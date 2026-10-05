# ADR 0002 — Validate generated statements against the cited evidence

**Status:** accepted

## Context
Prompt instructions ("never invent citations") are requests, not guarantees. A provider can still cite ids that do not
exist, attach a real id to an unsupported claim, or alter a number.

## Decision
`grounded_generation.py` treats provider output as untrusted. Each statement must (1) cite ids present in the evidence set,
(2) have ≥ 55 % of its content terms in the cited text, and (3) contain only numbers that occur in the cited text.
Failures are removed and reported; citations returned to the client are rebuilt from the evidence objects. An answer with
no surviving statement is a refusal.

## Consequences
* "Never fabricate citations" holds regardless of the provider, including a misbehaving one (unit tests use a fake provider
  that fabricates ids, values and uncited claims).
* A paraphrase with very low lexical overlap may be dropped (false negative). That is the intended trade-off: precision of
  grounding over fluency. `FACT_SUPPORT_MIN` is the knob.
* Lexical support is a proxy for entailment; adding an NLI model is a documented future step.
