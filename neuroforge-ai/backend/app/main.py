"""FastAPI application entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import SessionLocal, get_engine

log = logging.getLogger(__name__)


def bootstrap(create_tables: bool = True) -> None:
    """Create tables (dev/SQLite; production uses `alembic upgrade head`), seed admin + default workflows."""
    import app.db.models  # noqa: F401  (register models)
    from app.db.models.user import User
    from app.workflows.engine import seed_default_workflows

    s = get_settings()
    if create_tables:
        Base.metadata.create_all(get_engine())
    db = SessionLocal()
    try:
        if s.auth_enabled and not db.query(User).filter(User.email == s.seed_admin_email.lower()).first():
            db.add(User(email=s.seed_admin_email.lower(), name=s.seed_admin_name, hashed_password=hash_password(s.seed_admin_password), role="admin"))
            db.commit()
            log.info("Seeded admin user %s", s.seed_admin_email)
        seed_default_workflows(db)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    setup_logging(s.log_level)
    for problem in s.validate_for_production():
        log.error("Configuration problem: %s", problem)
    if s.is_production and s.validate_for_production():
        raise RuntimeError("Refusing to start with insecure production configuration")
    bootstrap(create_tables=not s.is_production)
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="NeuroForge AI", version="1.0.0", lifespan=lifespan,
                  description="Multimodal document intelligence and decision automation. Every conclusion is traceable to evidence.")
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origin_list, allow_credentials=True,
                       allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type"])

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        return resp

    register_exception_handlers(app)
    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()
