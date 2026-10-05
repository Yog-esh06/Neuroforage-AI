# ADR 0001 — Deterministic extraction before (and independent of) any LLM

**Status:** accepted

## Context
The product promise is that every conclusion is traceable to evidence. Entities, relationships, values, risks and
contradictions are the substrate of that promise. If an LLM produced them, they would inherit its non-determinism, cost,
latency and the possibility of invented facts — and the platform would need an LLM just to ingest a document.

## Decision
Entity, relationship, value, classification, risk and contradiction extraction are implemented with parsers, gazetteers,
typed rule tables and (optionally) spaCy NER. Each output carries the sentence/page it came from. The LLM is used only at
the *reasoning* stage, and even there its output is validated against the supplied evidence.

## Consequences
* Ingestion is reproducible, fast and works offline; the same input always yields the same graph.
* Rule recall is bounded by the rule tables (documented limitation); extending them is a code change, not a prompt change.
* A stronger model can still be plugged in at the reasoning layer without touching ingestion.
