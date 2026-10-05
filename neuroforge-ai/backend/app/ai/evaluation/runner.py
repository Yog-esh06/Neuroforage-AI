"""Reproducible evaluation. Ingests data/sample into an ISOLATED temporary database and measures the live pipeline.

    python -m app.ai.evaluation.runner            (from backend/)   or   make eval

Writes data/processed/eval_report.json and prints a summary. Nothing is mocked; scores are whatever the system achieves.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="neuroforge-eval-"))
    os.environ.update({"DATABASE_URL": f"sqlite:///{(tmp / 'eval.db').as_posix()}", "STORAGE_DIR": str(tmp / "docs"), "JOB_BACKEND": "sync",
                       "AUTH_ENABLED": "false", "LOG_LEVEL": "WARNING"})
    from app.ai.evaluation.answer_metrics import evaluate_answers
    from app.ai.evaluation.classification_metrics import evaluate_classification
    from app.ai.evaluation.retrieval_metrics import RetrievedItem, evaluate_retrieval
    from app.main import bootstrap
    from app.db.models.document import Document
    from app.db.models.reasoning import Contradiction
    from app.db.session import SessionLocal
    from app.services import document_service, reasoning_service
    from app.services.search_service import hybrid_search
    from app.ai.extraction.entities import spacy_available
    from app.core.security import _anonymous_admin

    ds = json.loads((REPO / "data" / "eval" / "eval_dataset.json").read_text(encoding="utf-8"))
    sample = REPO / "data" / "sample"
    if not (sample / "invoice_inv2041.pdf").exists():
        import subprocess
        subprocess.run([sys.executable, str(REPO / "backend" / "scripts" / "generate_sample_data.py")], check=True)

    bootstrap()
    db = SessionLocal()
    user = _anonymous_admin(db)
    t0 = time.perf_counter()
    for name in ds["classification"]:
        doc, _ = document_service.create_document(db, user, name, (sample / name).read_bytes())
        document_service.process_document(doc.id)
    ingest_s = time.perf_counter() - t0
    db.expire_all()
    docs = {d.filename: d for d in db.query(Document).all()}

    report: dict = {"environment": {"embedding": "hashing-v1 (default)", "spacy_ner": spacy_available(), "documents": len(docs), "ingest_seconds": round(ingest_s, 1)}}
    report["classification"] = evaluate_classification(ds["classification"], {n: d.doc_type for n, d in docs.items()})

    def search(q: str):
        res = hybrid_search(db, q, k=10, record=False)
        return [RetrievedItem(e.document_name, e.page_number, e.text) for e in res.evidence]

    report["retrieval"] = evaluate_retrieval(ds["retrieval"], search)
    # ablation: how much does each retrieval strategy contribute?
    ablation = {}
    for label, strategies in {"semantic only": ("semantic",), "lexical only": ("lexical",), "graph only": ("graph",), "hybrid (all + rerank)": ("semantic", "lexical", "graph")}.items():
        r = evaluate_retrieval(ds["retrieval"], lambda q, s=strategies: [RetrievedItem(e.document_name, e.page_number, e.text) for e in hybrid_search(db, q, k=10, strategies=s, record=False).evidence])
        ablation[label] = {k: r["summary"][k] for k in ("recall@5", "precision@5", "mrr", "ndcg@5")}
    report["retrieval_ablation"] = ablation
    report["answers"] = evaluate_answers(ds["answers"], lambda q: reasoning_service.ask(db, q, user=user))

    found = {(c.topic, frozenset((db.get(Document, c.document_a_id).filename, db.get(Document, c.document_b_id).filename))) for c in db.query(Contradiction).all()}
    expected = {(c["topic"], frozenset(c["documents"])) for c in ds["contradictions"]}
    tp = len(found & expected)
    report["contradictions"] = {"expected": len(expected), "found_total": len(found), "true_positives": tp, "recall": round(tp / len(expected), 4),
                                "precision": round(tp / len(found), 4) if found else 0.0,
                                "unexpected": sorted((t, sorted(d)) for t, d in found - expected), "missed": sorted((t, sorted(d)) for t, d in expected - found)}

    out = REPO / "data" / "processed" / "eval_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    c, r, a, k = report["classification"], report["retrieval"]["summary"], report["answers"]["summary"], report["contradictions"]
    print(f"\n=== NeuroForge evaluation ({report['environment']['documents']} docs, spaCy NER: {report['environment']['spacy_ner']}) ===")
    print(f"Classification  accuracy {c['accuracy']}  macro P/R/F1 {c['macro'].get('precision')}/{c['macro'].get('recall')}/{c['macro'].get('f1')}")
    for e in c["errors"]:
        print(f"   miss: {e['document']}: expected {e['expected']}, got {e['predicted']}")
    print(f"Retrieval ({report['retrieval']['n_questions']} q)  " + "  ".join(f"{m} {r[m]}" for m in ("recall@1", "recall@5", "recall@10", "precision@5", "mrr", "ndcg@5")))
    for label, m in ablation.items():
        print(f"   {label:24s} " + "  ".join(f"{k_} {v}" for k_, v in m.items()))
    print(f"Answers ({report['answers']['n_cases']} cases)  citation coverage {a['citation_coverage']}  groundedness {a['groundedness']}  answer relevance {a['answer_relevance']}")
    print(f"Contradictions  recall {k['recall']}  precision {k['precision']}  (tp {k['true_positives']}/{k['expected']}, extra {len(k['unexpected'])})")
    print(f"Report written to {out}")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
