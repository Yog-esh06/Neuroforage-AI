from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ai.embeddings.encoder import get_encoder
from app.core.config import get_settings
from app.core.security import get_current_user
from app.db.models.user import User
from app.db.session import get_db
from app.services import stats_service

router = APIRouter(tags=["system"])


@router.get("/health")
def health(db: Session = Depends(get_db)):
    s = get_settings()
    checks = {"database": "ok"}
    try:
        db.execute(text("SELECT 1"))
    except Exception as e:  # pragma: no cover
        checks["database"] = f"error: {type(e).__name__}"
    if s.job_backend == "celery" and not s.redis_url.startswith("filesystem://"):
        try:
            import redis

            redis.Redis.from_url(s.redis_url, socket_connect_timeout=1).ping()
            checks["redis"] = "ok"
        except Exception as e:
            checks["redis"] = f"error: {type(e).__name__}"
    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": status, "checks": checks, "job_backend": s.job_backend, "embedding_model": get_encoder().name}


@router.get("/stats/dashboard")
def dashboard(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return stats_service.dashboard(db)
