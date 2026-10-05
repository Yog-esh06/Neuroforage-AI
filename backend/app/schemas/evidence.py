"""Evidence: the unit of traceability. Every generated statement must reference one of these."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SourceLocation(BaseModel):
    chunk_id: int
    bbox: list[float] | None = None  # [x0,y0,x1,y1] in page coordinates (points), when known
    page_end: int | None = None


class Evidence(BaseModel):
    evidence_id: str = ""  # stable within one answer: "E1", "E2", ...
    document_id: int
    document_name: str
    document_type: str = "Unknown"
    page_number: int
    section: str | None = None
    text: str
    relevance_score: float = Field(ge=0, le=1)
    retrieval_method: str  # e.g. "semantic+lexical+graph"
    source_location: SourceLocation
    features: dict[str, float] = Field(default_factory=dict)  # per-factor reranking scores
    entities: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def citation(self) -> str:
        return f"[{self.document_name} - Page {self.page_number}]"
