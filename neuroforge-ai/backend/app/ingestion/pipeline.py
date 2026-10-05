"""Ingestion pipeline (pure, no database):

    bytes -> type detection -> extraction -> OCR if necessary -> layout processing -> normalisation -> chunking

Persistence and the later stages (embedding, knowledge extraction, analysis) are orchestrated by
`services/document_service.py`, which calls into this module.
"""
from __future__ import annotations

import logging
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.core.exceptions import IngestionError, UnsupportedFileError
from app.ingestion import formats
from app.ingestion.chunking import ChunkSpec, chunk_document
from app.ingestion.layout import ParsedDocument
from app.ingestion.pdf import parse_pdf

log = logging.getLogger(__name__)

MIME = {
    "pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "tif": "image/tiff",
    "tiff": "image/tiff", "bmp": "image/bmp", "webp": "image/webp", "txt": "text/plain", "md": "text/markdown",
    "csv": "text/csv", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_KIND = {"pdf": "pdf", "png": "image", "jpg": "image", "jpeg": "image", "tif": "image", "tiff": "image", "bmp": "image",
         "webp": "image", "txt": "text", "md": "text", "csv": "spreadsheet", "xlsx": "spreadsheet", "docx": "docx"}


@dataclass
class IngestionResult:
    parsed: ParsedDocument
    chunks: list[ChunkSpec]
    kind: str
    timings_ms: dict[str, int] = field(default_factory=dict)


def sniff_kind(filename: str, data: bytes) -> tuple[str, str]:
    """Detect (ext, kind) from magic bytes — the file name is only a hint and must agree with content."""
    ext = Path(filename).suffix.lower().lstrip(".")
    head = data[:16]
    if head.startswith(b"%PDF-"):
        detected = "pdf"
    elif head.startswith(b"\x89PNG\r\n\x1a\n"):
        detected = "png"
    elif head.startswith(b"\xff\xd8\xff"):
        detected = "jpg"
    elif head[:4] in (b"II*\x00", b"MM\x00*"):
        detected = "tiff"
    elif head.startswith(b"BM"):
        detected = "bmp"
    elif head[:4] == b"RIFF" and data[8:12] == b"WEBP":
        detected = "webp"
    elif head.startswith(b"PK\x03\x04"):
        detected = ext if ext in ("xlsx", "docx") else ""
        if not detected:
            raise UnsupportedFileError("ZIP-based file is neither .xlsx nor .docx")
    else:
        # Text-like formats: no NUL bytes and decodable
        if b"\x00" in data[:4096]:
            raise UnsupportedFileError("Unrecognised binary file type")
        if ext not in ("txt", "md", "csv"):
            raise UnsupportedFileError(f"File content does not match a supported type (extension .{ext or '?'})")
        detected = ext
    if ext and ext in _KIND and _KIND[ext] != _KIND[detected] and not (ext in ("jpg", "jpeg") and detected == "jpg"):
        raise UnsupportedFileError(f"Extension .{ext} does not match detected content type '{detected}'")
    return detected, _KIND[detected]


def parse_bytes(filename: str, data: bytes, *, path: Path | None = None) -> tuple[ParsedDocument, str]:
    ext, kind = sniff_kind(filename, data)
    if not data:
        raise IngestionError("File is empty")
    if kind == "pdf":
        if path is None:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as t:
                t.write(data)
                tmp = Path(t.name)
            try:
                return parse_pdf(tmp), kind
            finally:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:  # Windows may still hold the handle of a file that failed to open; cleanup is best-effort
                    log.debug("could not remove temp file %s", tmp)
        return parse_pdf(path), kind
    if kind == "image":
        return formats.parse_image(data), kind
    if kind == "spreadsheet":
        return formats.parse_spreadsheet(data, filename), kind
    if kind == "docx":
        return formats.parse_docx(data), kind
    return formats.parse_text(data, markdown=ext == "md"), kind


def ingest_bytes(filename: str, data: bytes, *, path: Path | None = None) -> IngestionResult:
    t0 = time.perf_counter()
    parsed, kind = parse_bytes(filename, data, path=path)
    t1 = time.perf_counter()
    total_chars = sum(len(p.text.strip()) for p in parsed.pages)
    if total_chars == 0 and not any(e.type == "table" for e in parsed.all_elements()):
        raise IngestionError("No extractable content found (document is empty or unreadable)")
    chunks = chunk_document(parsed)
    t2 = time.perf_counter()
    if not chunks:
        raise IngestionError("Document produced no indexable content")
    return IngestionResult(parsed, chunks, kind, {"extract_ms": int((t1 - t0) * 1000), "chunk_ms": int((t2 - t1) * 1000)})
