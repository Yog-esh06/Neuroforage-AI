"""PDF parsing with PyMuPDF. Per page: native text/layout, tables, images/figures, or OCR for scanned pages."""
from __future__ import annotations

import logging
import re
import statistics
from collections import Counter
from pathlib import Path

import pymupdf as fitz  # PyMuPDF
import numpy as np

from app.core.config import get_settings
from app.core.exceptions import IngestionError
from app.ingestion import images as img_mod
from app.ingestion.layout import (ParsedDocument, ParsedElement, ParsedPage, assign_sections, finalize_page_text,
                                  is_caption, looks_like_list_item, looks_like_numbered_heading,
                                  mark_headers_and_footers, overlap_ratio)
from app.ingestion.ocr import OCRUnavailable, get_ocr_engine
from app.ingestion.tables import normalize_table, table_to_text
from app.utils.text import normalize_text

log = logging.getLogger(__name__)
OCR_DPI = 200


def needs_ocr(page: fitz.Page, native_text: str) -> bool:
    """A page needs OCR when it has (almost) no extractable text but carries raster content,
    or when its text layer is garbage (very low alphabetic ratio)."""
    s = get_settings()
    stripped = native_text.strip()
    if len(stripped) >= s.ocr_min_chars_per_page:
        alpha = sum(ch.isalpha() for ch in stripped) / max(len(stripped), 1)
        return alpha < 0.35 and bool(page.get_images(full=True))
    has_raster = bool(page.get_images(full=True))
    has_vector_text_hint = len(page.get_drawings()) > 0 and not has_raster
    return has_raster or (not stripped and not has_vector_text_hint and page.rect.width > 0)


def _body_font_size(doc: fitz.Document, sample_pages: int = 12) -> float:
    sizes: Counter[float] = Counter()
    for pno in range(min(len(doc), sample_pages)):
        for b in doc[pno].get_text("dict")["blocks"]:
            for ln in b.get("lines", []):
                for sp in ln["spans"]:
                    n = len(sp["text"].strip())
                    if n:
                        sizes[round(sp["size"], 1)] += n
    return sizes.most_common(1)[0][0] if sizes else 11.0


def _heading_levels(sizes_seen: list[float], body: float) -> dict[float, int]:
    larger = sorted({round(s, 1) for s in sizes_seen if s >= body * 1.12}, reverse=True)
    return {s: min(i + 1, 4) for i, s in enumerate(larger)}


def _style_groups(block: dict) -> list[dict]:
    """Split a PyMuPDF text block into runs of lines that share a font style (size + boldness).

    PyMuPDF sometimes merges adjacent lines of different styles (e.g. a heading directly above a paragraph) into one block;
    splitting on style changes keeps headings separate so sections and citations stay correct.
    """
    groups: list[dict] = []
    for ln in block.get("lines", []):
        t = "".join(sp["text"] for sp in ln["spans"]).strip()
        if not t:
            continue
        chars = sum(len(sp["text"].strip()) for sp in ln["spans"])
        bold = sum(len(sp["text"].strip()) for sp in ln["spans"] if sp["flags"] & 16 or "bold" in sp["font"].lower())
        size = max(sp["size"] for sp in ln["spans"])
        is_bold = chars > 0 and bold / chars > 0.8
        lb = [float(v) for v in ln["bbox"]]
        g = groups[-1] if groups else None
        if g and abs(g["size"] - size) < 0.6 and g["is_bold"] == is_bold:
            g["lines"].append(t)
            g["chars"] += chars
            g["bold"] += bold
            g["bbox"] = [min(g["bbox"][0], lb[0]), min(g["bbox"][1], lb[1]), max(g["bbox"][2], lb[2]), max(g["bbox"][3], lb[3])]
        else:
            groups.append({"lines": [t], "chars": chars, "bold": bold, "size": size, "is_bold": is_bold, "bbox": lb})
    return groups


