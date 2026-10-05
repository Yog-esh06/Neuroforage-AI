"""Content-based document classification.

Method ("lexicon+structure"): each class has weighted phrase patterns (counted with saturation, boosted when they occur
in the opening of the document where titles live) plus structural cues (tables, money density, clause numbering,
citation markers ...). File names are never used. PDF metadata title/subject contribute as a weak extra signal.

The confidence is an engineering score = 0.55 * margin-share + 0.45 * evidence-strength; it is NOT a calibrated probability.
Documents whose best score is too small are labelled "Unknown".
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from app.ai.extraction import values as V

CLASSES = ["Contract", "Invoice", "Research Paper", "Financial Report", "Technical Documentation", "Policy", "Resume",
           "Legal Document", "General Report", "Unknown"]

# (regex, weight)
LEXICON: dict[str, list[tuple[str, float]]] = {
    "Contract": [
        (r"\bthis (?:services? |master |software |license )?agreement\b", 3), (r"\bhereinafter\b", 2), (r"\bwhereas\b", 2),
        (r"\bgoverning law\b|\bgoverned by the laws\b", 3), (r"\bindemnif\w+", 2.5), (r"\bconfidential(?:ity)?\b", 1),
        (r"\bin witness whereof\b", 3), (r"\beffective date\b", 1.5), (r"\bterminat(?:e|ion)\b", 1.5), (r"\bforce majeure\b", 2.5),
        (r"\bentire agreement\b", 2.5), (r"\blimitation of liability\b|\bliabilit(?:y|ies)\b", 1.5), (r"\bthe parties\b|\beach party\b", 1.5),
        (r"\blicensor\b|\blicensee\b|\bsupplier\b|\bclient\b", 1), (r"\bcounterparts?\b", 1.5), (r"\bshall\b", 0.4),
        (r"\bpayment terms?\b|\bfees?\b", 0.8), (r"\bauto(?:matic(?:ally)?)?[- ]?renew\w*", 2), (r"\bsigned\b|\bsignature\b", 0.8),
        (r"\bscope of (?:work|services)\b", 2), (r"\bamendment\b|\baddendum\b", 1.5),
    ],
    "Invoice": [
        (r"\binvoice\b", 3.5), (r"\binvoice (?:no|number|#|date)\b", 3), (r"\bbill(?:ed)? to\b", 3), (r"\bship(?:ped)? to\b", 1.5),
        (r"\b(?:total|amount|balance) due\b", 3), (r"\bsub-?total\b", 2.5), (r"\b(?:sales )?tax\b|\bgst\b|\bvat\b", 1.2),
        (r"\bdue date\b", 2), (r"\bpayment terms?\b|\bnet ?\d{2}\b", 1.5), (r"\bqty\b|\bquantity\b", 1.5), (r"\bunit price\b|\brate\b", 1.5),
        (r"\bpo (?:number|no)\b|\bpurchase order\b", 1.5), (r"\bremit(?:tance)? to\b|\bpayable to\b", 2), (r"\bdescription\b", 0.5),
    ],
    "Research Paper": [
        (r"\babstract\b", 3), (r"\bintroduction\b", 1), (r"\brelated work\b", 3), (r"\bmethodolog(?:y|ies)\b|\bmethods\b", 1.5),
        (r"\bexperiments?\b|\bexperimental (?:setup|results)\b", 2), (r"\bconclusions?\b", 1), (r"\breferences\b|\bbibliography\b", 2),
        (r"\bet al\.?", 2.5), (r"\bkeywords?\b|\bindex terms\b", 2), (r"\barxiv\b|\bdoi\b|\bproceedings\b|\bjournal\b", 2),
        (r"\bwe (?:propose|present|introduce|show|evaluate|demonstrate)\b", 3), (r"\bdatasets?\b|\bbaselines?\b", 1.5),
        (r"\bablation\b|\bstate[- ]of[- ]the[- ]art\b|\bhypothes[ie]s\b|\bnovel\b", 1.5), (r"\bfig(?:ure|\.)\s*\d", 0.8),
    ],
    "Financial Report": [
        (r"\bbalance sheets?\b", 3), (r"\bincome statements?\b|\bstatements? of (?:operations|income)\b", 3), (r"\bcash flows?\b", 2.5),
        (r"\brevenues?\b", 1.5), (r"\bnet (?:income|loss|profit)\b", 2.5), (r"\bebitda\b", 3), (r"\bfiscal (?:year|quarter)\b|\bfy ?\d{2,4}\b", 2),
        (r"\bearnings per share\b|\beps\b", 3), (r"\bshareholders?\b|\bstockholders?\b|\bdividends?\b", 2), (r"\btotal assets\b|\btotal liabilities\b", 3),
        (r"\bannual report\b|\b10-?k\b|\b10-?q\b|\bquarterly results\b", 3), (r"\bgross (?:margin|profit)\b|\boperating (?:income|margin|expenses?)\b", 2.5),
        (r"\byear[- ]over[- ]year\b|\byoy\b|\bq[1-4]\b", 1.2), (r"\bliquidity\b|\bcapital expenditures?\b|\bguidance\b", 2),
    ],
    "Technical Documentation": [
        (r"\binstallation\b|\binstall\b", 2), (r"\bapi\b", 1.5), (r"\bconfiguration\b|\bconfigure\b", 1.5), (r"\bendpoints?\b", 2.5),
        (r"\bparameters?\b|\barguments?\b", 1.5), (r"\breturns?\b", 0.8), (r"\busage\b|\bexamples?\b", 1), (r"\bprerequisites?\b|\brequirements\b", 2),
        (r"\barchitecture\b", 1.5), (r"\bdeploy(?:ment)?\b", 1.5), (r"\btroubleshooting\b", 3), (r"\bsdk\b|\bcli\b|\bcommand[- ]line\b", 2),
        (r"\brequest\b|\bresponse\b", 1), (r"\bfunctions?\b|\bclass(?:es)?\b|\bmodules?\b", 0.8), (r"\bversion \d+\.\d+", 1.5), (r"\bhttp[s]?://|\bGET\b|\bPOST\b", 1),
        (r"\bdocker\b|\bkubernetes\b|\bgit\b|\bnpm\b|\bpip\b", 1.5),
    ],
    "Policy": [
        (r"\bpolicy\b", 3), (r"\bpurpose\b", 1.5), (r"\bscope\b", 1.5), (r"\bapplies to\b|\bapplicability\b", 2.5),
        (r"\b(?:all )?employees?\b", 1.2), (r"\bmust\b|\bis required to\b|\bare required to\b", 1), (r"\bprocedures?\b", 1.5),
        (r"\bresponsibilit(?:y|ies)\b", 1.5), (r"\bviolations?\b|\bdisciplinary\b|\bnon-?compliance\b", 2.5), (r"\bapproved by\b|\bpolicy owner\b", 2.5),
        (r"\breview date\b|\bnext review\b|\blast reviewed\b", 3), (r"\bstandards?\b|\bguidelines?\b", 1), (r"\bacceptable use\b|\bcode of conduct\b", 3),
        (r"\bexceptions?\b", 0.8),
    ],
    "Resume": [
        (r"\bcurriculum vitae\b|\br[ée]sum[ée]\b", 4), (r"\bwork experience\b|\bprofessional experience\b|\bemployment history\b", 4),
        (r"\beducation\b", 1.5), (r"\bskills?\b", 1.5), (r"\bobjective\b|\bprofessional summary\b", 2), (r"\bcertifications?\b", 1.5),
        (r"\bb\.?(?:tech|sc|a|e)\b|\bm\.?(?:tech|sc|a|s|ba)\b|\bph\.?d\b|\bgpa\b|\bcgpa\b", 2), (r"\blinkedin\.com\b|\bgithub\.com\b", 2.5),
        (r"\b(?:20|19)\d{2}\s*[-–]\s*(?:(?:20|19)\d{2}|present|current)\b", 3), (r"\bresponsible for\b|\bled a team\b|\bdeveloped\b|\bachieved\b", 1),
        (r"\binternship\b|\bprojects?\b", 1),
    ],
    "Legal Document": [
        (r"\bplaintiffs?\b|\bdefendants?\b|\bpetitioners?\b|\brespondents?\b", 3.5), (r"\bcourt\b|\bjudge\b|\bjudgment\b|\bhon'?ble\b", 3),
        (r"\bpursuant to\b", 1.5), (r"\bhereby\b", 1), (r"\bstatutes?\b|\bsection \d+\b|\bact,? \d{4}\b", 1.5), (r"\bjurisdiction\b", 1.5),
        (r"\baffidavit\b|\bsworn\b|\bdeposition\b|\bsubpoena\b", 3.5), (r"\bappeal\b|\bappellant\b|\bcounsel\b|\battorney\b", 2.5),
        (r"\blegal notice\b|\bnotice of\b|\bcease and desist\b", 3), (r"\bv\.\s+[A-Z]|\bvs\.\s+[A-Z]", 3), (r"\bcase no\.?|\bcivil action\b", 3.5),
        (r"\bpower of attorney\b|\bwill and testament\b|\btrust deed\b", 3),
    ],
    "General Report": [
        (r"\bexecutive summary\b", 3), (r"\bfindings?\b", 1.5), (r"\brecommendations?\b", 2), (r"\boverview\b", 1), (r"\banalysis\b", 1),
        (r"\breport\b", 1.5), (r"\bsummary\b", 1), (r"\bbackground\b", 1), (r"\bobjectives?\b", 1), (r"\bkey (?:findings|takeaways|insights)\b", 2.5),
        (r"\bstatus\b|\bprogress\b|\bmilestones?\b", 1), (r"\bconclusions?\b", 0.8),
    ],
}
_COMPILED = {k: [(re.compile(p, re.I), w) for p, w in v] for k, v in LEXICON.items()}
MIN_SCORE = 5.0


@dataclass
class Classification:
    document_type: str
    confidence: float
    method: str
    scores: dict[str, float]
    top_signals: list[str]


def _structural(text: str, n_tables: int, kind: str, n_pages: int) -> dict[str, float]:
    s = {c: 0.0 for c in CLASSES}
    money = len(V.parse_money(text))
    words = max(len(text.split()), 1)
    clauses = len(re.findall(r"(?m)^\s*(?:\d{1,2}(?:\.\d{1,2})*\.?|\([a-z]\))\s+[A-Z]", text))
    shall = len(re.findall(r"\bshall\b", text, re.I))
    cites = len(re.findall(r"\[\d{1,3}\]", text))
    emails = len(re.findall(r"[\w\.-]+@[\w\.-]+\.\w+", text))
    if n_tables and money >= 4 and words < 700:
        s["Invoice"] += 3
    if money / words > 0.01 and n_tables:
        s["Financial Report"] += 1.5
        s["Invoice"] += 1
    if clauses >= 6 and shall >= 6:
        s["Contract"] += 4
    elif clauses >= 4:
        s["Contract"] += 1.5
        s["Policy"] += 1.5
    if cites >= 8:
        s["Research Paper"] += 4
    if re.search(r"(?im)^\s*references\s*$", text) and cites >= 3:
        s["Research Paper"] += 2
    if emails and words < 900 and re.search(r"(?i)experience|education|skills", text):
        s["Resume"] += 2.5
    if n_pages <= 2 and words < 400 and money >= 2:
        s["Invoice"] += 1
    if kind == "spreadsheet":
        s["Financial Report"] += 2
        s["Invoice"] += 1
    if re.search(r"```|\$ [a-z]+ |\bcurl\b|\bpip install\b|\bnpm (?:i|install)\b", text):
        s["Technical Documentation"] += 3
    return s


def classify(text: str, *, n_tables: int = 0, kind: str = "pdf", n_pages: int = 1, meta: dict | None = None,
             title: str | None = None) -> Classification:
    text = text or ""
    sample = text[:60000]
    head = sample[:1500]
    meta_text = " ".join(str(v) for k, v in (meta or {}).items() if k in ("title", "subject", "keywords")) + " " + (title or "")
    scores: dict[str, float] = {c: 0.0 for c in CLASSES}
    signals: dict[str, list[tuple[float, str]]] = {c: [] for c in CLASSES}

    for cls, pats in _COMPILED.items():
        for rx, w in pats:
            body_hits = len(rx.findall(sample))
            if not body_hits and not rx.search(meta_text):
                continue
            head_hits = len(rx.findall(head))
            meta_hit = 1 if rx.search(meta_text) else 0
            contrib = w * (min(body_hits, 4) / 4 * 0.6 + 0.4 * (1 if body_hits else 0)) + 0.8 * w * min(head_hits, 2) / 2 + 0.7 * w * meta_hit
            scores[cls] += contrib
            signals[cls].append((contrib, rx.pattern))
    for cls, extra in _structural(sample, n_tables, kind, n_pages).items():
        scores[cls] += extra
        if extra:
            signals[cls].append((extra, "structure"))

    # General Report is a catch-all: it must not beat a specific class on generic words alone
    scores["General Report"] *= 0.7
    ranked = sorted(((c, v) for c, v in scores.items() if c != "Unknown"), key=lambda x: -x[1])
    (top, s1), (_, s2) = ranked[0], ranked[1]
    if s1 < MIN_SCORE:
        conf = round(min(0.45, 0.2 + s1 / (MIN_SCORE * 4)), 3)
        return Classification("Unknown", conf, "lexicon+structure", {c: round(v, 2) for c, v in ranked[:4]}, [])
    share = s1 / (s1 + s2 + 1e-9)
    strength = 1 - math.exp(-s1 / 14)
    conf = round(min(0.99, 0.55 * share + 0.45 * strength), 3)
    method = "lexicon+structure" + ("+metadata" if meta_text.strip() and any(rx.search(meta_text) for rx, _ in _COMPILED[top]) else "")
    top_signals = [p for _, p in sorted(signals[top], reverse=True)[:5]]
    return Classification(top, conf, method, {c: round(v, 2) for c, v in ranked[:4]}, top_signals)
