"""Executes user-defined decision workflows: trigger -> conditions -> actions, with a full run log."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.db.models.document import Document
from app.db.models.reasoning import Contradiction, Insight
from app.db.models.user import User
from app.db.models.workflow import Workflow, WorkflowRun
from app.services import audit_service
from app.workflows import actions as A
from app.workflows import conditions as C

log = logging.getLogger(__name__)


def document_ctx(doc: Document, db: Session | None = None) -> dict[str, Any]:
    ctx = {"id": doc.id, "name": doc.filename, "type": doc.doc_type, "type_confidence": round(doc.doc_type_confidence or 0, 3),
           "ocr_used": bool(doc.ocr_used), "page_count": doc.page_count}
    if db is not None:
        ins = db.query(Insight.severity_score).filter(Insight.document_id == doc.id, Insight.kind == "risk").all()
        ctx["high_risk_count"] = sum(1 for (s,) in ins if s >= 0.7)
        ctx["max_severity_score"] = max((s for (s,) in ins), default=0.0)
        ctx["contradiction_count"] = db.query(Contradiction).filter((Contradiction.document_a_id == doc.id) | (Contradiction.document_b_id == doc.id)).count()
    return ctx


def insight_ctx(ins: Insight) -> dict[str, Any]:
    return {"id": ins.id, "title": ins.title, "kind": ins.kind, "category": ins.category, "severity": ins.severity,
            "severity_score": ins.severity_score, "confidence": ins.confidence, "evidence": ins.evidence,
            "evidence_count": len(ins.evidence or []), "recommended_action": ins.recommended_action}


def contradiction_ctx(c: Contradiction) -> dict[str, Any]:
    return {"id": c.id, "topic": c.topic, "kind": c.kind, "confidence": c.confidence,
            "explanation": f"{c.topic}: '{c.value_a}' vs '{c.value_b}'",
            "evidence": [{"document_id": c.document_a_id, "page_number": c.page_a, "text": c.evidence_a, "chunk_id": c.chunk_a_id},
                         {"document_id": c.document_b_id, "page_number": c.page_b, "text": c.evidence_b, "chunk_id": c.chunk_b_id}]}


def run_workflow(db: Session, wf: Workflow, trigger: str, ctx: dict[str, Any], subject_type: str, subject_id: int | None,
                 user: User | None = None, *, dedupe: bool = True) -> WorkflowRun | None:
    if dedupe and subject_id is not None:
        prior = db.query(WorkflowRun).filter(WorkflowRun.workflow_id == wf.id, WorkflowRun.subject_type == subject_type,
                                             WorkflowRun.subject_id == subject_id, WorkflowRun.trigger == trigger).first()
        if prior:
            return None
    matched, trace = C.evaluate(wf.conditions, ctx)
    run = WorkflowRun(workflow_id=wf.id, trigger=trigger, subject_type=subject_type, subject_id=subject_id, matched=matched,
                      status="completed" if matched else "skipped", steps=[{"step": "conditions", "matched": matched, "trace": trace}],
                      context={k: v for k, v in ctx.items() if k != "evidence"})
    db.add(run)
    db.flush()
    if matched:
        for act in wf.actions or []:
            try:
                result = A.HANDLERS[act["type"]](db, ctx, act.get("params") or {}, run.id)
            except Exception as e:  # keep running remaining actions; record the failure
                log.exception("workflow action failed")
                result = {"action": act.get("type"), "status": "failed", "error": str(e)[:300]}
                run.status = "failed"
                run.error = str(e)[:300]
            run.steps = [*run.steps, {"step": "action", **result}]
    audit_service.log_event(db, action="workflow_run", user=user, entity_type="workflow_run", entity_id=run.id,
                            document_id=(ctx.get("document") or {}).get("id"),
                            summary=f"Workflow '{wf.name}' {'matched' if matched else 'did not match'} ({trigger})",
                            details={"workflow_id": wf.id, "matched": matched, "steps": run.steps, "subject": [subject_type, subject_id]})
    return run


def fire(db: Session, trigger: str, ctx: dict[str, Any], subject_type: str, subject_id: int | None, user: User | None = None) -> list[WorkflowRun]:
    runs = []
    for wf in db.query(Workflow).filter(Workflow.enabled.is_(True), Workflow.trigger == trigger).all():
        r = run_workflow(db, wf, trigger, ctx, subject_type, subject_id, user)
        if r:
            runs.append(r)
    return runs


def backfill(db: Session, wf: Workflow, user: User | None = None) -> dict[str, int]:
    """Run one workflow over existing subjects of its trigger type (deduplicated). Used by the 'Run now' button."""
    evaluated = matched = 0
    if wf.trigger in ("insight_created", "manual"):
        for ins in db.query(Insight).all():
            doc = db.get(Document, ins.document_id) if ins.document_id else None
            ctx = {"insight": insight_ctx(ins), "document": document_ctx(doc, db) if doc else {}}
            r = run_workflow(db, wf, "insight_created" if wf.trigger == "insight_created" else "manual", ctx, "insight", ins.id, user)
            if r:
                evaluated += 1
                matched += int(r.matched)
    if wf.trigger == "contradiction_detected":
        for c in db.query(Contradiction).all():
            doc = db.get(Document, c.document_a_id)
            ctx = {"contradiction": contradiction_ctx(c), "document": document_ctx(doc, db) if doc else {}}
            r = run_workflow(db, wf, "contradiction_detected", ctx, "contradiction", c.id, user)
            if r:
                evaluated += 1
                matched += int(r.matched)
    if wf.trigger == "document_ready":
        for doc in db.query(Document).filter(Document.status == "READY").all():
            r = run_workflow(db, wf, "document_ready", {"document": document_ctx(doc, db)}, "document", doc.id, user)
            if r:
                evaluated += 1
                matched += int(r.matched)
    return {"evaluated": evaluated, "matched": matched}


DEFAULT_WORKFLOWS: list[dict[str, Any]] = [
    {"name": "High-risk clause review", "trigger": "insight_created",
     "description": "IF risk severity >= 0.7 AND evidence confidence >= 0.5 THEN create a review task.",
     "conditions": {"all": [{"field": "insight.severity_score", "op": ">=", "value": 0.7}, {"field": "insight.confidence", "op": ">=", "value": 0.5}]},
     "actions": [{"type": "create_review_task", "params": {}}]},
    {"name": "Critical finding escalation", "trigger": "insight_created",
     "description": "Critical findings flag the document and mark the insight as needing review.",
     "conditions": {"all": [{"field": "insight.severity", "op": "==", "value": "critical"}]},
     "actions": [{"type": "flag_document", "params": {"reason": "Critical risk detected"}}, {"type": "set_insight_status", "params": {"status": "needs_review"}}]},
    {"name": "Contradiction review", "trigger": "contradiction_detected",
     "description": "Conflicting claims across documents are routed to a human reviewer.",
     "conditions": {"all": [{"field": "contradiction.confidence", "op": ">=", "value": 0.6}]},
     "actions": [{"type": "create_review_task", "params": {}}]},
    {"name": "Low-confidence classification review", "trigger": "document_ready",
     "description": "Documents classified with confidence < 0.5 need a human check.",
     "conditions": {"all": [{"field": "document.type_confidence", "op": "<", "value": 0.5}]},
     "actions": [{"type": "create_review_task", "params": {"task_type": "classification_review", "priority": "low"}}]},
]


def seed_default_workflows(db: Session) -> int:
    n = 0
    for d in DEFAULT_WORKFLOWS:
        if not db.query(Workflow).filter(Workflow.name == d["name"]).first():
            db.add(Workflow(**d, enabled=True))
            n += 1
    if n:
        db.commit()
    return n
