# Evaluation

Code: `backend/app/ai/evaluation/` (`retrieval_metrics.py`, `answer_metrics.py`, `classification_metrics.py`, `runner.py`).
Data: `data/eval/eval_dataset.json`. Reproduce with `make eval` (or `cd backend && python -m app.ai.evaluation.runner`).

The runner boots an **isolated temporary database**, ingests `data/sample/` through the real pipeline (OCR included), runs the
live retrieval / reasoning code and writes `data/processed/eval_report.json`. Nothing is mocked and no score is hard-coded.

## Metric definitions

| Metric | Definition |
|---|---|
| **Recall@K** | share of a question's expected evidence items found in the top-K passages (each expectation counted once) |
| **Precision@K** | share of the top-K passages that satisfy at least one expectation |
| **MRR** | mean reciprocal rank of the first relevant passage |
| **nDCG@K** | rank-sensitive gain with binary relevance |
| *relevant* | passage comes from the expected document **and** contains one of the expectation's key phrases |
| **Citation coverage** | statements with ≥ 1 valid citation / all statements in the answer |
| **Groundedness** | statements whose content terms are ≥ 60 % supported by their cited evidence and whose numbers all occur there / all statements (re-computed independently of the generator) |
| **Answer relevance** | share of the case's expected key facts present in the answer; for must-refuse questions, 1 only if the system refused |
| **Classification P / R / F1** | per class and macro-averaged over classes with support |
| **Contradiction recall / precision** | detected (topic, document-pair) conflicts vs. the labelled set |

## Results (this repository, sample corpus: 10 documents, 18 retrieval questions, 8 answer cases)

Embedding backend `hashing` (default), spaCy `en_core_web_sm` loaded.

### Classification

| | Value |
|---|---|
| Accuracy | **0.90** (9 / 10) |
| Macro precision / recall / F1 | **1.00 / 0.92 / 0.94** |
| Miss | `vendor_costs_fy2026.xlsx`: labelled *Financial Report*, predicted *Unknown* (confidence 0.30) |

The miss is real and instructive: a four-row vendor-cost sheet has too little lexical evidence for any class, so the
classifier abstains instead of guessing — the intended behaviour, scored here as an error.

### Retrieval (top-10 evidence, per question)

| Metric | Hybrid + rerank |
|---|---|
| Recall@1 | 0.61 |
| Recall@5 | **1.00** |
| Recall@10 | **1.00** |
| Precision@5 | 0.27 |
| MRR | 0.84 |
| nDCG@5 | 0.94 |

Strategy ablation (same questions):

| Strategy | Recall@5 | Precision@5 | MRR | nDCG@5 |
|---|---|---|---|---|
| semantic only | 1.00 | 0.27 | 0.79 | 0.89 |
| lexical only (BM25) | 1.00 | 0.36 | 0.85 | 0.94 |
| graph only | 0.14 | 0.08 | 0.09 | 0.10 |
| **hybrid + rerank** | 1.00 | 0.27 | 0.84 | 0.94 |

**Honest reading.** On this small, vocabulary-aligned corpus, BM25 alone is as good as the full hybrid (MRR 0.85 vs 0.84)
and hybrid is clearly better than the semantic-only hashing encoder (MRR 0.79 → 0.84). The graph strategy is intentionally
an *auxiliary* signal: on its own it only answers questions that name entities, and it adds provenance/explainability more
than ranking gain here. Precision@5 is low mostly because most questions have one or two relevant passages while K = 5. A
corpus of 10 short documents cannot separate retrieval strategies convincingly; the numbers demonstrate that the machinery
works and is measurable, not that hybrid beats BM25 in general. Enabling `EMBEDDING_BACKEND=sbert` and a larger corpus is the
way to re-run this ablation meaningfully.

### Generation (extractive provider)

| Metric | Value |
|---|---|
| Citation coverage | 1.00 |
| Groundedness | 1.00 |
| Answer relevance (incl. 2 must-refuse cases) | 1.00 |

**Caveat.** With the default `extractive` provider every statement is a verbatim evidence sentence, so coverage and
groundedness are 1.0 *by construction*; what these numbers verify is that the validation layer and the independent re-check
agree and that the system refuses unanswerable questions (`a07`, `a08`) instead of inventing an answer. They say nothing
about the quality of a remote LLM. To evaluate an LLM provider, set `LLM_PROVIDER`/`LLM_API_KEY` and re-run — the metrics are
computed on the **post-validation** answer and on an independent groundedness check, so unsupported LLM output shows up as
dropped statements and lower coverage.

### Contradiction detection

| | Value |
|---|---|
| Recall | **1.00** (8 / 8 labelled conflicts) |
| Precision | **1.00** (0 unlabelled detections) |

**Label history (disclosure).** The first labelled set contained 5 conflicts. The first run reported precision 0.625: the
three "extra" detections were the late-payment-rate discrepancy between the MSA (2 % per month) and the amendment and both
invoices (1.5 % per month). All three were checked against the source documents and are genuine, so the labels — not the
system — were incomplete, and they were extended (`note` fields in the dataset). Labels were never relaxed to fit a
false positive.

## Test coverage vs. evaluation

`pytest` verifies behaviour (rejection of corrupted input, fabricated citations stripped, tamper detection, authorization …);
this module measures *quality* on labelled data. The two are complementary; neither replaces the other.

## Limitations

* Small synthetic corpus authored alongside the system → optimistic, not a benchmark. Extend `eval_dataset.json` with your own
  documents (labels = document + key phrases) before drawing conclusions.
* Retrieval relevance is phrase-based; a passage that is relevant but phrased differently is counted as a miss.
* No human-rated answer quality; no calibration of the confidence index against outcomes.
