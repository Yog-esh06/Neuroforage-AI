from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import to_filter
from app.core.exceptions import NotFoundError
from app.core.security import get_current_user, require_role
from app.db.models.reasoning import Answer, Citation, Query as QueryRow
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.requests import AskRequest, SearchRequest
from app.schemas.serializers import answer_out
from app.services import reasoning_service
from app.services.search_service import hybrid_search

router = APIRouter(prefix="/search", tags=["search"])


@router.post("")
def search(body: SearchRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    res = hybrid_search(db, body.query, filters=to_filter(body.filters), k=body.k, weights=body.weights,
                        strategies=tuple(body.strategies), user=user)
    return {"query": res.query, "query_id": res.query_id, "retrieval_run_id": res.run_id, "understanding": res.understanding.as_dict(),
            "strategies": res.strategies, "weights": res.weights, "linked_entities": res.linked_entities, "latency_ms": res.latency_ms,
            "results": [e.model_dump() for e in res.evidence]}


@router.post("/ask")
def ask(body: AskRequest, db: Session = Depends(get_db), user: User = Depends(require_role("analyst"))):
    return reasoning_service.ask(db, body.question, user=user, filters=to_filter(body.filters), k=body.k)


@router.get("/answers/{answer_id}")
def get_answer(answer_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    a = db.get(Answer, answer_id)
    if not a:
        raise NotFoundError(f"Answer {answer_id} not found")
    q = db.get(QueryRow, a.query_id)
    cites = db.query(Citation).filter(Citation.answer_id == a.id).all()
    return {**answer_out(a), "question": q.text if q else None,
            "citations": [{"marker": c.marker, "document_id": c.document_id, "chunk_id": c.chunk_id, "page_number": c.page_number,
                           "section": c.section, "text": c.text, "relevance_score": c.relevance_score, "retrieval_method": c.retrieval_method,
                           "bbox": c.bbox} for c in cites]}


@router.get("/history")
def history(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.query(QueryRow).order_by(QueryRow.id.desc()).limit(limit).all()
    return [{"id": r.id, "text": r.text, "created_at": r.created_at} for r in rows]
