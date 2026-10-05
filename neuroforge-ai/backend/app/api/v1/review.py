from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.security import get_current_user, require_role
from app.db.models.document import Document
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.requests import ReviewActionRequest
from app.schemas.serializers import task_out
from app.services import review_service

router = APIRouter(prefix="/review", tags=["review"])


def _enrich(db: Session, rows):
    docs = {d.id: d.filename for d in db.query(Document.id, Document.filename).filter(Document.id.in_({r.document_id for r in rows if r.document_id})).all()} if rows else {}
    users = {u.id: u.email for u in db.query(User.id, User.email).filter(User.id.in_({r.reviewer_id for r in rows if r.reviewer_id})).all()} if rows else {}
    return [task_out(r, docs.get(r.document_id), users.get(r.reviewer_id)) for r in rows]


@router.get("/tasks")
def tasks(status: str | None = None, priority: str | None = None, type: str | None = None, document_id: int | None = None,
          only_open: bool = False, limit: int = Query(100, ge=1, le=300), offset: int = Query(0, ge=0),
          db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    total, rows = review_service.list_tasks(db, status=status, priority=priority, task_type=type, document_id=document_id,
                                            only_open=only_open, limit=limit, offset=offset)
    return {"total": total, "items": _enrich(db, rows)}


@router.get("/tasks/{task_id}")
def task(task_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    t = review_service.get_task(db, task_id)
    return {**_enrich(db, [t])[0], "history": review_service.task_history(db, task_id)}


@router.post("/tasks/{task_id}/action")
def action(task_id: int, body: ReviewActionRequest, db: Session = Depends(get_db), user: User = Depends(require_role("reviewer"))):
    t = review_service.act(db, task_id, body.action, user, note=body.note, modified_recommendation=body.modified_recommendation)
    return {**_enrich(db, [t])[0], "history": review_service.task_history(db, task_id)}
