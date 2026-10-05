from __future__ import annotations

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import FileTooLargeError, NotFoundError, ValidationFailed
from app.core.security import get_current_user, require_role
from app.db.models.document import Chunk, Document, DocumentElement, Page, ProcessingJob
from app.db.models.knowledge import Entity, EntityMention
from app.db.models.reasoning import Contradiction, Insight
from app.db.models.user import User
from app.db.session import get_db
from app.ai.extraction.tables import cell_relationships, profile_table
from app.schemas.serializers import contradiction_out, document_out, insight_out
from app.services import audit_service, document_service
from app.utils.storage import get_storage
from app.workers.ingestion_tasks import enqueue_processing

router = APIRouter(prefix="/documents", tags=["documents"])


def _job(db: Session, doc_id: int) -> ProcessingJob | None:
    return db.query(ProcessingJob).filter(ProcessingJob.document_id == doc_id).order_by(ProcessingJob.id.desc()).first()


@router.post("", status_code=202)
async def upload(response: Response, file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(require_role("analyst"))):
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)  # bounded read: never buffers more than limit+1 bytes
    if len(data) > limit:
        raise FileTooLargeError(f"File exceeds the {get_settings().max_upload_mb} MB limit")
    doc, duplicate = document_service.create_document(db, user, file.filename or "", data)
    if duplicate:
        response.status_code = 200
        return {"duplicate": True, "document": document_out(doc, _job(db, doc.id))}
    backend = enqueue_processing(doc.id)
    db.refresh(doc)
    return {"duplicate": False, "queue": backend, "document": document_out(doc, _job(db, doc.id))}


