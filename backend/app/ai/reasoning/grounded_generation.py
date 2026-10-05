"""Evidence-grounded generation.

1. Build a request (question + evidence + entities + graph context + system rules) and call the configured provider.
2. Parse the JSON answer (provider failures / invalid JSON fall back to the local extractive composer, recorded in validation).
3. VALIDATE every statement against the evidence it cites:
     - cited ids must exist in the supplied evidence set (fabricated citations are stripped),
     - a statement with no valid citation is dropped,
     - lexical support: share of the statement's content terms found in the cited evidence must clear a threshold,
     - every number/amount/date in the statement must literally occur in the cited evidence.
   Dropped statements are reported under validation.unsupported_claims — never silently shown.
4. Detect contradictions inside the evidence set, compute per-finding and overall confidence.
Citations in the output are always built from the Evidence objects, never from model text.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from app.ai.extraction import values as V
from app.ai.providers.base import GenerationRequest, LLMProvider
from app.ai.providers.extractive import ExtractiveProvider
from app.ai.providers.provider_factory import get_provider
from app.ai.reasoning.confidence import ConfidenceInput, compute_confidence
from app.ai.reasoning.contradiction import TextUnit, detect_conflicts
from app.ai.reasoning.prompts import PROMPT_VERSION, SYSTEM_PROMPT, build_user_prompt
from app.core.exceptions import ProviderError
from app.schemas.evidence import Evidence
from app.utils.text import stem_tokens

log = logging.getLogger(__name__)
FACT_SUPPORT_MIN = 0.55
INFERENCE_SUPPORT_MIN = 0.35
_NUM_TOKEN = re.compile(r"\d[\d,\.]*")
_CITE_MARK = re.compile(r"\[(?:E\d+(?:\s*,\s*E\d+)*)\]")


def _parse_json(text: str) -> dict | None:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.M).strip()
    try:
        obj = json.loads(t)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            try:
                obj = json.loads(m.group(0))
                return obj if isinstance(obj, dict) else None
            except json.JSONDecodeError:
                return None
    return None


def _numbers(text: str) -> set[str]:
    out = set()
    for tok in _NUM_TOKEN.findall(text):
        t = tok.replace(",", "").rstrip(".")
        if t:
            out.add(t)
    return out


def support_score(statement: str, cited_text: str) -> tuple[float, list[str]]:
    """(lexical support share, numeric values missing from the evidence)."""
    stmt = _CITE_MARK.sub("", statement)
    toks = set(stem_tokens(stmt))
    if not toks:
        return 1.0, []
    ev_toks = set(stem_tokens(cited_text))
    share = len(toks & ev_toks) / len(toks)
    ev_nums = _numbers(cited_text)
    missing = [n for n in _numbers(stmt) if n not in ev_nums and len(n) >= 2]
    return share, missing


def corroboration(statement: str, evidence: list[Evidence]) -> tuple[int, int]:
    """(evidence items, distinct documents) containing a sentence that says (almost) the same thing."""
    from app.utils.text import split_sentences

    target = set(stem_tokens(_CITE_MARK.sub("", statement)))
    if not target:
        return 1, 1
    items, docs = 0, set()
    for e in evidence:
        for sent in split_sentences(e.text):
            toks = set(stem_tokens(sent))
            if toks and len(target & toks) / len(target | toks) >= 0.7:
                items += 1
                docs.add(e.document_id)
                break
    return max(items, 1), max(len(docs), 1)


def _graph_lines_and_entities(evidence: list[Evidence]) -> tuple[list[dict], list[str]]:
    ents: dict[str, dict] = {}
    for e in evidence:
        for x in e.entities:
            ents.setdefault(f"{x.get('type')}:{x.get('name')}", x)
    return list(ents.values()), []


def generate_grounded_answer(question: str, evidence: list[Evidence], *, entities: list[dict] | None = None,
                             graph_context: list[str] | None = None, intents: list[str] | None = None,
                             provider: LLMProvider | None = None) -> dict[str, Any]:
    t0 = time.perf_counter()
    for i, e in enumerate(evidence, start=1):
        e.evidence_id = f"E{i}"
    ev_by_id = {e.evidence_id: e for e in evidence}
    prov = provider or get_provider()
    ent_list = entities if entities is not None else _graph_lines_and_entities(evidence)[0]
    req = GenerationRequest(question, evidence, ent_list, graph_context or [], SYSTEM_PROMPT,
                            build_user_prompt(question, evidence, ent_list, graph_context or []), intents or [])
    validation: dict[str, Any] = {"unsupported_claims": [], "stripped_citations": [], "fallback": None}

    result, parsed = None, None
    try:
        result = prov.generate(req)
        parsed = _parse_json(result.text)
        if parsed is None:
            validation["fallback"] = "provider returned invalid JSON"
    except ProviderError as e:
        validation["fallback"] = f"provider error: {e.message}"
    if parsed is None:
        prov = ExtractiveProvider()
        result = prov.generate(req)
        parsed = _parse_json(result.text) or {"refused": True, "refusal_reason": "generation failed", "findings": []}
    assert result is not None

    # ---------------- validation
    findings_out: list[dict] = []
    total_stmts = supported_stmts = 0
    for f in parsed.get("findings", []) or []:
        stmts_out = []
        for st in f.get("statements", []) or []:
            text = str(st.get("text", "")).strip()
            if not text:
                continue
            total_stmts += 1
            raw_ids = [str(i).strip() for i in (st.get("evidence") or [])]
            valid = [i for i in raw_ids if i in ev_by_id]
            bad = [i for i in raw_ids if i not in ev_by_id]
            if bad:
                validation["stripped_citations"].append({"statement": text, "invalid_ids": bad})
            kind = "inference" if st.get("type") == "inference" else "fact"
            if not valid:
                validation["unsupported_claims"].append({"statement": text, "reason": "no valid citation"})
                continue
            cited = " ".join(ev_by_id[i].text for i in valid)
            share, missing = support_score(text, cited)
            if missing:
                validation["unsupported_claims"].append({"statement": text, "reason": f"values not in cited evidence: {missing}"})
                continue
            if share < (FACT_SUPPORT_MIN if kind == "fact" else INFERENCE_SUPPORT_MIN):
                validation["unsupported_claims"].append({"statement": text, "reason": f"low lexical support ({share:.2f})"})
                continue
            supported_stmts += 1
            stmts_out.append({"text": text, "type": kind, "evidence": valid, "support": round(share, 3)})
        if not stmts_out:
            continue
        cited_ids = sorted({i for s in stmts_out for i in s["evidence"]}, key=lambda x: int(x[1:]))
        findings_out.append({
            "title": str(f.get("title", "Finding"))[:200], "severity": f.get("severity", "info") if f.get("severity") in ("critical", "high", "medium", "low", "info") else "info",
            "statements": stmts_out, "entities": [str(x) for x in (f.get("entities") or [])][:12],
            "reasoning": str(f.get("reasoning", ""))[:1200],
            "contradictory_evidence": [i for i in (f.get("contradictory_evidence") or []) if i in ev_by_id],
            "recommended_action": str(f.get("recommended_action", ""))[:600], "evidence_ids": cited_ids,
        })

    refused = bool(parsed.get("refused")) or not findings_out
    refusal_reason = str(parsed.get("refusal_reason", "")) if parsed.get("refused") else ""
    if not findings_out and not parsed.get("refused"):
        refusal_reason = "No claim could be verified against the retrieved evidence."
    # summary: keep only sentences whose content is supported by the evidence set
    summary = ""
    if not refused:
        all_text = " ".join(e.text for e in evidence)
        keep = []
        for sent in re.split(r"(?<=[\.\!\?])\s+(?=\S)", str(parsed.get("summary", ""))):
            share, missing = support_score(sent, all_text)
            if sent.strip() and not missing and share >= FACT_SUPPORT_MIN:
                keep.append(sent.strip())
        summary = " ".join(keep)
        if not summary and findings_out:
            summary = " ".join(s["text"] for s in findings_out[0]["statements"][:2])

    # ---------------- contradictions inside the evidence set
    units = [TextUnit(e.source_location.chunk_id, e.document_id, e.document_name, e.page_number, e.text, e.document_type) for e in evidence]
    conflicts = detect_conflicts(units)
    conflict_dicts = [c.to_dict() for c in conflicts]
    chunk_to_eid = {e.source_location.chunk_id: e.evidence_id for e in evidence}

    def _touches(c, stmts: list[dict]) -> bool:
        """A conflict affects a finding only if one of its statements says (nearly) what a conflicting sentence says."""
        sa, sb = set(stem_tokens(c.evidence_a.sentence)), set(stem_tokens(c.evidence_b.sentence))
        for st in stmts:
            t = set(stem_tokens(st["text"]))
            if t and any(len(t & x) / len(t | x) >= 0.5 for x in (sa, sb) if x):
                return True
        return False

    for c, d in zip(conflicts, conflict_dicts):
        d["evidence_ids"] = [chunk_to_eid.get(c.evidence_a.unit.chunk_id), chunk_to_eid.get(c.evidence_b.unit.chunk_id)]
        for f in findings_out:
            if _touches(c, f["statements"]):
                f["contradictory_evidence"] = sorted(set(f["contradictory_evidence"]) | set(i for i in d["evidence_ids"] if i))

    # ---------------- confidence (per finding + overall)
    groundedness = (supported_stmts / total_stmts) if total_stmts else 0.0
    notes = [str(n) for n in (parsed.get("uncertainty_notes") or [])]
    llm_notes = len([n for n in notes if "extractive composer" not in n])

    def _conf(ids: list[str], stmts: list[dict], g: float) -> dict:
        used = [ev_by_id[i] for i in ids]
        rel_conf = [c.confidence for c in conflicts if _touches(c, stmts)]
        res = compute_confidence(ConfidenceInput(
            relevance_scores=[e.relevance_score for e in used], cited_doc_ids=[e.document_id for e in used],
            source_qualities=[e.features.get("quality", 0.7) for e in used],
            statement_support=[max(len(s["evidence"]), corroboration(s["text"], evidence)[0]) for s in stmts],
            statement_docs=[max(len({ev_by_id[i].document_id for i in s["evidence"]}), corroboration(s["text"], evidence)[1]) for s in stmts],
            groundedness=g, uncertainty_notes=llm_notes, conflict_confidences=rel_conf))
        return res.to_dict()

    for f in findings_out:
        f["confidence"] = _conf(f["evidence_ids"], f["statements"], 1.0)
    used_ids = sorted({i for f in findings_out for i in f["evidence_ids"]}, key=lambda x: int(x[1:]))
    all_stmts = [s for f in findings_out for s in f["statements"]]
    # Conflicts that bear on what the answer actually says are headline items; the rest are still reported, but separately.
    relevant_conflicts = [d for c, d in zip(conflicts, conflict_dicts) if _touches(c, all_stmts)]
    other_conflicts = [d for c, d in zip(conflicts, conflict_dicts) if not _touches(c, all_stmts)]
    overall = _conf(used_ids, all_stmts, groundedness) if findings_out else compute_confidence(ConfidenceInput([], [], [])).to_dict()

    validation.update({"total_statements": total_stmts, "supported_statements": supported_stmts,
                       "citation_coverage": round(groundedness, 3), "provider_is_llm": prov.is_llm})
    citations = []
    for i in used_ids:
        e = ev_by_id[i]
        citations.append({**e.model_dump(), "marker": e.citation})
    return {
        "summary": summary, "refused": refused, "refusal_reason": refusal_reason, "findings": findings_out,
        "citations": citations, "conflicts": relevant_conflicts, "other_conflicts": other_conflicts, "confidence": overall, "validation": validation,
        "uncertainty_notes": notes, "provider": result.provider, "model": result.model, "model_version": result.model_version,
        "prompt_version": PROMPT_VERSION, "latency_ms": int((time.perf_counter() - t0) * 1000),
    }
