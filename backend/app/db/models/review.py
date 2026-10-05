from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow

TASK_STATUSES = ("PENDING", "APPROVED", "REJECTED", "MODIFIED", "ESCALATED", "NEEDS_EVIDENCE")


class ReviewTask(Base):
    __tablename__ = "review_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_type: Mapped[str] = mapped_column(String(40), index=True)  # risk_review | contradiction_review | classification_review
    priority: Mapped[str] = mapped_column(String(10), default="medium", index=True)  # low|medium|high|critical
    title: Mapped[str] = mapped_column(String(300))
    ai_recommendation: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=True, index=True)
    insight_id: Mapped[int | None] = mapped_column(ForeignKey("insights.id", ondelete="SET NULL"), nullable=True)
    contradiction_id: Mapped[int | None] = mapped_column(ForeignKey("contradictions.id", ondelete="SET NULL"), nullable=True)
    workflow_run_id: Mapped[int | None] = mapped_column(ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    modified_recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
