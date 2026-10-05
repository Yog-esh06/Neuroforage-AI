from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    trigger: Mapped[str] = mapped_column(String(40), default="insight_created")  # document_ready|insight_created|contradiction_detected|manual
    conditions: Mapped[dict] = mapped_column(JSON, default=dict)  # {"all":[{"field","op","value"}], "any":[...]}
    actions: Mapped[list] = mapped_column(JSON, default=list)  # [{"type":"create_review_task", "params":{}}]
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), index=True)
    trigger: Mapped[str] = mapped_column(String(40))
    subject_type: Mapped[str] = mapped_column(String(30), default="")
    subject_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    matched: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="completed")  # completed|skipped|failed
    steps: Mapped[list] = mapped_column(JSON, default=list)
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
