# ADR 0004 — Hash-chained, append-only audit log

**Status:** accepted

## Context
An auditor must be able to reconstruct *how the system reached a conclusion* and trust that the record was not edited.

## Decision
Every significant action writes an `audit_logs` row containing user, timestamp, action, entity, document, query text, model,
model version, prompt version, confidence, summary and a `details` JSON (retrieved evidence, generated result, validation,
human decision). `hash = SHA-256(canonical JSON of the row ‖ prev_hash)`. `verify_chain` recomputes the chain.

## Consequences
* Any in-place edit or deletion of an intermediate row is detectable (tested).
* The write path takes a process-level lock to keep the chain linear; with several API replicas on PostgreSQL the chain
  head must be serialised (advisory lock / `SELECT … FOR UPDATE` on the last row). Single-writer ordering is a documented
  deployment constraint.
* A privileged DB user could recompute the entire chain; periodic anchoring of the head hash in external storage is the
  mitigation (documented in security.md).
