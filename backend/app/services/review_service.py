"""Human-in-the-loop review queue. AI proposes; a human approves, rejects, modifies, escalates or asks for more evidence."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.ai.retrieval.metadata import MetadataFilter
from app.core.exceptions import ConflictError, NotFoundError, ValidationFailed
from app.db.base import utcnow
from app.db.models.reasoning import Contradiction, Insight
from app.db.models.review import ReviewTask
from app.db.models.user import User
from app.services import audit_service
from app.services.search_service import hybrid_search

ACTIONS = {"approve", "reject", "modify", "escalate", "request_evidence"}
OPEN = ("PENDING", "NEEDS_EVIDENCE", "ESCALATED")
_PRIO_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def get_task(db: Session, task_id: int) -> ReviewTask:
    t = db.get(ReviewTask, task_id)
    if not t:
        raise NotFoundError(f"Review task {task_id} not found")
    return t


def list_tasks(db: Session, *, status: str | None = None, priority: str | None = None, task_type: str | None = None,
               document_id: int | None = None, only_open: bool = False, limit: int = 100, offset: int = 0) -> tuple[int, list[ReviewTask]]:
    q = db.query(ReviewTask)
    if status:
        q = q.filter(ReviewTask.status == status.upper())
    if only_open:
        q = q.filter(ReviewTask.status.in_(OPEN))
    if priority:
        q = q.filter(ReviewTask.priority == priority)
    if task_type:
        q = q.filter(ReviewTask.task_type == task_type)
    if document_id:
        q = q.filter(ReviewTask.document_id == document_id)
    total = q.count()
    rows = q.all()
    rows.sort(key=lambda t: (t.status not in OPEN, _PRIO_RANK.get(t.priority, 9), -(t.created_at.timestamp() if t.created_at else 0)))
    return total, rows[offset:offset + limit]


def act(db: Session, task_id: int, action: str, user: User, *, note: str | None = None, modified_recommendation: str | None = None) -> ReviewTask:
    if action not in ACTIONS:
        raise ValidationFailed(f"Unknown action '{action}'", details={"allowed": sorted(ACTIONS)})
    t = get_task(db, task_id)
    if t.status not in OPEN:
        raise ConflictError(f"Task is already {t.status}; decisions are final")
    before = {"status": t.status, "priority": t.priority, "recommendation": t.ai_recommendation}
    detail: dict[str, Any] = {"action": action, "note": note, "before": before}

    if action == "modify":
        if not (modified_recommendation or "").strip():
            raise ValidationFailed("'modify' requires modified_recommendation")
        t.status, t.modified_recommendation = "MODIFIED", modified_recommendation.strip()
    elif action in ("approve", "reject"):
        t.status = "APPROVED" if action == "approve" else "REJECTED"
    elif action == "escalate":
        t.status, t.priority = "ESCALATED", "critical"
    elif action == "request_evidence":
        query = f"{t.title}. {t.ai_recommendation}"[:400]
        have = {(e.get("document_id"), e.get("chunk_id")) for e in (t.evidence or [])}
        flt = MetadataFilter(document_ids=[t.document_id]) if t.document_id and t.task_type != "contradiction_review" else None
        res = hybrid_search(db, query, filters=flt, k=8, user=user, record=False)
        added = []
        for e in res.evidence:
            key = (e.document_id, e.source_location.chunk_id)
            if key in have:
                continue
            added.append({"document_id": e.document_id, "document_name": e.document_name, "page_number": e.page_number, "section": e.section,
                          "chunk_id": e.source_location.chunk_id, "text": e.text, "relevance_score": e.relevance_score,
                          "retrieval_method": e.retrieval_method, "bbox": e.source_location.bbox})
            if len(added) >= 4:
                break
        t.evidence = [*(t.evidence or []), *added]
        t.status = "NEEDS_EVIDENCE"
        detail["evidence_added"] = len(added)

    t.reviewer_id = user.id if user.id else None
    t.decision_note = note or t.decision_note
    t.updated_at = utcnow()
    if t.status in ("APPROVED", "REJECTED", "MODIFIED"):
        t.decided_at = utcnow()
        if t.insight_id and (ins := db.get(Insight, t.insight_id)):
            ins.status = {"APPROVED": "verified", "REJECTED": "rejected", "MODIFIED": "verified"}[t.status]
            if t.status == "MODIFIED":
                ins.recommended_action = t.modified_recommendation or ins.recommended_action
        if t.contradiction_id and (c := db.get(Contradiction, t.contradiction_id)):
            c.status = "resolved" if t.status != "REJECTED" else "dismissed"
            c.resolution_note = note
    detail["after"] = {"status": t.status, "priority": t.priority}
    audit_service.log_event(db, action=f"review_{action}", user=user, entity_type="review_task", entity_id=t.id, document_id=t.document_id,
                            confidence=t.confidence, summary=f"{user.email} → {t.status} on '{t.title}'",
                            details={**detail, "ai_recommendation": t.ai_recommendation, "evidence_count": len(t.evidence or []),
                                     "human_decision": t.status, "modified_recommendation": t.modified_recommendation})
    db.commit()
    return t


def task_history(db: Session, task_id: int) -> list[dict[str, Any]]:
    from app.db.models.audit import AuditLog

    rows = db.query(AuditLog).filter(AuditLog.entity_type == "review_task", AuditLog.entity_id == task_id).order_by(AuditLog.id).all()
    return [{"id": r.id, "timestamp": r.timestamp, "user": r.user_email, "action": r.action, "summary": r.summary, "details": r.details} for r in rows]
