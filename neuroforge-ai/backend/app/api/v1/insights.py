from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.security import get_current_user, require_role
from app.db.models.document import Document
from app.db.models.reasoning import Contradiction, Insight
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.requests import ContradictionStatusRequest, InsightStatusRequest
from app.schemas.serializers import contradiction_out, insight_out
from app.services import audit_service, document_service, insight_service

router = APIRouter(prefix="/insights", tags=["insights"])


def _names(db: Session, ids: set[int]) -> dict[int, str]:
    return {d.id: d.filename for d in db.query(Document.id, Document.filename).filter(Document.id.in_(ids)).all()} if ids else {}


@router.get("")
def list_insights(kind: str | None = None, severity: str | None = None, category: str | None = None, status: str | None = None,
                  document_id: int | None = None, min_confidence: float = Query(0.0, ge=0, le=1),
                  limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
                  db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    q = db.query(Insight).filter(Insight.confidence >= min_confidence)
    for col, val in ((Insight.kind, kind), (Insight.severity, severity), (Insight.category, category), (Insight.status, status), (Insight.document_id, document_id)):
        if val is not None:
            q = q.filter(col == val)
    total = q.count()
    rows = q.order_by(Insight.severity_score.desc(), Insight.confidence.desc(), Insight.id).offset(offset).limit(limit).all()
    names = _names(db, {r.document_id for r in rows if r.document_id})
    return {"total": total, "items": [insight_out(r, names.get(r.document_id)) for r in rows]}


@router.get("/contradictions")
def list_contradictions(status: str | None = None, document_id: int | None = None, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    q = db.query(Contradiction)
    if status:
        q = q.filter(Contradiction.status == status)
    if document_id:
        q = q.filter((Contradiction.document_a_id == document_id) | (Contradiction.document_b_id == document_id))
    rows = q.order_by(Contradiction.confidence.desc()).all()
    names = _names(db, {r.document_a_id for r in rows} | {r.document_b_id for r in rows})
    return {"total": len(rows), "items": [contradiction_out(r, names) for r in rows]}


@router.patch("/contradictions/{cid}")
def set_contradiction(cid: int, body: ContradictionStatusRequest, db: Session = Depends(get_db), user: User = Depends(require_role("reviewer"))):
    c = db.get(Contradiction, cid)
    if not c:
        raise NotFoundError(f"Contradiction {cid} not found")
    old = c.status
    c.status, c.resolution_note = body.status, body.note
    audit_service.log_event(db, action="contradiction_status", user=user, entity_type="contradiction", entity_id=c.id, document_id=c.document_a_id,
                            summary=f"Contradiction '{c.topic}' {old} → {body.status}", details={"note": body.note, "human_decision": body.status})
    db.commit()
    return contradiction_out(c, _names(db, {c.document_a_id, c.document_b_id}))


@router.get("/{insight_id}")
def get_insight(insight_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    i = db.get(Insight, insight_id)
    if not i:
        raise NotFoundError(f"Insight {insight_id} not found")
    return insight_out(i, _names(db, {i.document_id}).get(i.document_id))


@router.patch("/{insight_id}/status")
def set_status(insight_id: int, body: InsightStatusRequest, db: Session = Depends(get_db), user: User = Depends(require_role("reviewer"))):
    i = db.get(Insight, insight_id)
    if not i:
        raise NotFoundError(f"Insight {insight_id} not found")
    old = i.status
    i.status = body.status
    audit_service.log_event(db, action="insight_status", user=user, entity_type="insight", entity_id=i.id, document_id=i.document_id, confidence=i.confidence,
                            summary=f"Insight '{i.title}' {old} → {body.status}", details={"note": body.note, "human_decision": body.status})
    db.commit()
    return insight_out(i)


@router.post("/analyze/{doc_id}")
def reanalyze(doc_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("analyst"))):
    doc = document_service.get_document(db, doc_id)
    ins = insight_service.analyze_document(db, doc, user)
    con = insight_service.scan_contradictions(db, doc, user)
    db.commit()
    return {"insights": len(ins), "contradictions": len(con)}
