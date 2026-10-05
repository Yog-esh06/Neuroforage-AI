"""ORM -> JSON dict serialisers (explicit field lists: nothing sensitive leaks by accident)."""
from __future__ import annotations

from typing import Any

from app.db.models.audit import AuditLog
from app.db.models.document import Document, ProcessingJob
from app.db.models.reasoning import Answer, Contradiction, Insight
from app.db.models.review import ReviewTask
from app.db.models.user import User
from app.db.models.workflow import Workflow, WorkflowRun


def user_out(u: User) -> dict[str, Any]:
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "is_active": u.is_active}


def document_out(d: Document, job: ProcessingJob | None = None, *, detail: bool = False) -> dict[str, Any]:
    out = {"id": d.id, "filename": d.filename, "file_kind": d.file_kind, "mime_type": d.mime_type, "size_bytes": d.size_bytes, "status": d.status,
           "error": d.error, "document_type": d.doc_type, "classification_confidence": round(d.doc_type_confidence or 0, 3),
           "classification_method": d.classification_method, "page_count": d.page_count, "ocr_used": d.ocr_used,
           "ocr_confidence": d.ocr_confidence, "title": d.title, "version": d.current_version, "created_at": d.created_at,
           "processed_at": d.processed_at, "processing_ms": d.processing_ms, "flags": (d.meta or {}).get("flags", [])}
    if job:
        out["job"] = {"stage": job.stage, "progress": job.progress, "attempts": job.attempts, "error": job.error, "timings_ms": job.stage_timings_ms}
    if detail:
        out["classification_detail"] = d.classification_detail
        out["meta"] = {k: v for k, v in (d.meta or {}).items() if k != "flags"}
        out["sha256"] = d.sha256
    return out


def insight_out(i: Insight, doc_name: str | None = None) -> dict[str, Any]:
    return {"id": i.id, "kind": i.kind, "category": i.category, "title": i.title, "description": i.description, "severity": i.severity,
            "severity_score": i.severity_score, "confidence": i.confidence, "confidence_breakdown": i.confidence_breakdown, "status": i.status,
            "document_id": i.document_id, "document_name": doc_name, "evidence": i.evidence, "entities": i.entities, "reasoning": i.reasoning,
            "recommended_action": i.recommended_action, "method": i.method, "created_at": i.created_at}


def contradiction_out(c: Contradiction, names: dict[int, str] | None = None) -> dict[str, Any]:
    names = names or {}
    return {"id": c.id, "topic": c.topic, "subject": c.subject, "kind": c.kind, "confidence": c.confidence, "status": c.status,
            "resolution_note": c.resolution_note, "created_at": c.created_at,
            "evidence_a": {"document_id": c.document_a_id, "document_name": names.get(c.document_a_id), "page_number": c.page_a, "chunk_id": c.chunk_a_id, "text": c.evidence_a, "value": c.value_a},
            "evidence_b": {"document_id": c.document_b_id, "document_name": names.get(c.document_b_id), "page_number": c.page_b, "chunk_id": c.chunk_b_id, "text": c.evidence_b, "value": c.value_b}}


def task_out(t: ReviewTask, doc_name: str | None = None, reviewer: str | None = None) -> dict[str, Any]:
    return {"id": t.id, "type": t.task_type, "priority": t.priority, "title": t.title, "ai_recommendation": t.ai_recommendation,
            "modified_recommendation": t.modified_recommendation, "evidence": t.evidence, "confidence": t.confidence, "status": t.status,
            "reviewer": reviewer, "document_id": t.document_id, "document_name": doc_name, "insight_id": t.insight_id,
            "contradiction_id": t.contradiction_id, "workflow_run_id": t.workflow_run_id, "decision_note": t.decision_note,
            "created_at": t.created_at, "updated_at": t.updated_at, "decided_at": t.decided_at}


def workflow_out(w: Workflow, runs: int = 0, matched: int = 0) -> dict[str, Any]:
    return {"id": w.id, "name": w.name, "description": w.description, "trigger": w.trigger, "conditions": w.conditions, "actions": w.actions,
            "enabled": w.enabled, "created_at": w.created_at, "run_count": runs, "matched_count": matched}


def run_out(r: WorkflowRun, wf_name: str | None = None) -> dict[str, Any]:
    return {"id": r.id, "workflow_id": r.workflow_id, "workflow_name": wf_name, "trigger": r.trigger, "subject_type": r.subject_type,
            "subject_id": r.subject_id, "matched": r.matched, "status": r.status, "steps": r.steps, "error": r.error, "created_at": r.created_at}


def audit_out(a: AuditLog, *, full: bool = True) -> dict[str, Any]:
    out = {"id": a.id, "timestamp": a.timestamp, "user": a.user_email, "action": a.action, "entity_type": a.entity_type, "entity_id": a.entity_id,
           "document_id": a.document_id, "query_text": a.query_text, "model": a.model, "model_version": a.model_version,
           "prompt_version": a.prompt_version, "confidence": a.confidence, "summary": a.summary, "hash": a.hash, "prev_hash": a.prev_hash}
    if full:
        out["details"] = a.details
    return out


def answer_out(a: Answer) -> dict[str, Any]:
    return {"id": a.id, "query_id": a.query_id, "summary": a.summary, "findings": a.findings, "refused": a.refused, "confidence": a.confidence,
            "confidence_level": a.confidence_level, "confidence_breakdown": a.confidence_breakdown, "provider": a.provider, "model": a.model,
            "model_version": a.model_version, "prompt_version": a.prompt_version, "validation": a.validation, "latency_ms": a.latency_ms,
            "created_at": a.created_at}
