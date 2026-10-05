"""Combines candidates from every retrieval strategy and produces the final ranked evidence set.

final = sum_i w_i * feature_i  (+ small consensus bonus when several independent strategies retrieved the chunk)

Features (all in [0,1]):
  semantic   cosine similarity, relative to the best candidate and damped by absolute similarity
  lexical    BM25 score relative to the best candidate
  metadata   soft matches: document-type hint, page hint, query keywords found in the section heading
  entity     share of query entities (linked by the graph or found in text) present in the chunk
  graph      proximity of the chunk's entities to query entities in the knowledge graph
  recency    exponential decay on document age (weight is raised only when the query asks for recent info)
  quality    source reliability (native text vs OCR confidence, classification confidence)

The weights are engineering defaults, documented in docs/retrieval.md, and can be overridden per request.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.ai.retrieval.metadata import ChunkRecord
from app.ai.reasoning.risk_rules import scan_sentence
from app.ai.retrieval.query import QueryUnderstanding
from app.utils.text import canonical_key, split_sentences, stem_tokens

DEFAULT_WEIGHTS = {"semantic": 0.30, "lexical": 0.25, "metadata": 0.07, "entity": 0.11, "graph": 0.12, "recency": 0.02, "quality": 0.07}
RECENCY_WEIGHT_WHEN_ASKED = 0.12
CONSENSUS_BONUS = 0.04
HALF_LIFE_DAYS = 365.0


@dataclass
class Candidate:
    chunk_id: int
    sem: float = 0.0
    lex: float = 0.0
    graph: float = 0.0
    methods: set[str] = field(default_factory=set)


@dataclass
class Ranked:
    record: ChunkRecord
    score: float
    features: dict[str, float]
    methods: list[str]


def merge_candidates(semantic: list[tuple[int, float]], lexical: list[tuple[int, float]],
                     graph: list[tuple[int, float]]) -> dict[int, Candidate]:
    cands: dict[int, Candidate] = {}
    for cid, s in semantic:
        c = cands.setdefault(cid, Candidate(cid))
        c.sem = max(c.sem, s)
        c.methods.add("semantic")
    for cid, s in lexical:
        c = cands.setdefault(cid, Candidate(cid))
        c.lex = max(c.lex, s)
        c.methods.add("lexical")
    for cid, s in graph:
        c = cands.setdefault(cid, Candidate(cid))
        c.graph = max(c.graph, s)
        c.methods.add("graph")
    return cands


def _recency(created: datetime | None, newest: datetime | None) -> float:
    if not created or not newest:
        return 0.5
    c = created if created.tzinfo else created.replace(tzinfo=timezone.utc)
    n = newest if newest.tzinfo else newest.replace(tzinfo=timezone.utc)
    age_days = max((n - c).total_seconds() / 86400.0, 0.0)
    return math.exp(-math.log(2) * age_days / HALF_LIFE_DAYS)


def rerank(cands: dict[int, Candidate], records: dict[int, ChunkRecord], qu: QueryUnderstanding,
           chunk_entity_names: dict[int, set[str]], seed_entity_names: set[str], *, k: int = 10,
           weights: dict[str, float] | None = None) -> list[Ranked]:
    if not cands:
        return []
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        w.update({k_: v for k_, v in weights.items() if k_ in w})
    if qu.wants_recency:
        w["recency"] = RECENCY_WEIGHT_WHEN_ASKED
    total_w = sum(w.values()) or 1.0
    w = {k_: v / total_w for k_, v in w.items()}

    max_sem = max((c.sem for c in cands.values()), default=0.0)
    max_lex = max((c.lex for c in cands.values()), default=0.0)
    present = [records[c] for c in cands if c in records]
    newest = max((r.doc_created for r in present if r.doc_created), default=None)
    q_entities = {e["canonical"] for e in qu.entities} | seed_entity_names
    q_keys = set(qu.keywords)

    out: list[Ranked] = []
    for cid, c in cands.items():
        rec = records.get(cid)
        if rec is None:
            continue
        sem_rel = (c.sem / max_sem) if max_sem > 0 else 0.0
        sem = max(0.0, min(1.0, sem_rel * (0.5 + 0.5 * min(1.0, c.sem / 0.35))))  # damp when the best match is itself weak
        lex = (c.lex / max_lex) if max_lex > 0 else 0.0

        meta = 0.0
        if qu.doc_type_hints and rec.doc_type in qu.doc_type_hints:
            meta += 0.5
        if qu.page_hint and qu.page_hint[0] <= rec.page <= qu.page_hint[1]:
            meta += 0.3
        if rec.section and q_keys:
            sec_toks = set(stem_tokens(rec.section))
            meta += 0.5 * (len(sec_toks & q_keys) / max(len(q_keys), 1)) * min(len(q_keys), 3) / 3 + (0.2 if sec_toks & q_keys else 0)
        if "risk" in qu.intents and any(scan_sentence(s) for s in split_sentences(rec.text)):
            meta += 0.6  # question asks about risk and this passage contains a detected risk clause
        meta = min(meta, 1.0)

        ent = 0.0
        if q_entities:
            names = chunk_entity_names.get(cid, set())
            low = rec.text.lower()
            hit = sum(1 for e in q_entities if e in names or (e and e in canonical_key(low)))
            ent = hit / len(q_entities)

        feats = {"semantic": sem, "lexical": lex, "metadata": meta, "entity": ent, "graph": min(c.graph, 1.0),
                 "recency": _recency(rec.doc_created, newest), "quality": rec.quality}
        score = sum(w[k_] * feats[k_] for k_ in w)
        score += CONSENSUS_BONUS * (len(c.methods) - 1)
        out.append(Ranked(rec, round(min(score, 1.0), 4), {k_: round(v, 4) for k_, v in feats.items()}, sorted(c.methods)))

    out.sort(key=lambda r: -r.score)
    return out[:k]
