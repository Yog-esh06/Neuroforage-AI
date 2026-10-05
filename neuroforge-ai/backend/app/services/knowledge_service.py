"""Knowledge-graph queries for the explorer: entity lookup, relationships, multi-hop subgraphs, paths, evidence tracing."""
from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationFailed
from app.db.models.document import Chunk, Document
from app.db.models.knowledge import Entity, EntityMention, EntityRelationship
from app.knowledge.graph import VALUE_TYPES, get_graph
from app.knowledge.traversal import find_paths, subgraph
from app.utils.text import truncate


def search_entities(db: Session, q: str, types: list[str] | None, limit: int) -> list[dict[str, Any]]:
    kg = get_graph(db)
    if not q.strip():
        top = sorted((d for _, d in kg.g.nodes(data=True) if not types or d["type"] in types), key=lambda d: -d["mentions"])[:limit]
        return [{**d, "degree": kg.g.degree(d["id"]), "match_score": 1.0} for d in top]
    return kg.search_entities(q, limit=limit, types=set(types) if types else None)


def entity_detail(db: Session, entity_id: int) -> dict[str, Any]:
    kg = get_graph(db)
    node = kg.node(entity_id)
    if node is None:
        raise NotFoundError(f"Entity {entity_id} not found")
    edges = kg.edges_of(entity_id)
    rels = [{"id": e["id"], "relation": e["relation"], "direction": e["direction"], "confidence": e["confidence"],
             "other": {"id": e["other"]["id"], "name": e["other"]["name"], "type": e["other"]["type"]},
             "evidence": truncate(e["evidence"], 500), "document_id": e["document_id"], "document": e["document"], "page": e["page"],
             "chunk_id": e["chunk_id"]} for e in edges]
    mentions = (db.query(EntityMention.document_id, Document.filename, EntityMention.page_number, func.count(EntityMention.id))
                .join(Document, Document.id == EntityMention.document_id).filter(EntityMention.entity_id == entity_id)
                .group_by(EntityMention.document_id, Document.filename, EntityMention.page_number).order_by(EntityMention.document_id, EntityMention.page_number).all())
    docs: dict[int, dict] = {}
    for did, fn, page, n in mentions:
        d = docs.setdefault(did, {"document_id": did, "document": fn, "pages": [], "mentions": 0})
        d["pages"].append(page)
        d["mentions"] += n
    snippets = []
    for m in db.query(EntityMention).filter(EntityMention.entity_id == entity_id, EntityMention.chunk_id.isnot(None)).limit(6).all():
        ch = db.get(Chunk, m.chunk_id)
        if ch:
            snippets.append({"document_id": m.document_id, "page": m.page_number, "chunk_id": ch.id, "surface": m.surface, "method": m.method,
                             "text": truncate(ch.text, 400)})
    return {"entity": node, "relationships": rels, "documents": list(docs.values()), "evidence": snippets}


def graph_view(db: Session, entity_id: int, hops: int, max_nodes: int, relations: list[str] | None, min_confidence: float) -> dict[str, Any]:
    if hops < 1 or hops > 4:
        raise ValidationFailed("hops must be between 1 and 4")
    kg = get_graph(db)
    if entity_id not in kg.g:
        raise NotFoundError(f"Entity {entity_id} not found")
    return subgraph(kg, entity_id, hops=hops, max_nodes=max_nodes, relations=set(relations) if relations else None, min_confidence=min_confidence)


def overview(db: Session, max_nodes: int = 80) -> dict[str, Any]:
    """Whole-graph overview: most connected non-value entities and the edges among them."""
    import networkx as nx

    kg = get_graph(db)
    ranked = sorted((n for n, d in kg.g.nodes(data=True) if d["type"] not in VALUE_TYPES), key=lambda n: -kg.g.degree(n))[:max_nodes]
    idset = set(ranked)
    edges = [{"id": d["id"], "source": u, "target": v, "relation": d["relation"], "confidence": d["confidence"], "evidence": truncate(d["evidence"], 300),
              "document_id": d["document_id"], "document": d["document"], "page": d["page"], "chunk_id": d["chunk_id"]}
             for u, v, d in kg.g.edges(data=True) if u in idset and v in idset and d["relation"] != "co_occurs_with"]
    connected = {e["source"] for e in edges} | {e["target"] for e in edges}  # isolated entities add noise, not insight
    ids = [n for n in ranked if n in connected]
    simple = nx.Graph()
    simple.add_nodes_from(ids)
    simple.add_edges_from((e["source"], e["target"]) for e in edges)
    pos = _component_layout(simple)
    nodes = [{**kg.g.nodes[n], "degree": kg.g.degree(n), "hop": 0, "is_center": False, "x": pos[n][0], "y": pos[n][1]} for n in ids]
    return {"nodes": nodes, "edges": edges}


def _component_layout(g) -> dict[int, tuple[float, float]]:
    """Force-directed layout per connected component (readable node spacing), components packed on a grid, largest first."""
    import math

    import networkx as nx

    comps = sorted(nx.connected_components(g), key=len, reverse=True)
    cols = max(1, math.ceil(math.sqrt(len(comps))))
    cell_w, cell_h = 620.0, 420.0
    out: dict[int, tuple[float, float]] = {}
    for i, comp in enumerate(comps):
        sub = g.subgraph(comp)
        n = len(comp)
        if n == 1:
            local = {next(iter(comp)): (0.0, 0.0)}
        else:
            raw = nx.spring_layout(sub, k=1.6 / math.sqrt(n), iterations=150, seed=7)
            radius = min(cell_w, cell_h) / 2 * min(1.0, 0.35 + 0.12 * n)
            local = {k: (float(v[0]) * radius * 1.35, float(v[1]) * radius) for k, v in raw.items()}
        cx, cy = (i % cols) * cell_w, (i // cols) * cell_h
        for k, (x, y) in local.items():
            out[k] = (cx + x, cy + y)
    return _separate(out)


def _separate(pos: dict[int, tuple[float, float]], box_w: float = 210.0, box_h: float = 70.0, rounds: int = 80) -> dict[int, tuple[float, float]]:
    """Push apart any two nodes whose (box_w x box_h) boxes overlap, along the axis of least overlap."""
    p = {k: [v[0], v[1]] for k, v in pos.items()}
    keys = list(p)
    for _ in range(rounds):
        moved = False
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                dx, dy = p[b][0] - p[a][0], p[b][1] - p[a][1]
                ox, oy = box_w - abs(dx), box_h - abs(dy)
                if ox > 0 and oy > 0:
                    moved = True
                    if ox < oy:
                        s = (ox / 2 + 1) * (1 if dx >= 0 else -1)
                        p[a][0] -= s; p[b][0] += s
                    else:
                        s = (oy / 2 + 1) * (1 if dy >= 0 else -1)
                        p[a][1] -= s; p[b][1] += s
        if not moved:
            break
    return {k: (v[0], v[1]) for k, v in p.items()}


def paths(db: Session, source: int, target: int, max_hops: int) -> list[dict[str, Any]]:
    kg = get_graph(db)
    for i in (source, target):
        if i not in kg.g:
            raise NotFoundError(f"Entity {i} not found")
    return find_paths(kg, source, target, max_hops=max_hops)


def stats(db: Session) -> dict[str, Any]:
    return get_graph(db).stats()
