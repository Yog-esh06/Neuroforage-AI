"""Request models (validated by FastAPI/Pydantic)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=200)


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=200)
    role: Literal["admin", "reviewer", "analyst", "viewer"] = "analyst"


class FilterModel(BaseModel):
    document_ids: list[int] | None = None
    document_types: list[str] | None = None
    page_min: int | None = Field(default=None, ge=1)
    page_max: int | None = Field(default=None, ge=1)
    content_date_from: str | None = None
    content_date_to: str | None = None
    uploaded_from: str | None = None
    uploaded_to: str | None = None
    entities: list[str] = Field(default_factory=list, max_length=10)
    section_contains: str | None = Field(default=None, max_length=200)
    chunk_types: list[Literal["text", "table"]] | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=2000)
    k: int = Field(default=10, ge=1, le=50)
    filters: FilterModel | None = None
    strategies: list[Literal["semantic", "lexical", "graph"]] = Field(default_factory=lambda: ["semantic", "lexical", "graph"], min_length=1)
    weights: dict[str, float] | None = None

    @field_validator("weights")
    @classmethod
    def _weights(cls, v):
        if v is None:
            return v
        allowed = {"semantic", "lexical", "metadata", "entity", "graph", "recency", "quality"}
        bad = set(v) - allowed
        if bad or any(w < 0 or w > 1 for w in v.values()):
            raise ValueError(f"weights must be within 0..1 and keys in {sorted(allowed)}")
        return v


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    k: int = Field(default=8, ge=1, le=20)
    filters: FilterModel | None = None


class CompareRequest(BaseModel):
    document_ids: list[int] = Field(min_length=2, max_length=5)


class ReviewActionRequest(BaseModel):
    action: Literal["approve", "reject", "modify", "escalate", "request_evidence"]
    note: str | None = Field(default=None, max_length=2000)
    modified_recommendation: str | None = Field(default=None, max_length=4000)


class WorkflowIn(BaseModel):
    name: str = Field(min_length=3, max_length=200)
    description: str = Field(default="", max_length=1000)
    trigger: str
    conditions: dict[str, Any] = Field(default_factory=dict)
    actions: list[dict[str, Any]] = Field(min_length=1)
    enabled: bool = True


class WorkflowPatch(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    trigger: str | None = None
    conditions: dict[str, Any] | None = None
    actions: list[dict[str, Any]] | None = None
    enabled: bool | None = None


class InsightStatusRequest(BaseModel):
    status: Literal["open", "verified", "rejected", "needs_review"]
    note: str | None = Field(default=None, max_length=1000)


class ContradictionStatusRequest(BaseModel):
    status: Literal["open", "resolved", "dismissed"]
    note: str | None = Field(default=None, max_length=2000)
