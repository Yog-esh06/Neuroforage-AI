"""One place to invalidate every in-memory retrieval structure after data changes."""
from __future__ import annotations

from app.ai.embeddings.index import get_index
from app.ai.retrieval.lexical import get_bm25
from app.ai.retrieval.metadata import invalidate_store
from app.knowledge.graph import invalidate_graph


def invalidate_all() -> None:
    invalidate_store()
    get_bm25().invalidate()
    get_index().invalidate()
    invalidate_graph()