def _parse_native_page(page: fitz.Page, body_size: float, levels: dict[float, int]) -> ParsedPage:
    pno = page.number + 1
    rect = page.rect
    pp = ParsedPage(pno, rect.width, rect.height, method="text")
    elements: list[ParsedElement] = []

    # --- tables first, so overlapping text blocks can be suppressed
    table_boxes: list[list[float]] = []
    try:
        finder = page.find_tables()
        for t in finder.tables:
            norm = normalize_table(t.extract())
            if not norm or norm["n_rows"] < 1 or norm["n_cols"] < 2:
                continue
            bbox = [float(v) for v in t.bbox]
            table_boxes.append(bbox)
            elements.append(ParsedElement("table", table_to_text(norm), pno, bbox, data=norm, confidence=0.9))
    except Exception as e:  # find_tables is best-effort
        log.debug("find_tables failed on page %s: %s", pno, e)

    # --- text blocks
    d = page.get_text("dict")
    for b in d["blocks"]:
        bbox = [float(v) for v in b["bbox"]]
        if b["type"] == 1:  # image block
            if (bbox[2] - bbox[0]) > 40 and (bbox[3] - bbox[1]) > 40:
                elements.append(ParsedElement("image", "", pno, bbox, data={"width": b.get("width"), "height": b.get("height")}))
            continue
        if any(overlap_ratio(bbox, tb) > 0.6 for tb in table_boxes):
            continue
        for grp in _style_groups(b):
            lines_txt, chars, bold_chars, max_size, gbox = grp["lines"], grp["chars"], grp["bold"], grp["size"], grp["bbox"]
            joined = "\n".join(lines_txt)
            flat = " ".join(lines_txt)
            all_bold = chars > 0 and bold_chars / chars > 0.8
            size = round(max_size, 1)
            short = len(flat) < 120 and len(lines_txt) <= 2
            # A short, larger/bold or numbered-title block is a heading even when it starts with "1." (numbering != list)
            is_heading = short and (
                (size in levels and size >= body_size * 1.12)
                or (all_bold and not flat.endswith((".", ",", ";")) and len(flat.split()) <= 12)
                or looks_like_numbered_heading(flat)
            )
            is_list = (not is_heading) and looks_like_list_item(joined)
            text = joined if is_list else flat  # re-flow wrapped paragraph lines
            if is_heading:
                lvl = levels.get(size, 3 if all_bold else 2)
                elements.append(ParsedElement("heading", normalize_text(text), pno, gbox, level=lvl))
            elif is_list:
                elements.append(ParsedElement("list", normalize_text(text), pno, gbox))
            else:
                elements.append(ParsedElement("paragraph", normalize_text(text), pno, gbox,
                                              data={"caption": True} if is_caption(text) else None))

    # --- vector charts: dense drawings outside tables become figures
    try:
        drawings = [dr["rect"] for dr in page.get_drawings() if dr.get("rect") is not None]
        outside = [r for r in drawings if not any(overlap_ratio([r.x0, r.y0, r.x1, r.y1], tb) > 0.5 for tb in table_boxes)]
        if len(outside) >= 25:
            u = fitz.Rect(outside[0])
            for r in outside[1:]:
                u |= r
            if u.width > 100 and u.height > 70 and u.width < rect.width * 0.98:
                elements.append(ParsedElement("figure", "", pno, [u.x0, u.y0, u.x1, u.y1],
                                              data={"kind": "vector-chart", "drawing_ops": len(outside)}))
    except Exception:
        pass

    # --- reading order: top-to-bottom, left-to-right with simple column awareness
    elements.sort(key=lambda e: (round(e.bbox[1] / 4) if e.bbox else 0, e.bbox[0] if e.bbox else 0))
    for i, e in enumerate(elements):
        e.order = i

    # attach captions to figures/images directly above or below them
    visuals = [e for e in elements if e.type in ("image", "figure")]
    for cap in [e for e in elements if e.data and e.data.get("caption")]:
        near = min(visuals, key=lambda v: abs(v.bbox[3] - cap.bbox[1]) if v.bbox[3] <= cap.bbox[1] + 5
                   else abs(v.bbox[1] - cap.bbox[3]), default=None) if visuals else None
        if near is not None and near.type in ("image", "figure"):
            near.text = cap.text
            near.type = "figure"
    pp.elements = elements
    pp.text = normalize_text(page.get_text("text"))
    return pp


def _ocr_page(page: fitz.Page, pno: int) -> ParsedPage:
    zoom = OCR_DPI / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csRGB, alpha=False)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)[:, :, ::-1].copy()  # RGB->BGR
    pp = img_mod.ocr_image_to_page(arr, pno, scale=zoom)
    pp.width, pp.height = page.rect.width, page.rect.height
    return pp


def parse_pdf(path: Path) -> ParsedDocument:
    s = get_settings()
    try:
        doc = fitz.open(path)
    except Exception as e:
        raise IngestionError(f"PDF could not be opened (corrupted or not a PDF): {e}") from e
    try:
        if doc.needs_pass:
            raise IngestionError("PDF is password protected")
        if len(doc) == 0:
            raise IngestionError("PDF has no pages")
        if len(doc) > s.max_pages:
            raise IngestionError(f"PDF has {len(doc)} pages; limit is {s.max_pages}")

        out = ParsedDocument(kind="pdf")
        md = doc.metadata or {}
        out.meta = {k: v for k, v in md.items() if v and k in ("title", "author", "subject", "creationDate", "producer", "keywords")}
        out.title = (md.get("title") or "").strip() or None

        body = _body_font_size(doc)
        size_pool = [round(sp["size"], 1) for pno in range(min(len(doc), 12)) for b in doc[pno].get_text("dict")["blocks"]
                     for ln in b.get("lines", []) for sp in ln["spans"] if sp["text"].strip()]
        levels = _heading_levels(size_pool, body)

        for page in doc:
            native = page.get_text("text")
            if needs_ocr(page, native):
                if get_ocr_engine() is None:
                    out.warnings.append(f"page {page.number + 1}: scanned page but no OCR engine available")
                    pp = _parse_native_page(page, body, levels)
                    pp.method = "text-no-ocr"
                else:
                    try:
                        pp = _ocr_page(page, page.number + 1)
                        # Mixed pages: keep real vector tables/text that native extraction found beyond the scan image
                        if len(native.strip()) >= s.ocr_min_chars_per_page:
                            pp.method = "mixed"
                    except OCRUnavailable as e:
                        out.warnings.append(f"page {page.number + 1}: {e}")
                        pp = _parse_native_page(page, body, levels)
            else:
                pp = _parse_native_page(page, body, levels)
            out.pages.append(pp)

        mark_headers_and_footers(out.pages)
        assign_sections(out.pages)
        for pp in out.pages:
            finalize_page_text(pp)
        if not out.title:
            first_heading = next((e.text for e in out.all_elements() if e.type == "heading"), None)
            out.title = first_heading[:200] if first_heading else None
        return out
    finally:
        doc.close()


def render_page_png(path: Path, page_number: int, zoom: float = 1.6) -> bytes:
    doc = fitz.open(path)
    try:
        if page_number < 1 or page_number > len(doc):
            raise IngestionError(f"Page {page_number} out of range (1..{len(doc)})")
        pix = doc[page_number - 1].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return pix.tobytes("png")
    finally:
        doc.close()
