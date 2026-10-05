"""Workflow actions. Each action performs a real state change and returns a step record for the run log."""
from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.exceptions import ValidationFailed
from app.db.models.document import Document
from app.db.models.reasoning import Contradiction, Insight
from app.db.models.review import ReviewTask
from app.services import audit_service

ACTION_TYPES = {
    "create_review_task": "Create a human review task (params: priority?, task_type?, title?)",
    "flag_document": "Flag the document for attention (params: reason?)",
    "set_insight_status": "Set the insight status (params: status: open|needs_review)",
    "add_audit_note": "Write a note to the audit trail (params: message)",
}
_PRIORITY_BY_SEVERITY = {"critical": "critical", "high": "high", "medium": "medium", "low": "low"}


def validate_actions(actions: list[dict[str, Any]]) -> None:
    if not isinstance(actions, list) or not actions:
        raise ValidationFailed("A workflow needs at least one action")
    for a in actions:
        t = a.get("type")
        if t not in ACTION_TYPES:
            raise ValidationFailed(f"Unknown action '{t}'", details={"allowed": sorted(ACTION_TYPES)})
        p = a.get("params") or {}
        if t == "create_review_task" and p.get("priority") not in (None, "low", "medium", "high", "critical"):
            raise ValidationFailed("priority must be low|medium|high|critical")
        if t == "set_insight_status" and p.get("status") not in ("open", "needs_review"):
            raise ValidationFailed("status must be open|needs_review")
        if t == "add_audit_note" and not str(p.get("message", "")).strip():
            raise ValidationFailed("add_audit_note needs a message")


def _create_review_task(db: Session, ctx: dict, params: dict, run_id: int | None) -> dict:
    ins, con, doc = ctx.get("insight"), ctx.get("contradiction"), ctx.get("document") or {}
    if ins:
        existing = db.query(ReviewTask).filter(ReviewTask.insight_id == ins["id"], ReviewTask.status.in_(("PENDING", "NEEDS_EVIDENCE", "ESCALATED"))).first()
        if existing:
            return {"action": "create_review_task", "status": "skipped", "detail": f"open task #{existing.id} already exists"}
        row = ReviewTask(task_type=params.get("task_type", "risk_review"),
                         priority=params.get("priority") or _PRIORITY_BY_SEVERITY.get(ins.get("severity"), "medium"),
                         title=params.get("title") or ins["title"], ai_recommendation=ins.get("recommended_action", ""),
                         evidence=ins.get("evidence", []), confidence=ins.get("confidence", 0.0), document_id=doc.get("id"),
                         insight_id=ins["id"], workflow_run_id=run_id)
    elif con:
        existing = db.query(ReviewTask).filter(ReviewTask.contradiction_id == con["id"], ReviewTask.status.in_(("PENDING", "NEEDS_EVIDENCE", "ESCALATED"))).first()
        if existing:
            return {"action": "create_review_task", "status": "skipped", "detail": f"open task #{existing.id} already exists"}
        row = ReviewTask(task_type="contradiction_review", priority=params.get("priority") or ("high" if con["confidence"] >= 0.75 else "medium"),
                         title=params.get("title") or f"Conflict: {con['topic']}", ai_recommendation=con.get("explanation", ""),
                         evidence=con.get("evidence", []), confidence=con["confidence"], document_id=doc.get("id"),
                         contradiction_id=con["id"], workflow_run_id=run_id)
    else:
        row = ReviewTask(task_type=params.get("task_type", "classification_review"), priority=params.get("priority") or "medium",
                         title=params.get("title") or f"Review document: {doc.get('name')}",
                         ai_recommendation=params.get("recommendation") or f"Classified as {doc.get('type')} (confidence {doc.get('type_confidence')}). Please verify.",
                         evidence=[], confidence=float(doc.get("type_confidence") or 0.0), document_id=doc.get("id"), workflow_run_id=run_id)
    db.add(row)
    db.flush()
    return {"action": "create_review_task", "status": "done", "review_task_id": row.id, "priority": row.priority}


def _flag_document(db: Session, ctx: dict, params: dict, run_id: int | None) -> dict:
    doc_id = (ctx.get("document") or {}).get("id")
    doc = db.get(Document, doc_id) if doc_id else None
    if not doc:
        return {"action": "flag_document", "status": "skipped", "detail": "no document in context"}
    flags = list((doc.meta or {}).get("flags", []))
    reason = params.get("reason") or "Flagged by workflow"
    if reason not in flags:
        flags.append(reason)
    doc.meta = {**(doc.meta or {}), "flags": flags}
    return {"action": "flag_document", "status": "done", "document_id": doc.id, "reason": reason}


def _set_insight_status(db: Session, ctx: dict, params: dict, run_id: int | None) -> dict:
    ins = ctx.get("insight")
    row = db.get(Insight, ins["id"]) if ins else None
    if not row:
        return {"action": "set_insight_status", "status": "skipped", "detail": "no insight in context"}
    row.status = params.get("status", "needs_review")
    return {"action": "set_insight_status", "status": "done", "insight_id": row.id, "new_status": row.status}


def _add_audit_note(db: Session, ctx: dict, params: dict, run_id: int | None) -> dict:
    doc_id = (ctx.get("document") or {}).get("id")
    audit_service.log_event(db, action="workflow_note", entity_type="workflow_run", entity_id=run_id, document_id=doc_id,
                            summary=str(params.get("message"))[:500], details={"context_keys": sorted(ctx)})
    return {"action": "add_audit_note", "status": "done"}


HANDLERS: dict[str, Callable[[Session, dict, dict, int | None], dict]] = {
    "create_review_task": _create_review_task, "flag_document": _flag_document,
    "set_insight_status": _set_insight_status, "add_audit_note": _add_audit_note,
}
