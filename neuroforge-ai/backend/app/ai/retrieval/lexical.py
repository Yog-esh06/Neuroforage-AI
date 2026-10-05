"""BM25 lexical retrieval (own implementation: inverted index, supports restriction to an allowed chunk set)."""
from __future__ import annotations

import math
import threading
from collections import Counter, defaultdict

from sqlalchemy.orm import Session

from app.ai.retrieval.metadata import ChunkStore, get_store
from app.utils.text import stem_tokens

K1, B = 1.5, 0.75


class BM25Index:
    def __init__(self):
        self._lock = threading.RLock()
        self._built_for: int | None = None
        self.postings: dict[str, list[tuple[int, int]]] = {}
        self.doc_len: dict[int, int] = {}
        self.avg_len = 0.0
        self.n_docs = 0
        self._stale = True

    def invalidate(self) -> None:
        with self._lock:
            self._stale = True

    def ensure(self, db: Session) -> None:
        store: ChunkStore = get_store(db)
        with self._lock:
            if not self._stale and self._built_for == store.version:
                return
            postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
            doc_len: dict[int, int] = {}
            for cid, rec in store.records.items():
                # section heading is part of the indexed text: headings carry strong topical signal
                toks = stem_tokens(f"{rec.section or ''} {rec.text}")
                doc_len[cid] = len(toks)
                for t, f in Counter(toks).items():
                    postings[t].append((cid, f))
            self.postings, self.doc_len = dict(postings), doc_len
            self.n_docs = len(doc_len)
            self.avg_len = (sum(doc_len.values()) / self.n_docs) if self.n_docs else 0.0
            self._built_for = store.version
            self._stale = False

    def search(self, db: Session, query: str, k: int = 50, allowed: set[int] | None = None) -> list[tuple[int, float]]:
        self.ensure(db)
        q_terms = stem_tokens(query)
        if not q_terms or not self.n_docs:
            return []
        scores: dict[int, float] = defaultdict(float)
        for term in set(q_terms):
            plist = self.postings.get(term)
            if not plist:
                continue
            df = len(plist)
            idf = math.log(1 + (self.n_docs - df + 0.5) / (df + 0.5))
            qtf = q_terms.count(term)
            for cid, tf in plist:
                if allowed is not None and cid not in allowed:
                    continue
                dl = self.doc_len[cid]
                denom = tf + K1 * (1 - B + B * dl / (self.avg_len or 1.0))
                scores[cid] += idf * (tf * (K1 + 1) / denom) * (1 + 0.15 * (qtf - 1))
        ranked = sorted(scores.items(), key=lambda x: -x[1])[:k]
        return [(cid, float(s)) for cid, s in ranked]


_bm25 = BM25Index()


def get_bm25() -> BM25Index:
    return _bm25


def search_lexical(db: Session, query: str, k: int = 50, allowed: set[int] | None = None) -> list[tuple[int, float]]:
    return _bm25.search(db, query, k, allowed)
