from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.models.user import User
from app.db.session import get_db
from app.services import knowledge_service as ks

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/stats")
def stats(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return ks.stats(db)


@router.get("/overview")
def overview(max_nodes: int = Query(80, ge=5, le=300), db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return ks.overview(db, max_nodes)


@router.get("/entities")
def entities(q: str = Query("", max_length=200), type: list[str] | None = Query(None), limit: int = Query(25, ge=1, le=100),
             db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return ks.search_entities(db, q, type, limit)


@router.get("/entities/{entity_id}")
def entity(entity_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return ks.entity_detail(db, entity_id)


@router.get("/entities/{entity_id}/graph")
def entity_graph(entity_id: int, hops: int = Query(1, ge=1, le=4), max_nodes: int = Query(60, ge=5, le=300),
                 relation: list[str] | None = Query(None), min_confidence: float = Query(0.0, ge=0, le=1),
                 db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return ks.graph_view(db, entity_id, hops, max_nodes, relation, min_confidence)


@router.get("/paths")
def paths(source: int, target: int, max_hops: int = Query(4, ge=1, le=6), db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return ks.paths(db, source, target, max_hops)
