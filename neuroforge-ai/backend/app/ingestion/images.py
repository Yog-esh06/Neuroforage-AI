"""Image handling: preprocessing, OCR -> layout elements, and grid-table recovery for scanned pages."""
from __future__ import annotations

import statistics

import cv2
import numpy as np

from app.ingestion.layout import ParsedElement, ParsedPage, looks_like_list_item, looks_like_numbered_heading
from app.ingestion.ocr import OCRLine, run_ocr
from app.ingestion.tables import normalize_table, table_to_text


def decode_image(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Image could not be decoded")
    return img


def deskew(gray: np.ndarray) -> tuple[np.ndarray, float]:
    """Estimate skew from the minimum-area rectangle of dark pixels; rotate only for |angle| in (0.3, 15)."""
    inv = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(inv > 0))
    if len(coords) < 200:
        return gray, 0.0
    angle = cv2.minAreaRect(coords[:, ::-1].astype(np.float32))[-1]
    angle = angle - 90 if angle > 45 else angle
    if abs(angle) < 0.3 or abs(angle) > 15:
        return gray, 0.0
    h, w = gray.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(gray, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE), float(angle)


def preprocess_for_ocr(img: np.ndarray) -> np.ndarray:
    """Grayscale -> light denoise -> deskew. Returns a 3-channel image (engines expect colour/gray arrays)."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    # Cheap noise estimate (high-frequency residual); only pay for non-local-means denoising when the scan is noisy.
    residual = gray.astype(np.int16) - cv2.GaussianBlur(gray, (3, 3), 0).astype(np.int16)
    if float(np.abs(residual).mean()) > 2.5:
        small = cv2.fastNlMeansDenoising(gray, None, h=6, templateWindowSize=5, searchWindowSize=11)
        gray = small
    gray, _ = deskew(gray)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def detect_table_grids(img: np.ndarray, min_cells: int = 4) -> list[dict]:
    """Detect ruled tables: morphological line extraction -> cell rectangles -> row/column clustering.

    Returns [{"bbox": [x0,y0,x1,y1], "cells": [[x0,y0,x1,y1],...], "row_edges": [...], "col_edges": [...]}].
    Only ruled (bordered) tables are recovered; borderless layouts fall back to paragraph text.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    bw = cv2.adaptiveThreshold(~gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 15, -2)
    h, w = bw.shape
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(w // 30, 20), 1))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(h // 40, 15)))
    horiz = cv2.dilate(cv2.erode(bw, hk), hk)
    vert = cv2.dilate(cv2.erode(bw, vk), vk)
    grid = cv2.add(horiz, vert)
    grid = cv2.dilate(grid, np.ones((3, 3), np.uint8))

    contours, hier = cv2.findContours(~grid, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    cells = []
    for c in contours:
        x, y, cw, ch = cv2.boundingRect(c)
        if 12 < cw < w * 0.95 and 8 < ch < h * 0.5:
            cells.append([float(x), float(y), float(x + cw), float(y + ch)])
    if len(cells) < min_cells:
        return []

    # Group cells into tables by proximity of their union boxes (single-table scans are the common case).
    cells.sort(key=lambda b: (b[1], b[0]))
    groups: list[list[list[float]]] = []
    for cell in cells:
        placed = False
        for g in groups:
            gx0, gy0 = min(b[0] for b in g), min(b[1] for b in g)
            gx1, gy1 = max(b[2] for b in g), max(b[3] for b in g)
            if cell[0] >= gx0 - 20 and cell[2] <= gx1 + 20 and cell[1] <= gy1 + 25:
                g.append(cell)
                placed = True
                break
        if not placed:
            groups.append([cell])

    tables = []
    for g in groups:
        if len(g) < min_cells:
            continue
        rows = _cluster([(b[1] + b[3]) / 2 for b in g], tol=max(6.0, statistics.median(b[3] - b[1] for b in g) * 0.4))
        cols = _cluster([(b[0] + b[2]) / 2 for b in g], tol=max(8.0, statistics.median(b[2] - b[0] for b in g) * 0.3))
        if len(rows) < 2 or len(cols) < 2:
            continue
        tables.append({
            "bbox": [min(b[0] for b in g), min(b[1] for b in g), max(b[2] for b in g), max(b[3] for b in g)],
            "cells": g, "row_centers": rows, "col_centers": cols,
        })
    return tables


def _cluster(values: list[float], tol: float) -> list[float]:
    vals = sorted(values)
    clusters: list[list[float]] = [[vals[0]]]
    for v in vals[1:]:
        if v - clusters[-1][-1] <= tol:
            clusters[-1].append(v)
        else:
            clusters.append([v])
    return [sum(c) / len(c) for c in clusters]


def _nearest(centers: list[float], v: float) -> int:
    return min(range(len(centers)), key=lambda i: abs(centers[i] - v))


def table_from_grid(grid: dict, lines: list[OCRLine]) -> tuple[list[list[str]], list[OCRLine]]:
    """Fill the detected grid with OCR lines whose centres fall inside its cells. Returns (rows, consumed lines)."""
    rows_c, cols_c = grid["row_centers"], grid["col_centers"]
    matrix = [["" for _ in cols_c] for _ in rows_c]
    used: list[OCRLine] = []
    for ln in lines:
        cx, cy = (ln.bbox[0] + ln.bbox[2]) / 2, (ln.bbox[1] + ln.bbox[3]) / 2
        if not any(c[0] <= cx <= c[2] and c[1] <= cy <= c[3] for c in grid["cells"]):
            continue
        r, c = _nearest(rows_c, cy), _nearest(cols_c, cx)
        matrix[r][c] = (matrix[r][c] + " " + ln.text).strip()
        used.append(ln)
    return matrix, used


def lines_to_elements(lines: list[OCRLine], page_number: int, start_order: int = 0) -> list[ParsedElement]:
    """Group OCR lines into paragraphs/headings/lists using vertical gaps, alignment and relative line height."""
    if not lines:
        return []
    lines = sorted(lines, key=lambda l: (round(l.bbox[1] / 6), l.bbox[0]))
    heights = [l.bbox[3] - l.bbox[1] for l in lines]
    med_h = statistics.median(heights) or 10.0

    # Merge boxes on the same visual row (OCR often splits one row into several fragments).
    rows: list[list[OCRLine]] = []
    for ln in sorted(lines, key=lambda l: (l.bbox[1] + l.bbox[3]) / 2):
        cy = (ln.bbox[1] + ln.bbox[3]) / 2
        if rows and abs(cy - statistics.mean((l.bbox[1] + l.bbox[3]) / 2 for l in rows[-1])) < med_h * 0.5:
            rows[-1].append(ln)
        else:
            rows.append([ln])
    merged: list[OCRLine] = []
    for r in rows:
        r.sort(key=lambda l: l.bbox[0])
        merged.append(OCRLine(
            " ".join(l.text for l in r),
            [min(l.bbox[0] for l in r), min(l.bbox[1] for l in r), max(l.bbox[2] for l in r), max(l.bbox[3] for l in r)],
            sum(l.confidence for l in r) / len(r),
        ))

    paras: list[list[OCRLine]] = []
    for ln in merged:
        if paras:
            prev = paras[-1][-1]
            gap = ln.bbox[1] - prev.bbox[3]
            same_left = abs(ln.bbox[0] - prev.bbox[0]) < med_h * 2.5
            if gap < med_h * 0.9 and same_left and not looks_like_list_item(ln.text) \
                    and (ln.bbox[3] - ln.bbox[1]) < med_h * 1.35:
                paras[-1].append(ln)
                continue
        paras.append([ln])

    out: list[ParsedElement] = []
    order = start_order
    for p in paras:
        text = " ".join(l.text for l in p).strip()
        if not text:
            continue
        bbox = [min(l.bbox[0] for l in p), min(l.bbox[1] for l in p), max(l.bbox[2] for l in p), max(l.bbox[3] for l in p)]
        avg_h = statistics.mean(l.bbox[3] - l.bbox[1] for l in p)
        conf = sum(l.confidence for l in p) / len(p)
        if len(p) == 1 and len(text) < 100 and (avg_h > med_h * 1.3 or looks_like_numbered_heading(text) or
                                                (text.isupper() and len(text) > 3)):
            etype, level = "heading", (1 if avg_h > med_h * 1.6 else 2)
        elif all(looks_like_list_item(l.text) for l in p):
            etype, level = "list", None
        else:
            etype, level = "paragraph", None
        out.append(ParsedElement(etype, text, page_number, bbox, level=level, confidence=round(conf, 4), order=order))
        order += 1
    return out


def ocr_image_to_page(img: np.ndarray, page_number: int, scale: float = 1.0, *, preprocess: bool = True,
                      detect_tables: bool = True) -> ParsedPage:
    """Full scanned-page path: preprocess -> OCR -> table grids -> layout elements. `scale` maps pixels to page units."""
    proc = preprocess_for_ocr(img) if preprocess else img
    lines = run_ocr(proc)
    elements: list[ParsedElement] = []
    consumed: set[int] = set()
    order = 0

    if detect_tables:
        for grid in detect_table_grids(proc):
            matrix, used = table_from_grid(grid, lines)
            filled = sum(1 for r in matrix for c in r if c)
            if filled < 3:
                continue
            consumed.update(id(u) for u in used)
            norm = normalize_table(matrix)
            if not norm:
                continue
            elements.append(ParsedElement(
                "table", table_to_text(norm), page_number,
                [v / scale for v in grid["bbox"]], data={**norm, "source": "ocr-grid"},
                confidence=round(sum(u.confidence for u in used) / max(len(used), 1), 4), order=order,
            ))
            order += 1

    rest = [l for l in lines if id(l) not in consumed]
    for el in lines_to_elements(rest, page_number, start_order=order):
        if scale != 1.0 and el.bbox:
            el.bbox = [v / scale for v in el.bbox]
        elements.append(el)

    # Reading order: top-to-bottom by bbox.
    elements.sort(key=lambda e: (e.bbox[1] if e.bbox else 0, e.bbox[0] if e.bbox else 0))
    for i, e in enumerate(elements):
        e.order = i
    h, w = proc.shape[:2]
    conf = round(sum(l.confidence for l in lines) / len(lines), 4) if lines else None
    return ParsedPage(page_number, w / scale, h / scale, ocr_used=True, ocr_confidence=conf, method="ocr", elements=elements)
