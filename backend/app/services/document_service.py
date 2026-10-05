"""Document lifecycle: validated upload -> asynchronous processing -> READY.

Status machine:  QUEUED -> PROCESSING -> INDEXING -> READY   (any stage may end in FAILED)
Stages: extract/OCR/layout/chunk (PROCESSING) -> classify -> embed + knowledge graph (INDEXING) -> insights/contradictions -> workflows.
"""
from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from app.ai.embeddings.encoder import get_encoder
from app.ai.extraction.classifier import classify
from app.core.config import get_settings
from app.core.exceptions import ConflictError, FileTooLargeError, IngestionError, NotFoundError, UnsupportedFileError, ValidationFailed
from app.core.security import safe_filename
from app.db.base import utcnow
from app.db.models.document import (Chunk, Document, DocumentElement, DocumentVersion, Embedding, Page, ProcessingJob)
from app.db.models.user import User
from app.db.session import session_scope
from app.ingestion.pipeline import MIME, ingest_bytes, sniff_kind
from app.knowledge.builder import build_for_chunks, clear_document_knowledge
from app.services import audit_service
from app.services.index_registry import invalidate_all
from app.utils.hashing import sha256_bytes
from app.utils.storage import get_storage

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ upload
def validate_upload(filename: str, data: bytes) -> tuple[str, str, str]:
    s = get_settings()
    if not filename or not filename.strip():
        raise ValidationFailed("File name is required")
    if len(data) == 0:
        raise ValidationFailed("Uploaded file is empty")
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise FileTooLargeError(f"File exceeds the {s.max_upload_mb} MB limit")
    safe = safe_filename(filename)
    ext = Path(safe).suffix.lower().lstrip(".")
    if ext not in s.allowed_ext_set:
        raise UnsupportedFileError(f"Unsupported file type '.{ext}'", details={"allowed": sorted(s.allowed_ext_set)})
    detected, kind = sniff_kind(safe, data)  # raises UnsupportedFileError when content disagrees with the extension
    return safe, detected, kind


def _storage_key(doc_uuid: str, version: int, safe: str) -> str:
    return f"{doc_uuid[:2]}/{doc_uuid}/v{version}/{safe}"


def create_document(db: Session, user: User | None, filename: str, data: bytes) -> tuple[Document, bool]:
    """Store the file and queue processing. Returns (document, duplicate)."""
    safe, ext, kind = validate_upload(filename, data)
    digest = sha256_bytes(data)
    existing = db.query(Document).filter(Document.sha256 == digest, Document.status != "FAILED").first()
    if existing:
        return existing, True
    key = _storage_key(uuid.uuid4().hex, 1, safe)
    get_storage().save(key, data)
    doc = Document(filename=filename[:255], safe_name=safe, mime_type=MIME.get(ext, "application/octet-stream"), file_kind=kind,
                   size_bytes=len(data), sha256=digest, storage_key=key, status="QUEUED", owner_id=user.id if user and user.id else None)
    db.add(doc)
    db.flush()
    db.add(DocumentVersion(document_id=doc.id, version=1, sha256=digest, storage_key=key, size_bytes=len(data), created_by=doc.owner_id))
    db.add(ProcessingJob(document_id=doc.id, status="QUEUED", stage="queued"))
    audit_service.log_event(db, action="document_uploaded", user=user, entity_type="document", entity_id=doc.id, document_id=doc.id,
                            summary=f"Uploaded {safe} ({len(data)} bytes)", details={"sha256": digest, "kind": kind})
    db.commit()
    return doc, False


def add_version(db: Session, user: User | None, doc_id: int, filename: str, data: bytes) -> Document:
    doc = get_document(db, doc_id)
    safe, _, kind = validate_upload(filename, data)
    digest = sha256_bytes(data)
    if digest == doc.sha256:
        raise ConflictError("Uploaded file is identical to the current version")
    version = doc.current_version + 1
    key = _storage_key(uuid.uuid4().hex, version, safe)
    get_storage().save(key, data)
    db.add(DocumentVersion(document_id=doc.id, version=version, sha256=digest, storage_key=key, size_bytes=len(data), created_by=user.id if user and user.id else None))
    doc.current_version, doc.sha256, doc.storage_key, doc.size_bytes = version, digest, key, len(data)
    doc.filename, doc.safe_name, doc.file_kind, doc.status, doc.error = filename[:255], safe, kind, "QUEUED", None
    db.add(ProcessingJob(document_id=doc.id, status="QUEUED", stage="queued"))
    audit_service.log_event(db, action="document_version_added", user=user, entity_type="document", entity_id=doc.id, document_id=doc.id,
                            summary=f"Version {version} uploaded", details={"sha256": digest})
    db.commit()
    return doc