@router.get("")
def list_documents(q: str | None = Query(None, max_length=200), status: str | None = None, document_type: str | None = None,
                   ids: str | None = Query(None, description="comma-separated ids"), sort: str = Query("created_desc", pattern="^(created_desc|created_asc|name|type)$"),
                   limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    qry = db.query(Document)
    if q:
        like = f"%{q}%"
        qry = qry.filter(or_(Document.filename.ilike(like), Document.title.ilike(like)))
    if status:
        qry = qry.filter(Document.status == status.upper())
    if document_type:
        qry = qry.filter(Document.doc_type == document_type)
    if ids:
        try:
            qry = qry.filter(Document.id.in_([int(i) for i in ids.split(",") if i.strip()]))
        except ValueError as e:
            raise ValidationFailed("ids must be comma-separated integers") from e
    total = qry.count()
    order = {"created_desc": Document.id.desc(), "created_asc": Document.id.asc(), "name": Document.filename.asc(), "type": Document.doc_type.asc()}[sort]
    rows = qry.order_by(order).offset(offset).limit(limit).all()
    jobs = {j.document_id: j for j in db.query(ProcessingJob).filter(ProcessingJob.document_id.in_([d.id for d in rows])).order_by(ProcessingJob.id).all()} if rows else {}
    return {"total": total, "items": [document_out(d, jobs.get(d.id)) for d in rows]}


@router.get("/{doc_id}")
def get_document(doc_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    d = document_service.get_document(db, doc_id)
    counts = {
        "chunks": db.query(func.count(Chunk.id)).filter(Chunk.document_id == doc_id).scalar(),
        "entities": db.query(func.count(func.distinct(EntityMention.entity_id))).filter(EntityMention.document_id == doc_id).scalar(),
        "insights": db.query(func.count(Insight.id)).filter(Insight.document_id == doc_id).scalar(),
        "tables": db.query(func.count(DocumentElement.id)).filter(DocumentElement.document_id == doc_id, DocumentElement.element_type == "table").scalar(),
        "contradictions": db.query(func.count(Contradiction.id)).filter(or_(Contradiction.document_a_id == doc_id, Contradiction.document_b_id == doc_id)).scalar(),
    }
    versions = [{"version": v.version, "sha256": v.sha256, "size_bytes": v.size_bytes, "created_at": v.created_at} for v in d.versions]
    return {**document_out(d, _job(db, doc_id), detail=True), "counts": counts, "versions": versions}


@router.get("/{doc_id}/pages")
def pages(doc_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    document_service.get_document(db, doc_id)
    rows = db.query(Page).filter(Page.document_id == doc_id).order_by(Page.page_number).all()
    return [{"page_number": p.page_number, "width": p.width, "height": p.height, "ocr_used": p.ocr_used, "ocr_confidence": p.ocr_confidence,
             "method": p.extraction_method, "chars": len(p.text or "")} for p in rows]


@router.get("/{doc_id}/pages/{page_number}")
def page_detail(doc_id: int, page_number: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    document_service.get_document(db, doc_id)
    p = db.query(Page).filter(Page.document_id == doc_id, Page.page_number == page_number).first()
    if not p:
        raise NotFoundError(f"Page {page_number} not found")
    els = db.query(DocumentElement).filter(DocumentElement.page_id == p.id).order_by(DocumentElement.order_idx).all()
    elements = []
    for e in els:
        item = {"id": e.id, "type": e.element_type, "text": e.text, "bbox": e.bbox, "section": e.section, "level": e.level, "confidence": e.confidence}
        if e.element_type == "table" and e.data:
            item["table"] = {"headers": e.data.get("headers"), "rows": e.data.get("rows"), "profile": profile_table(e.data),
                             "cells": cell_relationships(e.data, 60)}
        elements.append(item)
    ents = (db.query(Entity.id, Entity.name, Entity.entity_type, func.count(EntityMention.id))
            .join(EntityMention, EntityMention.entity_id == Entity.id)
            .filter(EntityMention.document_id == doc_id, EntityMention.page_number == page_number)
            .group_by(Entity.id, Entity.name, Entity.entity_type).order_by(func.count(EntityMention.id).desc()).limit(80).all())
    ins = db.query(Insight).filter(Insight.document_id == doc_id).all()
    page_ins = [insight_out(i) for i in ins if any(ev.get("page_number") == page_number for ev in (i.evidence or []))]
    return {"page_number": p.page_number, "width": p.width, "height": p.height, "text": p.text, "ocr_used": p.ocr_used, "ocr_confidence": p.ocr_confidence,
            "method": p.extraction_method, "elements": elements, "entities": [{"id": i, "name": n, "type": t, "mentions": c} for i, n, t, c in ents],
            "insights": page_ins}


@router.get("/{doc_id}/pages/{page_number}/image")
def page_image(doc_id: int, page_number: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    data, mime = document_service.page_image(db, doc_id, page_number)
    return Response(content=data, media_type=mime, headers={"Cache-Control": "private, max-age=300"})


@router.get("/{doc_id}/file")
def download(doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    d = document_service.get_document(db, doc_id)
    data = get_storage().read(d.storage_key)
    audit_service.log_event(db, action="document_downloaded", user=user, entity_type="document", entity_id=d.id, document_id=d.id, summary=f"Downloaded {d.safe_name}")
    db.commit()
    return Response(content=data, media_type=d.mime_type, headers={"Content-Disposition": f'attachment; filename="{d.safe_name}"', "X-Content-Type-Options": "nosniff"})


@router.get("/{doc_id}/entities")
def doc_entities(doc_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    document_service.get_document(db, doc_id)
    rows = (db.query(Entity.id, Entity.name, Entity.entity_type, func.count(EntityMention.id), func.min(EntityMention.page_number))
            .join(EntityMention, EntityMention.entity_id == Entity.id).filter(EntityMention.document_id == doc_id)
            .group_by(Entity.id, Entity.name, Entity.entity_type).order_by(func.count(EntityMention.id).desc()).all())
    return [{"id": i, "name": n, "type": t, "mentions": c, "first_page": p} for i, n, t, c, p in rows]


@router.get("/{doc_id}/tables")
def doc_tables(doc_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    document_service.get_document(db, doc_id)
    els = db.query(DocumentElement).filter(DocumentElement.document_id == doc_id, DocumentElement.element_type == "table").order_by(DocumentElement.page_number, DocumentElement.order_idx).all()
    return [{"id": e.id, "page_number": e.page_number, "section": e.section, "bbox": e.bbox, "headers": (e.data or {}).get("headers"), "rows": (e.data or {}).get("rows"),
             "profile": profile_table(e.data or {}), "confidence": e.confidence} for e in els]


@router.get("/{doc_id}/insights")
def doc_insights(doc_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    d = document_service.get_document(db, doc_id)
    rows = db.query(Insight).filter(Insight.document_id == doc_id).order_by(Insight.severity_score.desc(), Insight.id).all()
    cons = db.query(Contradiction).filter(or_(Contradiction.document_a_id == doc_id, Contradiction.document_b_id == doc_id)).all()
    names = {x.id: x.filename for x in db.query(Document).filter(Document.id.in_({c.document_a_id for c in cons} | {c.document_b_id for c in cons} | {doc_id})).all()}
    return {"insights": [insight_out(i, d.filename) for i in rows], "contradictions": [contradiction_out(c, names) for c in cons]}


@router.post("/{doc_id}/reprocess", status_code=202)
def reprocess(doc_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("analyst"))):
    d = document_service.get_document(db, doc_id)
    if d.status in ("QUEUED", "PROCESSING", "INDEXING"):
        raise ValidationFailed("Document is already being processed")
    d.status, d.error = "QUEUED", None
    db.add(ProcessingJob(document_id=d.id, status="QUEUED", stage="queued"))
    audit_service.log_event(db, action="document_reprocess", user=user, entity_type="document", entity_id=d.id, document_id=d.id, summary="Reprocessing requested")
    db.commit()
    return {"queue": enqueue_processing(d.id), "document": document_out(d, _job(db, d.id))}


@router.post("/{doc_id}/versions", status_code=202)
async def new_version(doc_id: int, file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(require_role("analyst"))):
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise FileTooLargeError(f"File exceeds the {get_settings().max_upload_mb} MB limit")
    d = document_service.add_version(db, user, doc_id, file.filename or "", data)
    return {"queue": enqueue_processing(d.id), "document": document_out(d, _job(db, d.id))}


@router.delete("/{doc_id}", status_code=204)
def delete(doc_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("reviewer"))):
    document_service.delete_document(db, user, doc_id)
    return Response(status_code=204)
