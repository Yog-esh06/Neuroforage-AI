"""Layout model + heuristics.

Internal representation:  ParsedDocument -> ParsedPage -> ParsedElement
(heading | paragraph | list | table | image | figure | header | footer)

Every element keeps page number, bbox (when available), section path and type; these are the
coordinates later used for evidence citations and for highlighting in the document viewer.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from app.utils.text import normalize_text

ELEMENT_TYPES = ("heading", "paragraph", "list", "table", "image", "figure", "header", "footer")

_BULLET_RE = re.compile(r"^\s*(?:[••●▪◦\-\*–]|\(?\d{1,3}[\.\)]|\(?[a-zA-Z][\.\)]|\([ivx]+\))\s+\S")
_NUM_HEADING_RE = re.compile(r"^(?:(?:ARTICLE|SECTION|CHAPTER|Article|Section|Chapter)\s+[IVXLC\d]+[\.:]?\s*.*|\d{1,2}(?:\.\d{1,2}){0,3}\.?\s+[A-Z][^\n]{2,90})$")
_PAGE_NUM_RE = re.compile(r"^\s*(?:page\s+)?\d{1,4}\s*(?:of\s+\d{1,4})?\s*$", re.I)
_CAPTION_RE = re.compile(r"^\s*(figure|fig\.|chart|diagram|exhibit|graph)\s*\d+", re.I)
_FOOTER_WORDS = re.compile(r"confidential|all rights reserved|proprietary|©|copyright", re.I)


@dataclass
class ParsedElement:
    type: str
    text: str
    page_number: int
    bbox: list[float] | None = None
    section: str | None = None
    level: int | None = None
    data: dict[str, Any] | None = None
    confidence: float | None = None
    order: int = 0


@dataclass
class ParsedPage:
    page_number: int
    width: float | None = None
    height: float | None = None
    text: str = ""
    ocr_used: bool = False
    ocr_confidence: float | None = None
    method: str = "text"  # text | ocr | mixed | table-only
    elements: list[ParsedElement] = field(default_factory=list)


@dataclass
class ParsedDocument:
    kind: str  # pdf | image | spreadsheet | docx | text
    pages: list[ParsedPage] = field(default_factory=list)
    title: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def ocr_used(self) -> bool:
        return any(p.ocr_used for p in self.pages)

    @property
    def ocr_confidence(self) -> float | None:
        confs = [p.ocr_confidence for p in self.pages if p.ocr_confidence is not None]
        return round(sum(confs) / len(confs), 4) if confs else None

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages if p.text)

    def all_elements(self) -> list[ParsedElement]:
        return [e for p in self.pages for e in p.elements]


def looks_like_list_item(text: str) -> bool:
    lines = [l for l in text.split("\n") if l.strip()]
    return bool(lines) and sum(1 for l in lines if _BULLET_RE.match(l)) >= max(1, len(lines) // 2 + (len(lines) % 2 and 0))


def looks_like_numbered_heading(text: str) -> bool:
    t = text.strip()
    return len(t) < 110 and "\n" not in t and bool(_NUM_HEADING_RE.match(t)) and not t.endswith((",", ";", "."))


def is_caption(text: str) -> bool:
    return bool(_CAPTION_RE.match(text.strip()))


def is_page_number(text: str) -> bool:
    return bool(_PAGE_NUM_RE.match(text.strip()))


def looks_like_boilerplate_footer(text: str) -> bool:
    return is_page_number(text) or (len(text) < 140 and bool(_FOOTER_WORDS.search(text)))


def _skeleton(text: str) -> str:
    return re.sub(r"\d+", "#", re.sub(r"\s+", " ", text.strip().lower()))


def mark_headers_and_footers(pages: list[ParsedPage]) -> None:
    """Re-type edge-of-page paragraphs as header/footer.

    Multi-page documents: repeated (digit-normalized) text near the top/bottom margin on >=2 pages.
    Any document: bare page numbers and obvious boilerplate in the bottom margin.
    """
    if not pages:
        return
    top_counter: Counter[str] = Counter()
    bottom_counter: Counter[str] = Counter()
    for p in pages:
        h = p.height or 0
        if not h:
            continue
        seen_top, seen_bottom = set(), set()
        for e in p.elements:
            if e.bbox is None or e.type not in ("paragraph", "heading", "list"):
                continue
            if e.bbox[3] <= h * 0.09:
                seen_top.add(_skeleton(e.text))
            elif e.bbox[1] >= h * 0.91:
                seen_bottom.add(_skeleton(e.text))
        top_counter.update(seen_top)
        bottom_counter.update(seen_bottom)

    multi = len(pages) >= 3
    for p in pages:
        h = p.height or 0
        if not h:
            continue
        for e in p.elements:
            if e.bbox is None or e.type not in ("paragraph", "heading", "list"):
                continue
            sk = _skeleton(e.text)
            if e.bbox[3] <= h * 0.09 and ((multi and top_counter[sk] >= 2) or is_page_number(e.text)):
                e.type, e.level = "header", None
            elif e.bbox[1] >= h * 0.91 and (
                (multi and bottom_counter[sk] >= 2) or looks_like_boilerplate_footer(e.text)
            ):
                e.type, e.level = "footer", None


def assign_sections(pages: list[ParsedPage]) -> None:
    """Walk elements in reading order and attach the active heading path as `section`."""
    stack: list[tuple[int, str]] = []
    for p in pages:
        for e in sorted(p.elements, key=lambda x: x.order):
            if e.type == "heading":
                lvl = e.level or 1
                while stack and stack[-1][0] >= lvl:
                    stack.pop()
                stack.append((lvl, re.sub(r"\s+", " ", e.text.strip())[:140]))
                e.section = " > ".join(t for _, t in stack)
            elif e.type in ("header", "footer"):
                e.section = None
            else:
                e.section = " > ".join(t for _, t in stack) or None


def finalize_page_text(page: ParsedPage) -> None:
    """Page text = body elements in reading order (excluding headers/footers), tables flattened."""
    parts = []
    for e in sorted(page.elements, key=lambda x: x.order):
        if e.type in ("header", "footer"):
            continue
        if e.text:
            parts.append(e.text)
    page.text = normalize_text("\n\n".join(parts))


def union_bbox(boxes: list[list[float] | None]) -> list[float] | None:
    bs = [b for b in boxes if b]
    if not bs:
        return None
    return [min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs)]


def overlap_ratio(a: list[float], b: list[float]) -> float:
    """Fraction of `a`'s area covered by `b`."""
    ix0, iy0, ix1, iy1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    area = max((a[2] - a[0]) * (a[3] - a[1]), 1e-6)
    return ((ix1 - ix0) * (iy1 - iy0)) / area
