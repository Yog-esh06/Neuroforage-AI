"""Knowledge-graph retrieval: link query entities, expand through relationships, return connected chunks."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.knowledge.graph import get_graph
from app.knowledge.traversal import neighborhood_chunks


def search_graph(db: Session, query: str, k: int = 50, allowed: set[int] | None = None,
                 hops: int = 2) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Returns (ranked chunk candidates, linked seed entities)."""
    kg = get_graph(db)
    seeds = kg.link_query_entities(query)
    if not seeds:
        return [], []
    scores = neighborhood_chunks(kg, seeds, hops=hops)
    if allowed is not None:
        scores = {c: s for c, s in scores.items() if c in allowed}
    ranked = sorted(scores.items(), key=lambda x: -x[1])[:k]
    return [(c, float(s)) for c, s in ranked], seeds
