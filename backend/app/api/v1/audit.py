from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.security import require_role
from app.db.models.audit import AuditLog
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.serializers import audit_out
from app.services import audit_service

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("")
def list_audit(action: str | None = None, document_id: int | None = None, user: str | None = None, entity_type: str | None = None,
               q: str | None = Query(None, max_length=200), limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
               db: Session = Depends(get_db), _: User = Depends(require_role("reviewer"))):
    total, rows = audit_service.list_events(db, action=action, document_id=document_id, user_email=user, entity_type=entity_type, q=q, limit=limit, offset=offset)
    return {"total": total, "items": [audit_out(r, full=False) for r in rows]}


@router.get("/actions")
def actions(db: Session = Depends(get_db), _: User = Depends(require_role("reviewer"))):
    return [a for (a,) in db.query(AuditLog.action).group_by(AuditLog.action).order_by(func.count(AuditLog.id).desc()).all()]


@router.get("/verify")
def verify(db: Session = Depends(get_db), _: User = Depends(require_role("reviewer"))):
    return audit_service.verify_chain(db)


@router.get("/{audit_id}")
def get_audit(audit_id: int, db: Session = Depends(get_db), _: User = Depends(require_role("reviewer"))):
    r = db.get(AuditLog, audit_id)
    if not r:
        raise NotFoundError(f"Audit record {audit_id} not found")
    return audit_out(r)
