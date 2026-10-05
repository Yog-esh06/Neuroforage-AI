"""In-memory knowledge graph (NetworkX MultiDiGraph) materialised from the relational store.

Nodes  = Entity rows            (id, name, type, mention_count, aliases, attributes)
Edges  = EntityRelationship rows (relation, confidence, evidence text, document, page, chunk)

The database remains the source of truth; the graph is rebuilt lazily after any ingestion/deletion
(`invalidate()`), which keeps traversal fast and the implementation simple.
"""
from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any

import networkx as nx
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models.document import Chunk, Document
from app.db.models.knowledge import Entity, EntityMention, EntityRelationship
from app.utils.text import canonical_key, truncate

# Noise-reduction: structural value entities rarely help navigation unless connected
VALUE_TYPES = {"DATE", "MONEY", "METRIC"}


class KnowledgeGraph:
    def __init__(self):
        self.g: nx.MultiDiGraph = nx.MultiDiGraph()
        self._lock = threading.RLock()
        self._stale = True
        self.name_index: dict[str, list[int]] = defaultdict(list)  # canonical name -> entity ids
        self.chunk_entities: dict[int, set[int]] = defaultdict(set)  # chunk id -> entity ids
        self.entity_chunks: dict[int, set[int]] = defaultdict(set)

    # ---------------------------------------------------------------- build
    def invalidate(self) -> None:
        with self._lock:
            self._stale = True

    def ensure(self, db: Session) -> "KnowledgeGraph":
        with self._lock:
            if not self._stale:
                return self
            g = nx.MultiDiGraph()
            name_index: dict[str, list[int]] = defaultdict(list)
            chunk_entities: dict[int, set[int]] = defaultdict(set)
            entity_chunks: dict[int, set[int]] = defaultdict(set)

            doc_names = {d.id: d.filename for d in db.query(Document.id, Document.filename).all()}
            for e in db.query(Entity).all():
                g.add_node(e.id, id=e.id, name=e.name, type=e.entity_type, mentions=e.mention_count,
                           aliases=e.aliases or [], attributes=e.attributes or {})
                name_index[e.canonical_name].append(e.id)
                for a in e.aliases or []:
                    name_index[canonical_key(a)].append(e.id)
            for m in db.query(EntityMention.entity_id, EntityMention.chunk_id).filter(EntityMention.chunk_id.isnot(None)).all():
                chunk_entities[m.chunk_id].add(m.entity_id)
                entity_chunks[m.entity_id].add(m.chunk_id)
            for r in db.query(EntityRelationship).all():
                if r.source_id in g and r.target_id in g:
                    g.add_edge(r.source_id, r.target_id, key=r.id, id=r.id, relation=r.relation, confidence=r.confidence,
                               evidence=r.evidence_text, document_id=r.document_id, document=doc_names.get(r.document_id, "?"),
                               page=r.page_number, chunk_id=r.chunk_id, method=r.method)
            self.g, self.name_index, self.chunk_entities, self.entity_chunks = g, name_index, chunk_entities, entity_chunks
            self._stale = False
            return self

    # ---------------------------------------------------------------- lookup
    def node(self, entity_id: int) -> dict[str, Any] | None:
        return dict(self.g.nodes[entity_id]) if entity_id in self.g else None

    def search_entities(self, query: str, limit: int = 20, types: set[str] | None = None) -> list[dict[str, Any]]:
        q = canonical_key(query)
        if not q:
            return []
        scored = []
        for nid, data in self.g.nodes(data=True):
            if types and data["type"] not in types:
                continue
            names = [canonical_key(data["name"])] + [canonical_key(a) for a in data.get("aliases", [])]
            best = 0.0
            for n in names:
                if not n:
                    continue
                if n == q:
                    best = max(best, 1.0)
                elif n.startswith(q) or q.startswith(n):
                    best = max(best, 0.85)
                elif q in n:
                    best = max(best, 0.7)
                else:
                    qt, nt = set(q.split()), set(n.split())
                    if qt and nt and len(qt & nt) / len(qt | nt) >= 0.5:
                        best = max(best, 0.5 * len(qt & nt) / len(qt | nt) + 0.2)
            if best > 0:
                scored.append((best, data["mentions"], nid))
        scored.sort(key=lambda x: (-x[0], -x[1]))
        return [{**self.g.nodes[nid], "match_score": round(s, 3), "degree": self.g.degree(nid)} for s, _, nid in scored[:limit]]

    def link_query_entities(self, query: str, min_len: int = 3) -> list[tuple[int, float]]:
        """Entity linking for retrieval: entities whose canonical name occurs as a phrase in the query."""
        q = " " + canonical_key(query) + " "
        out: dict[int, float] = {}
        for name, ids in self.name_index.items():
            if len(name) >= min_len and f" {name} " in q:
                for i in ids:
                    out[i] = max(out.get(i, 0.0), min(1.0, 0.6 + 0.4 * len(name.split()) / 3))
        return sorted(out.items(), key=lambda x: -x[1])

    # ---------------------------------------------------------------- edges
    def edges_of(self, entity_id: int) -> list[dict[str, Any]]:
        if entity_id not in self.g:
            return []
        out = []
        for u, v, data in self.g.out_edges(entity_id, data=True):
            out.append({**data, "source": u, "target": v, "direction": "out", "other": self.g.nodes[v]})
        for u, v, data in self.g.in_edges(entity_id, data=True):
            out.append({**data, "source": u, "target": v, "direction": "in", "other": self.g.nodes[u]})
        return sorted(out, key=lambda e: -e["confidence"])

    def stats(self) -> dict[str, Any]:
        types: dict[str, int] = defaultdict(int)
        for _, d in self.g.nodes(data=True):
            types[d["type"]] += 1
        rels: dict[str, int] = defaultdict(int)
        for _, _, d in self.g.edges(data=True):
            rels[d["relation"]] += 1
        return {"entities": self.g.number_of_nodes(), "relationships": self.g.number_of_edges(),
                "by_type": dict(types), "by_relation": dict(rels)}


_graph = KnowledgeGraph()


def get_graph(db: Session) -> KnowledgeGraph:
    return _graph.ensure(db)


def invalidate_graph() -> None:
    _graph.invalidate()