def get_document(db: Session, doc_id: int) -> Document:
    d = db.get(Document, doc_id)
    if not d:
        raise NotFoundError(f"Document {doc_id} not found")
    return d


def delete_document(db: Session, user: User | None, doc_id: int) -> None:
    doc = get_document(db, doc_id)
    keys = [v.storage_key for v in doc.versions]
    clear_document_knowledge(db, doc.id)
    name = doc.filename
    db.delete(doc)
    audit_service.log_event(db, action="document_deleted", user=user, entity_type="document", entity_id=doc_id, document_id=doc_id,
                            summary=f"Deleted {name}")
    db.commit()
    for k in keys:
        try:
            get_storage().delete(k)
        except Exception:  # storage cleanup is best-effort
            log.warning("could not delete stored object %s", k)
    invalidate_all()


# ------------------------------------------------------------------ processing
def _set_stage(db: Session, doc: Document, job: ProcessingJob, status: str, stage: str, progress: float) -> None:
    doc.status, job.status, job.stage, job.progress = status, status, stage, progress
    db.commit()


def _clear_derived(db: Session, doc: Document) -> None:
    clear_document_knowledge(db, doc.id)
    db.query(Embedding).filter(Embedding.document_id == doc.id).delete(synchronize_session=False)
    db.query(Chunk).filter(Chunk.document_id == doc.id).delete(synchronize_session=False)
    db.query(DocumentElement).filter(DocumentElement.document_id == doc.id).delete(synchronize_session=False)
    db.query(Page).filter(Page.document_id == doc.id).delete(synchronize_session=False)
    db.flush()


