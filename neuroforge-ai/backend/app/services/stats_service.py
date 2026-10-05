"""Dashboard metrics — every number is computed from the database; nothing is hard-coded or simulated."""
from __future__ import annotations

import statistics
from collections import Counter
from datetime import timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.db.models.audit import AuditLog
from app.db.models.document import Chunk, Document, ProcessingJob
from app.db.models.knowledge import Entity, EntityRelationship
from app.db.models.reasoning import Answer, Contradiction, Insight, RetrievalRun
from app.db.models.review import ReviewTask
from app.ai.providers.provider_factory import provider_status
from app.ai.extraction.entities import spacy_available
from app.ingestion.ocr import ocr_status


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return round(s[min(len(s) - 1, int(round((p / 100) * (len(s) - 1))))], 1)


def dashboard(db: Session) -> dict[str, Any]:
    docs_by_status = dict(db.query(Document.status, func.count(Document.id)).group_by(Document.status).all())
    docs_by_type = dict(db.query(Document.doc_type, func.count(Document.id)).filter(Document.status == "READY").group_by(Document.doc_type).all())
    total_docs = sum(docs_by_status.values())
    proc_ms = [m for (m,) in db.query(Document.processing_ms).filter(Document.status == "READY", Document.processing_ms.isnot(None)).all()]

    risk_q = db.query(Insight).filter(Insight.kind == "risk", Insight.status != "rejected")
    high_risk = risk_q.filter(Insight.severity_score >= 0.7).count()
    sev_dist = dict(db.query(Insight.severity, func.count(Insight.id)).filter(Insight.kind == "risk", Insight.status != "rejected").group_by(Insight.severity).all())
    cat_dist = dict(db.query(Insight.category, func.count(Insight.id)).filter(Insight.kind == "risk", Insight.status != "rejected").group_by(Insight.category).all())

    ins_conf = [c for (c,) in db.query(Insight.confidence).filter(Insight.status != "rejected").all()]
    ans_conf = [c for (c,) in db.query(Answer.confidence).filter(Answer.refused.is_(False)).all()]
    all_conf = ins_conf + ans_conf
    hist = Counter(min(int(c * 10), 9) for c in all_conf)

    review_status = dict(db.query(ReviewTask.status, func.count(ReviewTask.id)).group_by(ReviewTask.status).all())
    open_tasks = sum(review_status.get(s, 0) for s in ("PENDING", "NEEDS_EVIDENCE", "ESCALATED"))
    open_by_priority = dict(db.query(ReviewTask.priority, func.count(ReviewTask.id)).filter(ReviewTask.status.in_(("PENDING", "NEEDS_EVIDENCE", "ESCALATED"))).group_by(ReviewTask.priority).all())

    since = utcnow() - timedelta(days=13)
    per_day: Counter[str] = Counter()
    for (ts,) in db.query(Document.created_at).filter(Document.created_at >= since).all():
        per_day[ts.date().isoformat()] += 1
    series = [{"date": (since + timedelta(days=i)).date().isoformat(), "documents": per_day.get(((since + timedelta(days=i)).date().isoformat()), 0)} for i in range(14)]

    stage_ms: dict[str, list[int]] = {}
    for (t,) in db.query(ProcessingJob.stage_timings_ms).filter(ProcessingJob.status == "READY").all():
        for k, v in (t or {}).items():
            stage_ms.setdefault(k, []).append(v)
    search_ms = [m for (m,) in db.query(RetrievalRun.latency_ms).all()]
    answer_ms = [m for (m,) in db.query(Answer.latency_ms).all()]
    recent = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(8).all()

    return {
        "documents": {"total": total_docs, "ready": docs_by_status.get("READY", 0), "by_status": docs_by_status, "by_type": docs_by_type,
                      "processing": sum(docs_by_status.get(s, 0) for s in ("QUEUED", "PROCESSING", "INDEXING")), "failed": docs_by_status.get("FAILED", 0),
                      "chunks": db.query(func.count(Chunk.id)).scalar() or 0, "ocr_documents": db.query(Document).filter(Document.ocr_used.is_(True)).count()},
        "knowledge": {"entities": db.query(func.count(Entity.id)).scalar() or 0, "relationships": db.query(func.count(EntityRelationship.id)).scalar() or 0,
                      "entities_by_type": dict(db.query(Entity.entity_type, func.count(Entity.id)).group_by(Entity.entity_type).all())},
        "review": {"open": open_tasks, "by_status": review_status, "open_by_priority": open_by_priority},
        "risk": {"high_risk_findings": high_risk, "by_severity": sev_dist, "by_category": cat_dist, "total_insights": db.query(func.count(Insight.id)).scalar() or 0},
        "contradictions": {"total": db.query(func.count(Contradiction.id)).scalar() or 0, "open": db.query(Contradiction).filter(Contradiction.status == "open").count()},
        "confidence": {"average": round(statistics.fmean(all_conf), 3) if all_conf else None,
                       "insights_average": round(statistics.fmean(ins_conf), 3) if ins_conf else None,
                       "answers_average": round(statistics.fmean(ans_conf), 3) if ans_conf else None,
                       "samples": len(all_conf), "histogram": [{"bucket": f"{i / 10:.1f}-{(i + 1) / 10:.1f}", "count": hist.get(i, 0)} for i in range(10)]},
        "latency": {"processing_avg_ms": round(statistics.fmean(proc_ms)) if proc_ms else None, "processing_p95_ms": _pct(proc_ms, 95),
                    "search_avg_ms": round(statistics.fmean(search_ms), 1) if search_ms else None,
                    "answer_avg_ms": round(statistics.fmean(answer_ms), 1) if answer_ms else None,
                    "stage_avg_ms": {k: round(statistics.fmean(v)) for k, v in stage_ms.items()}},
        "uploads_per_day": series,
        "recent_activity": [{"id": a.id, "timestamp": a.timestamp, "action": a.action, "user": a.user_email, "summary": a.summary} for a in recent],
        "system": {"llm": provider_status(), "ocr": ocr_status(), "spacy_ner": spacy_available()},
    }
