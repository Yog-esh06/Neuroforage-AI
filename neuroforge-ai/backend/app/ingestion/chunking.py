"""Structure-aware chunking.

Rules:
  * A chunk never crosses a page boundary (keeps page citations exact) or a section boundary.
  * Prose is packed up to TARGET_WORDS (hard cap MAX_WORDS) with a one-sentence overlap on forced splits.
  * Tables become their own chunks; each row is serialised as "Header: value; ..." so cell relationships
    survive in text, and long tables are split into row groups that repeat the header context.
  * Headers/footers are excluded from chunks; headings are kept at the start of the section's first chunk.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.ingestion.layout import ParsedDocument, ParsedElement, union_bbox
from app.ingestion.tables import row_to_sentence
from app.utils.text import split_sentences, word_count

TARGET_WORDS = 170
MAX_WORDS = 260
TABLE_ROWS_PER_CHUNK = 15


@dataclass
class ChunkSpec:
    page_number: int
    section: str | None
    text: str
    chunk_type: str = "text"
    element_keys: list[tuple[int, int]] = field(default_factory=list)  # (page_number, element order)
    bbox: list[float] | None = None

    @property
    def token_count(self) -> int:
        return word_count(self.text)


def _table_chunks(el: ParsedElement) -> list[ChunkSpec]:
    data = el.data or {}
    headers, rows = data.get("headers") or [], data.get("rows") or []
    prefix = f"Table{(' — ' + el.section) if el.section else ''}"
    if not rows:
        return [ChunkSpec(el.page_number, el.section, f"{prefix}\n{el.text}", "table", [(el.page_number, el.order)], el.bbox)] if el.text else []
    out = []
    has_header = data.get("has_header", True)
    for i in range(0, len(rows), TABLE_ROWS_PER_CHUNK):
        group = rows[i:i + TABLE_ROWS_PER_CHUNK]
        lines = [row_to_sentence(headers, r) if has_header else " | ".join(r) for r in group]
        head = f"{prefix} (columns: {', '.join(headers)})" if has_header else prefix
        out.append(ChunkSpec(el.page_number, el.section, head + "\n" + "\n".join(lines), "table",
                             [(el.page_number, el.order)], el.bbox))
    return out


def chunk_document(doc: ParsedDocument) -> list[ChunkSpec]:
    chunks: list[ChunkSpec] = []
    for page in doc.pages:
        buf: list[ParsedElement] = []
        buf_words = 0
        buf_section: str | None = None

        def flush():
            nonlocal buf, buf_words
            if not buf:
                return
            text = "\n".join(e.text for e in buf).strip()
            if text:
                chunks.append(ChunkSpec(page.page_number, buf_section, text, "text",
                                        [(e.page_number, e.order) for e in buf], union_bbox([e.bbox for e in buf])))
            buf, buf_words = [], 0

        for el in sorted(page.elements, key=lambda e: e.order):
            if el.type in ("header", "footer"):
                continue
            if el.type == "table":
                flush()
                chunks.extend(_table_chunks(el))
                continue
            if el.type in ("image", "figure") and not el.text:
                continue
            if not el.text.strip():
                continue
            if el.type == "heading":
                flush()
                buf_section = el.section
                buf.append(el)
                buf_words = word_count(el.text)
                continue
            if el.section != buf_section and buf:
                flush()
            buf_section = el.section if not buf else buf_section
            w = word_count(el.text)
            if w > MAX_WORDS:  # split an oversized paragraph on sentence boundaries with 1-sentence overlap
                flush()
                buf_section = el.section
                sents = split_sentences(el.text) or [el.text]
                cur: list[str] = []
                cur_w = 0
                for s in sents:
                    sw = word_count(s)
                    if cur and cur_w + sw > TARGET_WORDS:
                        chunks.append(ChunkSpec(page.page_number, el.section, " ".join(cur), "text", [(el.page_number, el.order)], el.bbox))
                        cur, cur_w = [cur[-1]], word_count(cur[-1])
                    cur.append(s)
                    cur_w += sw
                if cur:
                    chunks.append(ChunkSpec(page.page_number, el.section, " ".join(cur), "text", [(el.page_number, el.order)], el.bbox))
                continue
            if buf_words + w > TARGET_WORDS and buf:
                flush()
                buf_section = el.section
            buf.append(el)
            buf_words += w
        flush()
    # Drop fragments that carry no information (e.g. a lone heading with no body on the page).
    return [c for c in chunks if c.chunk_type == "table" or word_count(c.text) >= 3]
