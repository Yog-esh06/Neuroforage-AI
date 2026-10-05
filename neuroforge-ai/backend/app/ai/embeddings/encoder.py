"""Embedding encoders behind one interface.

* `hashing`  (default): dependency-free, deterministic. Feature-hashed word uni/bi-grams + character n-grams +
  a small domain concept lexicon (so "terminate" / "expire" / "end" and "fee" / "payment" / "price" share features).
  It is a lexical-semantic-lite encoder, NOT a neural model: it generalises across morphology, spelling and the
  curated concept groups only. Use `sbert` for true dense semantics.
* `sbert`: sentence-transformers (install the `sbert` extra). Falls back to `hashing` if unavailable.
"""
from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from functools import lru_cache

import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer

from app.core.config import get_settings
from app.utils.text import stem, tokenize

log = logging.getLogger(__name__)

CONCEPTS: dict[str, list[str]] = {
    "c_end": ["terminate", "termination", "expire", "expiry", "expiration", "end", "cease", "conclude", "lapse", "cancel", "cancellation"],
    "c_start": ["effective", "commence", "begin", "start", "initiate", "inception"],
    "c_pay": ["pay", "payment", "fee", "price", "cost", "charge", "amount", "remit", "invoice", "billing", "compensation", "consideration", "payable"],
    "c_risk": ["risk", "liability", "exposure", "penalty", "damages", "breach", "default", "hazard", "threat", "vulnerability", "fine", "sanction"],
    "c_obl": ["obligation", "duty", "shall", "must", "require", "responsible", "undertake", "covenant", "commit"],
    "c_conf": ["confidential", "secret", "proprietary", "nda", "disclosure", "nondisclosure"],
    "c_law": ["law", "legal", "statute", "regulation", "compliance", "regulatory", "jurisdiction", "court", "governing"],
    "c_renew": ["renew", "renewal", "extend", "extension", "evergreen", "autorenew"],
    "c_income": ["revenue", "income", "profit", "earnings", "sales", "turnover", "ebitda", "margin"],
    "c_cost": ["expense", "expenditure", "cost", "spending", "outlay", "opex", "capex"],
    "c_person": ["employee", "staff", "personnel", "worker", "contractor", "consultant", "team"],
    "c_data": ["data", "information", "record", "dataset", "database", "personal", "privacy"],
    "c_sec": ["security", "encryption", "breach", "incident", "vulnerability", "attack", "unauthorized", "access"],
    "c_ai": ["model", "algorithm", "neural", "learning", "training", "classifier", "embedding", "inference"],
    "c_time": ["deadline", "due", "schedule", "timeline", "date", "term", "period", "duration"],
    "c_ownership": ["own", "ownership", "title", "intellectual", "ip", "license", "licence", "rights"],
    "c_dispute": ["dispute", "arbitration", "litigation", "claim", "lawsuit", "mediation", "remedy"],
    "c_increase": ["increase", "grow", "rise", "growth", "expand", "gain", "improve"],
    "c_decrease": ["decrease", "decline", "drop", "fall", "reduce", "loss", "shrink", "decline"],
}
_CONCEPT_OF: dict[str, str] = {}
for _c, _ws in CONCEPTS.items():
    for _w in _ws:
        _CONCEPT_OF[stem(_w)] = _c
        _CONCEPT_OF[_w] = _c


class Encoder(ABC):
    name: str
    dim: int

    @abstractmethod
    def encode(self, texts: list[str]) -> np.ndarray:
        """Return float32 array (n, dim), L2-normalised rows."""


def _word_analyzer(text: str) -> list[str]:
    toks = [stem(t) for t in tokenize(text)]
    feats = list(toks)
    feats += [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
    feats += [_CONCEPT_OF[t] for t in toks if t in _CONCEPT_OF] * 2  # concept features weighted x2
    return feats


class HashingEncoder(Encoder):
    def __init__(self, dim: int = 1024):
        self.dim = dim
        self.name = f"hashing-v1-{dim}"
        self._word = HashingVectorizer(n_features=dim, analyzer=_word_analyzer, alternate_sign=True, norm=None)
        self._char = HashingVectorizer(n_features=dim, analyzer="char_wb", ngram_range=(4, 5), alternate_sign=True, norm=None, lowercase=True)

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        w = self._word.transform(texts)
        c = self._char.transform(texts)
        # sublinear tf scaling, then combine: words dominate, char n-grams add typo/morphology robustness
        w.data = np.sign(w.data) * np.log1p(np.abs(w.data))
        c.data = np.sign(c.data) * np.log1p(np.abs(c.data))
        m = (w * 1.0 + c * 0.35).toarray().astype(np.float32)
        norms = np.linalg.norm(m, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return m / norms


class SBertEncoder(Encoder):
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)
        self.dim = int(self._model.get_sentence_embedding_dimension())
        self.name = f"sbert:{model_name}"
        self._lock = threading.Lock()

    def encode(self, texts: list[str]) -> np.ndarray:
        with self._lock:
            v = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False, batch_size=32)
        return np.asarray(v, dtype=np.float32)


@lru_cache
def get_encoder() -> Encoder:
    s = get_settings()
    if s.embedding_backend == "sbert":
        try:
            enc = SBertEncoder(s.embedding_model)
            log.info("Embedding backend: %s (dim=%d)", enc.name, enc.dim)
            return enc
        except Exception as e:
            log.warning("sentence-transformers unavailable (%s); falling back to hashing encoder", e)
    enc = HashingEncoder(s.embedding_dim)
    log.info("Embedding backend: %s", enc.name)
    return enc
