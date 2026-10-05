"""Hybrid retrieval orchestration:

    query -> understanding -> [semantic | BM25 | graph] -> metadata filtering -> rerank -> evidence set
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.ai.retrieval.graph import search_graph
from app.ai.retrieval.lexical import search_lexical
from app.ai.retrieval.metadata import MetadataFilter, apply_filter, get_store
from app.ai.retrieval.query import QueryUnderstanding, understand
from app.ai.retrieval.reranker import DEFAULT_WEIGHTS, merge_candidates, rerank
from app.ai.retrieval.semantic import search_semantic
from app.db.models.reasoning import Query, RetrievalRun
from app.db.models.user import User
from app.knowledge.graph import VALUE_TYPES, get_graph
from app.schemas.evidence import Evidence, SourceLocation
from app.services import audit_service
from app.utils.text import canonical_key

ALL_STRATEGIES = ("semantic", "lexical", "graph")


@dataclass
class SearchResult:
    query: str
    understanding: QueryUnderstanding
    evidence: list[Evidence]
    strategies: dict[str, Any]
    linked_entities: list[dict]
    latency_ms: int
    query_id: int | None = None
    run_id: int | None = None
    filters_applied: bool = False
    weights: dict[str, float] = field(default_factory=dict)


def hybrid_search(db: Session, query: str, *, filters: MetadataFilter | None = None, k: int = 10,
                  weights: dict[str, float] | None = None, strategies: tuple[str, ...] = ALL_STRATEGIES,
                  user: User | None = None, record: bool = True, pool: int = 60) -> SearchResult:
    t0 = time.perf_counter()
    store = get_store(db)
    kg = get_graph(db)
    qu = understand(query)
    allowed = apply_filter(store, filters, kg)

    sem = search_semantic(db, query, pool, allowed) if "semantic" in strategies else []
    lex = search_lexical(db, query, pool, allowed) if "lexical" in strategies else []
    gra, seeds = search_graph(db, query, pool, allowed) if "graph" in strategies else ([], [])

    cands = merge_candidates(sem, lex, gra)
    seed_names = {canonical_key(kg.g.nodes[i]["name"]) for i, _ in seeds if i in kg.g}
    chunk_names = {cid: {canonical_key(kg.g.nodes[e]["name"]) for e in kg.chunk_entities.get(cid, ()) if e in kg.g} for cid in cands}
    ranked = rerank(cands, store.records, qu, chunk_names, seed_names, k=k, weights=weights)

    evidence: list[Evidence] = []
    for r in ranked:
        rec = r.record
        ents = [{"name": kg.g.nodes[e]["name"], "type": kg.g.nodes[e]["type"], "id": e}
                for e in sorted(kg.chunk_entities.get(rec.id, ()), key=lambda x: -kg.g.nodes[x]["mentions"] if x in kg.g else 0)
                if e in kg.g and kg.g.nodes[e]["type"] not in VALUE_TYPES][:10]
        evidence.append(Evidence(
            document_id=rec.document_id, document_name=rec.filename, document_type=rec.doc_type, page_number=rec.page,
            section=rec.section, text=rec.text, relevance_score=max(0.0, min(1.0, r.score)),
            retrieval_method="+".join(r.methods), source_location=SourceLocation(chunk_id=rec.id, bbox=rec.bbox, page_end=rec.page_end),
            features=r.features, entities=ents))
    for i, e in enumerate(evidence, start=1):
        e.evidence_id = f"E{i}"

    linked = [{"id": i, "name": kg.g.nodes[i]["name"], "type": kg.g.nodes[i]["type"], "score": round(s, 3)} for i, s in seeds[:10] if i in kg.g]
    weights_used = {**DEFAULT_WEIGHTS, **(weights or {})}
    stats = {"semantic": {"candidates": len(sem), "enabled": "semantic" in strategies},
             "lexical": {"candidates": len(lex), "enabled": "lexical" in strategies},
             "graph": {"candidates": len(gra), "linked_entities": len(seeds), "enabled": "graph" in strategies},
             "pool": len(cands), "indexed_chunks": len(store.records), "filtered_to": None if allowed is None else len(allowed)}
    latency = int((time.perf_counter() - t0) * 1000)
    res = SearchResult(query, qu, evidence, stats, linked, latency, filters_applied=allowed is not None, weights=weights_used)

    if record:
        q = Query(user_id=user.id if user and user.id else None, text=query, filters=(filters.__dict__ if filters else {}),
                  understanding=qu.as_dict())
        db.add(q)
        db.flush()
        run = RetrievalRun(query_id=q.id, strategies={**stats, "weights": weights_used}, latency_ms=latency,
                           results=[{**e.model_dump(exclude={"text"}), "text_preview": e.text[:240]} for e in evidence])
        db.add(run)
        db.flush()
        res.query_id, res.run_id = q.id, run.id
        audit_service.log_event(db, action="search", user=user, entity_type="query", entity_id=q.id, query_text=query,
                                summary=f"Hybrid search returned {len(evidence)} evidence items",
                                details={"strategies": stats, "evidence": [{"evidence_id": e.evidence_id, "document_id": e.document_id,
                                                                            "page": e.page_number, "chunk_id": e.source_location.chunk_id,
                                                                            "score": e.relevance_score, "method": e.retrieval_method} for e in evidence]})
        db.commit()
    return res
