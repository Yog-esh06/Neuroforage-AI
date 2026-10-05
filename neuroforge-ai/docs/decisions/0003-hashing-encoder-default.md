# ADR 0003 — Dependency-free hashing encoder as the default embedding backend

**Status:** accepted (with an opt-in neural backend)

## Context
`sentence-transformers` pulls PyTorch (~2 GB), needs a model download, and is slow to start. The project must be runnable
anywhere with `pip install` and no external services, and its tests must be deterministic.

## Decision
Default to `HashingEncoder`: stateless feature hashing of stemmed word uni/bi-grams and character n-grams plus a curated
concept lexicon, L2-normalised. `EMBEDDING_BACKEND=sbert` switches to sentence-transformers; the retrieval pipeline is
identical because both implement `Encoder.encode`. Vectors are tagged with the encoder name so models can be swapped and
re-embedded (`workers/embedding_tasks.reembed_all`).

## Consequences
* Zero-install, reproducible semantic-ish search, adequate for the vocabulary-rich business documents targeted here.
* It does **not** capture paraphrase beyond morphology/concept groups. `docs/evaluation.md` reports the ablation so the
  contribution of each strategy is visible rather than assumed; hybrid retrieval compensates with BM25 and the graph.
* For production quality on free-form prose, enable `sbert` (or an API embedding model) — a configuration change.
