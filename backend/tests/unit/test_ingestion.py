"""Ingestion: valid PDF, corrupted file, scanned PDF (OCR), empty document, large document, type sniffing."""
from __future__ import annotations

import time
from pathlib import Path

import pymupdf
import pytest

from app.core.exceptions import IngestionError, UnsupportedFileError
from app.ingestion.pipeline import ingest_bytes, sniff_kind
from app.utils.storage import LocalStorage
from tests.conftest import SAMPLE


def _make_pdf(pages: list[list[tuple[str, float]]]) -> bytes:
    doc = pymupdf.open()
    for lines in pages:
        page = doc.new_page()
        y = 72
        for text, size in lines:
            page.insert_text((72, y), text, fontsize=size, fontname="hebo" if size > 14 else "helv")
            y += size * 2
    out = doc.tobytes()
    doc.close()
    return out


def test_valid_pdf_extracts_structure_and_sections():
    pdf = _make_pdf([[("Quarterly Review", 22), ("1. Overview", 14), ("Revenue grew twelve percent during the quarter due to new customers.", 10.5),
                      ("2. Risks", 14), ("The supplier may terminate the agreement at any time without cause.", 10.5)]])
    res = ingest_bytes("review.pdf", pdf)
    types = [e.type for e in res.parsed.pages[0].elements]
    assert types.count("heading") >= 3
    assert not res.parsed.ocr_used  # native text layer: OCR must NOT run
    sections = {c.section for c in res.chunks}
    assert any("Overview" in (s or "") for s in sections) and any("Risks" in (s or "") for s in sections)
    assert all(c.page_number == 1 for c in res.chunks)


def test_corrupted_pdf_rejected():
    with pytest.raises(IngestionError):
        ingest_bytes("broken.pdf", b"%PDF-1.7\n1 0 obj << /Broken true >> garbage garbage")


def test_truncated_pdf_is_rejected_or_recovered_without_inventing_content():
    good = (SAMPLE / "invoice_inv2041.pdf").read_bytes()
    original_words = set(ingest_bytes("full.pdf", good).parsed.full_text.split())
    with pytest.raises(IngestionError):
        ingest_bytes("cut.pdf", good[: int(len(good) * 0.05)])  # header only: cannot be opened
    for frac in (0.2, 0.5, 0.8, 0.95):  # PyMuPDF may repair these; whatever it recovers must come from the source
        try:
            res = ingest_bytes("cut.pdf", good[: int(len(good) * frac)])
        except IngestionError:
            continue
        assert set(res.parsed.full_text.split()) <= original_words


def test_empty_file_rejected():
    with pytest.raises((IngestionError, UnsupportedFileError)):
        ingest_bytes("empty.txt", b"")


def test_blank_pdf_page_reports_no_content():
    doc = pymupdf.open()
    doc.new_page()
    data = doc.tobytes()
    with pytest.raises(IngestionError, match="No extractable content|no indexable"):
        ingest_bytes("blank.pdf", data)


@pytest.mark.slow
def test_scanned_pdf_uses_ocr_and_recovers_table():
    p = SAMPLE / "scanned_invoice_inv3307.pdf"
    res = ingest_bytes(p.name, p.read_bytes(), path=p)
    assert res.parsed.ocr_used and res.parsed.ocr_confidence and res.parsed.ocr_confidence > 0.6
    text = res.parsed.full_text.replace(" ", "")
    assert "INV-3307" in text and "5,150.00" in text
    tables = [e for e in res.parsed.all_elements() if e.type == "table"]
    assert tables and tables[0].data["headers"][0].lower().startswith("item")
    assert any(r[-1].startswith("$4,000") for r in tables[0].data["rows"])


def test_ocr_decision_is_automatic_for_native_pdf():
    p = SAMPLE / "invoice_inv2041.pdf"
    res = ingest_bytes(p.name, p.read_bytes(), path=p)
    assert not res.parsed.ocr_used and res.parsed.pages[0].method == "text"


def test_table_structure_preserved():
    p = SAMPLE / "invoice_inv2041.pdf"
    res = ingest_bytes(p.name, p.read_bytes(), path=p)
    tbl = next(e for e in res.parsed.all_elements() if e.type == "table")
    assert tbl.data["headers"] == ["Description", "Qty", "Unit Price", "Amount"]
    assert tbl.data["rows"][0][0] == "Platform licence"
    chunk = next(c for c in res.chunks if c.chunk_type == "table")
    assert "Description: Platform licence; Qty: 1" in chunk.text  # cell relationships serialised


@pytest.mark.slow
def test_large_document_processes_and_keeps_page_citations():
    lines = [[(f"Section {i}", 16), (f"Page {i} describes obligation number {i} and the payment of ${i * 1000} to the supplier.", 10.5)] for i in range(1, 121)]
    pdf = _make_pdf(lines)
    t = time.perf_counter()
    res = ingest_bytes("large.pdf", pdf)
    assert len(res.parsed.pages) == 120
    assert {c.page_number for c in res.chunks} == set(range(1, 121))  # a chunk never crosses a page
    assert time.perf_counter() - t < 60


def test_type_sniffing_requires_content_to_match_extension():
    pdf = (SAMPLE / "invoice_inv2041.pdf").read_bytes()
    with pytest.raises(UnsupportedFileError):
        sniff_kind("report.txt", pdf)  # PDF bytes pretending to be text
    with pytest.raises(UnsupportedFileError):
        sniff_kind("run.exe", b"MZ\x90\x00\x03\x00\x00\x00")
    assert sniff_kind("a.pdf", pdf)[1] == "pdf"


def test_spreadsheet_docx_and_text_parse():
    for name, kind in (("vendor_costs_fy2026.xlsx", "spreadsheet"), ("resume_jane_doe.docx", "docx"), ("information_security_policy.txt", "text")):
        p = SAMPLE / name
        res = ingest_bytes(name, p.read_bytes())
        assert res.kind == kind and res.chunks


def test_storage_blocks_path_traversal(tmp_path: Path):
    st = LocalStorage(tmp_path)
    st.save("ab/file.pdf", b"x")
    assert st.read("ab/file.pdf") == b"x"
    for bad in ("../outside.txt", "/etc/passwd", "ab/../../x", "..\\x"):
        with pytest.raises(Exception):
            st.save(bad, b"nope")
