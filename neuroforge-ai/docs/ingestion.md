# Ingestion, OCR and layout understanding

Code: `backend/app/ingestion/`, orchestrated by `services/document_service.py`.

```text
bytes → type sniffing → extraction → OCR (only if needed) → layout → normalisation → chunking
```

## 1. Validation (before anything is stored)

* Extension allow-list (`ALLOWED_EXTENSIONS`) **and** magic-byte sniffing: a PDF renamed `.txt`, or an executable renamed
  `.pdf`, is rejected with 415. ZIP-based files must really be `.docx`/`.xlsx`.
* Size limit (`MAX_UPLOAD_MB`) enforced by a bounded read (never buffers more than limit+1 bytes) → 413.
* Page limit (`MAX_PAGES`), password-protected PDFs and unopenable/corrupt files fail with a specific `IngestionError`
  and the document ends in `FAILED` with the reason shown in the UI.
* File names are reduced to a safe ASCII allow-list; storage keys are generated (`ab/<uuid>/v1/<safe name>`), and the
  local backend resolves every key against its root (path-traversal guard).
* Exact duplicates (same SHA-256) are detected and not re-processed.

## 2. Extraction by file kind

| Kind | Method |
|---|---|
| PDF | PyMuPDF text/layout dicts per page, `find_tables()`, image blocks, vector-drawing density for charts |
| Image | OpenCV preprocessing → OCR → grid-table recovery |
| XLSX / CSV | pandas; each sheet is a page containing a typed table |
| DOCX | python-docx walk of the body in order: Heading styles, lists, tables |
| TXT / MD | paragraph / heading / list heuristics (Markdown `#` aware) |

## 3. Automatic OCR decision (per page)

`needs_ocr(page, native_text)`: a page is OCR'd when it has fewer than `OCR_MIN_CHARS_PER_PAGE` characters of native text
*and* carries raster content (or is empty), or when its text layer is mostly non-alphabetic garbage. Native PDFs never
touch the OCR engine. Mixed documents are handled page by page; `pages.extraction_method` records `text`, `ocr`, `mixed`.

OCR engines (`OCR_ENGINE`): **RapidOCR** (ONNX Runtime, default, pure pip install) or **Tesseract** (if the binary and
`pytesseract` are present). If none is available, scanned pages are reported as warnings rather than silently dropped.

OCR pipeline (`ingestion/images.py`): sparse noise estimate → non-local-means denoise only when noisy → deskew
(min-area-rect, ±15°) → OCR → **ruled-table recovery** (morphological line extraction → cell rectangles → row/column
clustering → OCR boxes assigned to cells) → remaining boxes grouped into paragraphs/headings/lists by gaps, alignment and
relative height. Bounding boxes are scaled back to PDF points so they overlay the rendered page exactly.

Limitation: borderless scanned tables are not reconstructed; they come through as paragraph text.

## 4. Layout model

```text
Document
 └─ Page (number, width, height, extraction method, OCR confidence)
     └─ Element (heading | paragraph | list | table | image | figure | header | footer)
          page_number · bbox · section path · level · data (table cells) · confidence
```

* **Headings:** font size above body size (levels by size rank), all-bold short lines, or numbered/ARTICLE patterns.
  A text block that PyMuPDF merged across font styles is split on style changes first (`_style_groups`).
* **Lists:** bullet/number markers. A short larger/bold numbered line ("1. Term") is a heading, not a list.
* **Headers/footers:** edge-of-page text that repeats across pages (digit-normalised), bare page numbers, boilerplate.
* **Sections:** every element receives its heading path (`Agreement > 2. Fees and Payment`).
* **Captions:** "Figure N …" text is attached to the nearest image/figure.
* **Tables:** header detection, empty row/column removal, typed column profile, total-row reconciliation
  (`ai/extraction/tables.py`) — a stated total that does not equal the sum of its rows becomes a finding.

## 5. Chunking (`ingestion/chunking.py`)

* Never crosses a page (citations stay exact) or a section boundary; headers/footers are excluded.
* Prose is packed to ~170 words (cap 260) with one-sentence overlap on forced splits.
* Tables are separate chunks; each row is serialised `Header: value; Header: value`, so cell relationships survive in the
  text that is embedded and indexed. Long tables split into row groups.
* Each chunk stores page, section, element ids and the union bounding box used to highlight the citation.

## 6. Classification (`ai/extraction/classifier.py`)

Content-based, never filename-based: weighted phrase lexicons per class (saturating counts, boosted in the document
opening and in PDF title/subject), plus structural cues (tables + monetary density, numbered clauses + "shall" frequency,
citation markers, contact details). Output: `document_type`, `confidence`, `classification_method`, and the raw class
scores. Documents with too little evidence become `Unknown`. The confidence is an engineering score
(`0.55·margin-share + 0.45·evidence-strength`), not a probability. Measured precision/recall/F1: see
[evaluation.md](evaluation.md).
