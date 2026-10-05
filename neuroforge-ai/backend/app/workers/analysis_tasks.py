"""Analysis tasks: re-run insight generation + contradiction scan for a document (e.g. after rule changes)."""
from __future__ import annotations

from app.db.models.document import Document
from app.db.session import session_scope
from app.services import insight_service
from app.workers.celery_app import celery_app


def reanalyze_document(document_id: int) -> dict:
    with session_scope() as db:
        doc = db.get(Document, document_id)
        if not doc or doc.status != "READY":
            return {"document_id": document_id, "skipped": True}
        insights = insight_service.analyze_document(db, doc)
        conflicts = insight_service.scan_contradictions(db, doc)
        return {"document_id": document_id, "insights": len(insights), "contradictions": len(conflicts)}


@celery_app.task(name="app.workers.analysis_tasks.reanalyze_document_task")
def reanalyze_document_task(document_id: int) -> dict:
    return reanalyze_document(document_id)
