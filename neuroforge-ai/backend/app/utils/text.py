"""Small, dependency-free text helpers shared by retrieval, extraction and reasoning."""
from __future__ import annotations

import re
import unicodedata

STOPWORDS = frozenset("""
a an and are as at be been being but by can could did do does for from had has have he her his how i if in into is it
its may me might more most my no nor not of on or our over shall she should so some such than that the their them then
there these they this those to too under up us was we were what when where which who whom why will with within without
would you your also any all each other per via upon hereby herein thereof hereto
""".split())

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-\.\$%]*[A-Za-z0-9%]|[A-Za-z0-9]")
_SENT_SPLIT = re.compile(r"(?<=[\.\?\!;])\s+(?=[A-Z0-9\(\"'\[])|\n+")


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("­", "").replace("\x00", "")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # de-hyphenate line wraps
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def tokenize(text: str, *, drop_stop: bool = True) -> list[str]:
    toks = [t.lower() for t in _TOKEN_RE.findall(text or "")]
    if drop_stop:
        toks = [t for t in toks if t not in STOPWORDS and len(t) > 1]
    return toks


def split_sentences(text: str) -> list[str]:
    parts = [s.strip() for s in _SENT_SPLIT.split(text or "")]
    return [s for s in parts if s]


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))


def truncate(text: str, n: int = 300) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def canonical_key(name: str) -> str:
    """Case/punctuation-insensitive key used to merge entity surface forms."""
    s = unicodedata.normalize("NFKC", name).lower()
    s = re.sub(r"[^\w\s&\-]", "", s)  # drop all other punctuation (incl. ? ! ' " . , ; : ( )) so "Acme?" matches "Acme"
    s = re.sub(r"\b(inc|incorporated|llc|ltd|limited|corp|corporation|co|gmbh|plc|pvt|pty|the)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


_SUFFIXES = ("ization", "isation", "ational", "ations", "ation", "ments", "ment", "ities", "ity", "ingly", "ings", "ing",
             "ness", "ious", "ies", "ied", "ive", "ers", "er", "ed", "es", "ly", "s")


def stem(tok: str) -> str:
    """Very light suffix stripper (deterministic, no dependencies). Keeps numbers/currency tokens intact."""
    if len(tok) <= 3 or not tok.isalpha():
        return tok
    base = tok
    for suf in _SUFFIXES:
        if tok.endswith(suf) and len(tok) - len(suf) >= 3:
            base = tok[: -len(suf)]
            if suf in ("ies", "ied"):
                return base + "y"
            break
    if base.endswith("e") and len(base) > 4:  # expire / expires / expired -> expir
        base = base[:-1]
    return base


def stem_tokens(text: str) -> list[str]:
    return [stem(t) for t in tokenize(text)]
