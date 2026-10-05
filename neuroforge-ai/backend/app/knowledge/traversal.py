"""Graph traversal: multi-hop expansion, path finding with evidence, and visualisation subgraphs."""
from __future__ import annotations

from collections import deque
from typing import Any

import networkx as nx

from app.knowledge.graph import KnowledgeGraph, VALUE_TYPES
from app.utils.text import truncate


def _edge_view(u: int, v: int, d: dict[str, Any]) -> dict[str, Any]:
    return {"id": d["id"], "source": u, "target": v, "relation": d["relation"], "confidence": d["confidence"],
            "evidence": truncate(d.get("evidence", ""), 400), "document_id": d["document_id"], "document": d.get("document"),
            "page": d["page"], "chunk_id": d.get("chunk_id")}


def expand(kg: KnowledgeGraph, seeds: list[int], hops: int = 2, max_nodes: int = 120,
           relations: set[str] | None = None, include_values: bool = True) -> dict[int, dict[str, Any]]:
    """Breadth-first expansion ignoring edge direction. Returns {entity_id: {"hop": n, "via": edge_id|None}}."""
    seen: dict[int, dict[str, Any]] = {s: {"hop": 0, "via": None} for s in seeds if s in kg.g}
    q = deque(seen.keys())
    while q and len(seen) < max_nodes:
        cur = q.popleft()
        hop = seen[cur]["hop"]
        if hop >= hops:
            continue
        for u, v, d in list(kg.g.out_edges(cur, data=True)) + list(kg.g.in_edges(cur, data=True)):
            other = v if u == cur else u
            if other in seen:
                continue
            if relations and d["relation"] not in relations:
                continue
            if not include_values and kg.g.nodes[other]["type"] in VALUE_TYPES:
                continue
            seen[other] = {"hop": hop + 1, "via": d["id"]}
            q.append(other)
            if len(seen) >= max_nodes:
                break
    return seen


def subgraph(kg: KnowledgeGraph, center: int, hops: int = 1, max_nodes: int = 60,
             relations: set[str] | None = None, min_confidence: float = 0.0) -> dict[str, Any]:
    """Nodes/edges payload for the explorer (React Flow). Highest-degree neighbours are kept when truncating."""
    if center not in kg.g:
        return {"nodes": [], "edges": []}
    reach = expand(kg, [center], hops=hops, max_nodes=10_000, relations=relations)
    ids = sorted(reach, key=lambda n: (reach[n]["hop"], -kg.g.degree(n)))[:max_nodes]
    idset = set(ids)
    nodes = [{**kg.g.nodes[n], "hop": reach[n]["hop"], "degree": kg.g.degree(n), "is_center": n == center} for n in ids]
    edges = []
    for u, v, d in kg.g.edges(data=True):
        if u in idset and v in idset and d["confidence"] >= min_confidence and (not relations or d["relation"] in relations):
            edges.append(_edge_view(u, v, d))
    return {"nodes": nodes, "edges": edges}


def find_paths(kg: KnowledgeGraph, source: int, target: int, max_hops: int = 4, limit: int = 5) -> list[dict[str, Any]]:
    """Simple paths (undirected view) up to `max_hops` edges, shortest first, each step carrying its evidence."""
    if source not in kg.g or target not in kg.g:
        return []
    und = nx.Graph(kg.g)  # simple undirected view (parallel edges collapsed); edge evidence is looked up on the multigraph
    paths = []
    try:
        for p in nx.shortest_simple_paths(und, source, target):
            if len(p) - 1 > max_hops:
                break
            steps = []
            for a, b in zip(p, p[1:]):
                best = None
                for u, v in ((a, b), (b, a)):
                    if kg.g.has_edge(u, v):
                        for key, d in kg.g[u][v].items():
                            if best is None or d["confidence"] > best[2]["confidence"]:
                                best = (u, v, d)
                if best:
                    steps.append(_edge_view(best[0], best[1], best[2]))
            paths.append({"nodes": [kg.node(n) for n in p], "hops": len(p) - 1, "steps": steps})
            if len(paths) >= limit:
                break
    except nx.NetworkXNoPath:
        return []
    return paths


def neighborhood_chunks(kg: KnowledgeGraph, seeds: list[tuple[int, float]], hops: int = 2) -> dict[int, float]:
    """Chunk relevance from graph proximity: weight(entity) = seed_score * 0.55^hop; chunk score = max over its entities,
    boosted when a relationship's own evidence chunk connects two reached entities."""
    scores: dict[int, float] = {}
    for seed, w in seeds:
        reach = expand(kg, [seed], hops=hops, max_nodes=80)
        for eid, info in reach.items():
            ew = w * (0.55 ** info["hop"])
            for ch in kg.entity_chunks.get(eid, ()):
                scores[ch] = max(scores.get(ch, 0.0), ew)
        for u, v, d in kg.g.edges(data=True):
            if d.get("chunk_id") and (u in reach and v in reach):
                ew = w * (0.55 ** max(reach[u]["hop"], reach[v]["hop"])) * 1.15
                scores[d["chunk_id"]] = max(scores.get(d["chunk_id"], 0.0), min(ew, 1.0))
    return scores
