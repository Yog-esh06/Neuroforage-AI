from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import require_role
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.requests import CompareRequest
from app.services import comparison_service

router = APIRouter(prefix="/compare", tags=["comparison"])


@router.post("")
def compare(body: CompareRequest, db: Session = Depends(get_db), user: User = Depends(require_role("analyst"))):
    return comparison_service.compare_documents(db, body.document_ids, user)