def process_document(document_id: int) -> None:
    """Full pipeline; safe to call from a thread or Celery worker. Never raises (failures are recorded)."""
    from app.services import insight_service  # local import: avoids import cycles at module load
    from app.workflows import engine as wf_engine

    t_start = time.perf_counter()
    timings: dict[str, int] = {}
    with session_scope() as db:
        doc = db.get(Document, document_id)
        if not doc:
            return
        job = db.query(ProcessingJob).filter(ProcessingJob.document_id == doc.id).order_by(ProcessingJob.id.desc()).first() or ProcessingJob(document_id=doc.id)
        if job.id is None:
            db.add(job)
            db.flush()
        job.attempts += 1
        job.started_at, job.finished_at, job.error, doc.error = utcnow(), None, None, None
        try:
            _set_stage(db, doc, job, "PROCESSING", "extracting", 0.05)
            storage = get_storage()
            data = storage.read(doc.storage_key)
            path = storage.local_path(doc.storage_key) if doc.file_kind == "pdf" else None
            result = ingest_bytes(doc.safe_name, data, path=path)
            timings.update(result.timings_ms)
            parsed = result.parsed

            _clear_derived(db, doc)
            _set_stage(db, doc, job, "PROCESSING", "layout", 0.3)
            element_ids: dict[tuple[int, int], int] = {}
            for pp in parsed.pages:
                page = Page(document_id=doc.id, page_number=pp.page_number, width=pp.width, height=pp.height, text=pp.text,
                            ocr_used=pp.ocr_used, ocr_confidence=pp.ocr_confidence, extraction_method=pp.method)
                db.add(page)
                db.flush()
                for el in pp.elements:
                    row = DocumentElement(document_id=doc.id, page_id=page.id, page_number=pp.page_number, order_idx=el.order,
                                          element_type=el.type, text=el.text, bbox=el.bbox, section=el.section, level=el.level,
                                          data=el.data, confidence=el.confidence)
                    db.add(row)
                    db.flush()
                    element_ids[(pp.page_number, el.order)] = row.id
            chunk_rows: list[Chunk] = []
            for i, cs in enumerate(result.chunks):
                ch = Chunk(document_id=doc.id, chunk_index=i, page_number=cs.page_number, section=cs.section, chunk_type=cs.chunk_type,
                           text=cs.text, token_count=cs.token_count, element_ids=[element_ids[k] for k in cs.element_keys if k in element_ids],
                           bbox=cs.bbox)
                db.add(ch)
                chunk_rows.append(ch)
            db.flush()

            n_tables = sum(1 for e in parsed.all_elements() if e.type == "table")
            cls = classify(parsed.full_text, n_tables=n_tables, kind=parsed.kind, n_pages=len(parsed.pages), meta=parsed.meta, title=parsed.title)
            doc.doc_type, doc.doc_type_confidence, doc.classification_method = cls.document_type, cls.confidence, cls.method
            doc.classification_detail = {"scores": cls.scores, "signals": cls.top_signals}
            doc.page_count, doc.ocr_used, doc.ocr_confidence = len(parsed.pages), parsed.ocr_used, parsed.ocr_confidence
            doc.title = parsed.title
            doc.meta = {**(doc.meta or {}), **parsed.meta, "warnings": parsed.warnings, "n_chunks": len(chunk_rows), "n_tables": n_tables}
            db.commit()

            _set_stage(db, doc, job, "INDEXING", "embedding", 0.55)
            t = time.perf_counter()
            enc = get_encoder()
            texts = [f"{c.section or ''}\n{c.text}".strip() for c in chunk_rows]
            for i in range(0, len(texts), 64):
                vecs = enc.encode(texts[i:i + 64])
                for c, v in zip(chunk_rows[i:i + 64], vecs):
                    db.add(Embedding(chunk_id=c.id, document_id=doc.id, model=enc.name, dim=int(v.shape[0]), vector=np.asarray(v, dtype=np.float32).tobytes()))
            db.commit()
            timings["embed_ms"] = int((time.perf_counter() - t) * 1000)

            _set_stage(db, doc, job, "INDEXING", "knowledge", 0.7)
            t = time.perf_counter()
            kstats = build_for_chunks(db, doc.id, chunk_rows)
            db.commit()
            timings["knowledge_ms"] = int((time.perf_counter() - t) * 1000)
            doc.meta = {**doc.meta, "entities_created": kstats.entities_created, "mentions": kstats.mentions, "relationships": kstats.relationships}
            invalidate_all()

            _set_stage(db, doc, job, "INDEXING", "analysis", 0.85)
            t = time.perf_counter()
            doc.status = "INDEXING"
            insight_service.analyze_document(db, doc)
            insight_service.scan_contradictions(db, doc)
            db.commit()
            timings["analysis_ms"] = int((time.perf_counter() - t) * 1000)

            doc.status, job.status, job.stage, job.progress = "READY", "READY", "ready", 1.0
            doc.processed_at = job.finished_at = utcnow()
            doc.processing_ms = int((time.perf_counter() - t_start) * 1000)
            job.stage_timings_ms = timings
            wf_engine.fire(db, "document_ready", {"document": wf_engine.document_ctx(doc, db)}, "document", doc.id)
            audit_service.log_event(db, action="document_processed", entity_type="document", entity_id=doc.id, document_id=doc.id,
                                    summary=f"{doc.filename} processed: {doc.doc_type} ({doc.doc_type_confidence:.2f}), {doc.page_count} page(s)",
                                    details={"timings_ms": timings, "ocr_used": doc.ocr_used, "classification": cls.scores, "stats": doc.meta})
            db.commit()
            invalidate_all()
        except Exception as e:
            db.rollback()
            log.exception("processing failed for document %s", document_id)
            msg = e.message if isinstance(e, IngestionError) else f"{type(e).__name__}: {e}"
            doc = db.get(Document, document_id)
            job = db.query(ProcessingJob).filter(ProcessingJob.document_id == document_id).order_by(ProcessingJob.id.desc()).first()
            if doc:
                doc.status, doc.error = "FAILED", str(msg)[:1000]
                doc.processing_ms = int((time.perf_counter() - t_start) * 1000)
            if job:
                job.status, job.stage, job.error, job.finished_at = "FAILED", "failed", str(msg)[:1000], utcnow()
            audit_service.log_event(db, action="document_failed", entity_type="document", entity_id=document_id, document_id=document_id,
                                    summary=f"Processing failed: {str(msg)[:200]}", details={"error": str(msg)[:1000]})
            db.commit()
            invalidate_all()


def page_image(db: Session, doc_id: int, page: int) -> tuple[bytes, str]:
    from app.ingestion.pdf import render_page_png

    doc = get_document(db, doc_id)
    storage = get_storage()
    if doc.file_kind == "pdf":
        return render_page_png(storage.local_path(doc.storage_key), page), "image/png"
    if doc.file_kind == "image":
        if page != 1:
            raise NotFoundError("Images have a single page")
        return storage.read(doc.storage_key), doc.mime_type
    raise NotFoundError("No visual rendering is available for this file type; use the extracted text view")
