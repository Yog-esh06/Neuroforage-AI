"""Queries, retrieval runs, answers, citations, contradictions and insights."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class Query(Base):
    __tablename__ = "queries"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    understanding: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RetrievalRun(Base):
    __tablename__ = "retrieval_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    query_id: Mapped[int] = mapped_column(ForeignKey("queries.id", ondelete="CASCADE"), index=True)
    strategies: Mapped[dict] = mapped_column(JSON, default=dict)  # per-strategy candidate counts + weights
    results: Mapped[list] = mapped_column(JSON, default=list)  # ranked evidence incl. feature scores
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Answer(Base):
    __tablename__ = "answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    query_id: Mapped[int] = mapped_column(ForeignKey("queries.id", ondelete="CASCADE"), index=True)
    retrieval_run_id: Mapped[int | None] = mapped_column(ForeignKey("retrieval_runs.id"), nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    findings: Mapped[list] = mapped_column(JSON, default=list)
    refused: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_level: Mapped[str] = mapped_column(String(10), default="LOW")
    confidence_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    provider: Mapped[str] = mapped_column(String(50), default="")
    model: Mapped[str] = mapped_column(String(100), default="")
    model_version: Mapped[str] = mapped_column(String(100), default="")
    prompt_version: Mapped[str] = mapped_column(String(50), default="")
    validation: Mapped[dict] = mapped_column(JSON, default=dict)  # unsupported claims, citation coverage
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Citation(Base):
    __tablename__ = "citations"

    id: Mapped[int] = mapped_column(primary_key=True)
    answer_id: Mapped[int | None] = mapped_column(ForeignKey("answers.id", ondelete="CASCADE"), nullable=True, index=True)
    insight_id: Mapped[int | None] = mapped_column(ForeignKey("insights.id", ondelete="CASCADE"), nullable=True, index=True)
    marker: Mapped[str] = mapped_column(String(20), default="")
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    chunk_id: Mapped[int | None] = mapped_column(ForeignKey("chunks.id", ondelete="SET NULL"), nullable=True)
    page_number: Mapped[int] = mapped_column(Integer, default=1)
    section: Mapped[str | None] = mapped_column(String(500), nullable=True)
    text: Mapped[str] = mapped_column(Text, default="")
    relevance_score: Mapped[float] = mapped_column(Float, default=0.0)
    retrieval_method: Mapped[str] = mapped_column(String(60), default="")
    bbox: Mapped[list | None] = mapped_column(JSON, nullable=True)


class Contradiction(Base):
    __tablename__ = "contradictions"

    id: Mapped[int] = mapped_column(primary_key=True)
    topic: Mapped[str] = mapped_column(String(200), index=True)
    subject: Mapped[str | None] = mapped_column(String(300), nullable=True)
    kind: Mapped[str] = mapped_column(String(30), default="value")  # date|money|duration|number|text
    document_a_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    document_b_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    chunk_a_id: Mapped[int | None] = mapped_column(ForeignKey("chunks.id", ondelete="SET NULL"), nullable=True)
    chunk_b_id: Mapped[int | None] = mapped_column(ForeignKey("chunks.id", ondelete="SET NULL"), nullable=True)
    page_a: Mapped[int] = mapped_column(Integer, default=1)
    page_b: Mapped[int] = mapped_column(Integer, default=1)
    evidence_a: Mapped[str] = mapped_column(Text, default="")
    evidence_b: Mapped[str] = mapped_column(Text, default="")
    value_a: Mapped[str] = mapped_column(String(200), default="")
    value_b: Mapped[str] = mapped_column(String(200), default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | resolved | dismissed
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    query_id: Mapped[int | None] = mapped_column(ForeignKey("queries.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Insight(Base):
    __tablename__ = "insights"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)  # risk | obligation | key_date | financial | compliance
    category: Mapped[str] = mapped_column(String(60), default="")
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(10), default="low", index=True)  # low|medium|high|critical
    severity_score: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|verified|rejected|needs_review
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=True, index=True)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    entities: Mapped[list] = mapped_column(JSON, default=list)
    reasoning: Mapped[str] = mapped_column(Text, default="")
    recommended_action: Mapped[str] = mapped_column(Text, default="")
    method: Mapped[str] = mapped_column(String(60), default="rules")
    model: Mapped[str] = mapped_column(String(100), default="")
    prompt_version: Mapped[str] = mapped_column(String(50), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
