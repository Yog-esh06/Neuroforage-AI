"""Shared API dependencies and helpers."""
from __future__ import annotations

from app.ai.retrieval.metadata import MetadataFilter
from app.schemas.requests import FilterModel


def to_filter(f: FilterModel | None) -> MetadataFilter | None:
    if f is None:
        return None
    return MetadataFilter(**f.model_dump())
