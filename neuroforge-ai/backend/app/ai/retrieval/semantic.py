"""Dense/semantic retrieval over chunk embeddings."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.ai.embeddings.encoder import get_encoder
from app.ai.embeddings.index import get_index


def search_semantic(db: Session, query: str, k: int = 50, allowed: set[int] | None = None) -> list[tuple[int, float]]:
    enc = get_encoder()
    qv = enc.encode([query])[0]
    return get_index().search(db, enc.name, qv, k=k, allowed_chunk_ids=allowed)
