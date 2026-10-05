"""Deterministic risk detectors shared by insight generation and the extractive answer composer.

Each rule matches a sentence; severity can be modulated by parsed values (amounts, rates, notice periods).
Confidence here is a rule-precision prior (engineering estimate), later combined with evidence quality.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.ai.extraction import values as V

SEVERITY_SCORE = {"low": 0.25, "medium": 0.5, "high": 0.75, "critical": 0.95}


def severity_from_score(score: float) -> str:
    return "critical" if score >= 0.9 else "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"


@dataclass(frozen=True)
class RiskRule:
    id: str
    category: str  # legal | financial | compliance | operational | security
    title: str
    pattern: re.Pattern
    severity: str
    precision: float
    action: str
    reasoning: str


def _rule(id_, cat, title, pat, sev, prec, action, why) -> RiskRule:
    return RiskRule(id_, cat, title, re.compile(pat, re.I), sev, prec, action, why)


RULES: list[RiskRule] = [
    _rule("unlimited_liability", "legal", "Unlimited liability exposure",
          r"unlimited liability|liability (?:shall be|is|will be) unlimited|without (?:any )?(?:limit|cap)(?:ation)? (?:of|on|to) liability|uncapped liability",
          "critical", 0.85, "Negotiate a liability cap or obtain legal review before approval.",
          "Clause removes any ceiling on liability, so potential loss is unbounded."),
    _rule("indemnity", "legal", "Indemnification obligation",
          r"\bindemnif(?:y|ies|ication)\b|hold harmless", "medium", 0.65,
          "Confirm indemnity scope, caps and carve-outs with counsel.",
          "Indemnities transfer third-party claim costs to a party; scope determines exposure."),
    _rule("auto_renewal", "operational", "Automatic renewal clause",
          r"auto(?:matic(?:ally)?)?[- ]?renew\w*|renews? automatically|evergreen", "medium", 0.8,
          "Calendar the non-renewal notice deadline and decide whether to opt out.",
          "Contract renews without action, which can lock in obligations if the notice window is missed."),
    _rule("termination_convenience", "legal", "Termination for convenience",
          r"terminate[sd]?\b[^.]{0,80}\b(?:for convenience|at any time|without cause|for any reason)", "medium", 0.7,
          "Check whether the right is mutual and what notice/penalties apply.",
          "One-sided termination rights reduce revenue/service certainty."),
    _rule("penalty", "financial", "Penalty or liquidated damages",
          r"liquidated damages|\bpenalt(?:y|ies)\b|\bforfeit\w*", "high", 0.75,
          "Quantify the maximum penalty exposure and confirm it is proportionate.",
          "Contractual penalties create direct, pre-agreed financial exposure on breach."),
    _rule("late_interest", "financial", "Late-payment interest or fees",
          r"(?:late (?:payment )?(?:fee|charge|interest)|interest (?:at|of|rate))\b[^.]{0,60}\d", "medium", 0.7,
          "Verify payment terms can be met; consider negotiating the rate.",
          "Late-payment charges accrue on overdue amounts."),
    _rule("exclusivity", "operational", "Exclusivity / non-compete restriction",
          r"\bexclusiv\w+|non-?compet\w+|sole supplier|sole source", "medium", 0.7,
          "Assess impact on alternative suppliers/customers and duration of restriction.",
          "Exclusivity limits commercial flexibility."),
    _rule("ip_assignment", "legal", "Intellectual-property assignment",
          r"assigns? (?:all )?(?:right|title|interest)|work made for hire|work-for-hire", "medium", 0.7,
          "Confirm which IP transfers and whether background IP is excluded.",
          "Assignment transfers ownership of created IP."),
    _rule("data_breach", "security", "Data breach / unauthorised access",
          r"data breach|unauthori[sz]ed (?:access|disclosure|use)|security incident|ransomware|exfiltrat\w+", "high", 0.7,
          "Review incident response, notification duties and affected data scope.",
          "Document references security exposure involving data."),
    _rule("compliance_violation", "compliance", "Regulatory non-compliance",
          r"non-?complian\w+|violat\w+ (?:of )?(?:the )?(?:GDPR|HIPAA|SOX|CCPA|PCI|regulation|law|act)|regulatory (?:fine|penalt\w+|action)|fined",
          "high", 0.75, "Escalate to compliance; confirm remediation owner and deadline.",
          "Text indicates a regulatory breach or enforcement exposure."),
    _rule("financial_distress", "financial", "Financial distress indicator",
          r"going concern|material weakness|covenant (?:breach|violation)|bankruptcy|insolven\w+|restatement|goodwill impairment|default (?:on|under)",
          "critical", 0.8, "Escalate to finance leadership; verify against audited statements.",
          "Language associated with serious solvency or reporting problems."),
    _rule("vulnerability", "security", "Known vulnerability",
          r"CVE-\d{4}-\d{4,}|critical vulnerabilit\w+|unpatched|remote code execution|privilege escalation", "high", 0.75,
          "Prioritise patching and verify exposure in affected systems.",
          "Documented vulnerability that may be exploitable."),
    _rule("as_is_disclaimer", "legal", "Warranty disclaimer (as-is)",
          r"\bas[- ]is\b|disclaims? all warrant\w+", "low", 0.6,
          "Confirm acceptable given the criticality of the deliverable.", "Warranty protection is waived."),
    _rule("unilateral_change", "legal", "Unilateral change rights",
          r"(?:may|reserves the right to) (?:modify|amend|change|update) [^.]{0,60}(?:at any time|without (?:prior )?notice|sole discretion)",
          "medium", 0.65, "Seek mutual-consent or notice requirements for changes.",
          "One party can alter terms without agreement."),
]

_PAYMENT_OBLIGATION = re.compile(r"\b(?:shall|will|must|agrees? to)\s+pay\b|\bpayable\b|\btotal (?:contract )?value\b|\bfees? of\b|\bamount due\b", re.I)


@dataclass
class RiskHit:
    rule_id: str
    category: str
    title: str
    severity: str
    severity_score: float
    precision: float
    sentence: str
    action: str
    reasoning: str
    values: list[str] = field(default_factory=list)


_NEGATORS = re.compile(r"\b(no|not|without|never|neither|nor|absence of|free (?:from|of)|did not|does not|do not|has not|have not|nothing)\b", re.I)


def _negated(sentence: str, m: re.Match) -> bool:
    window = sentence[max(0, m.start() - 60):m.end()]
    return bool(_NEGATORS.search(window))


def scan_sentence(sentence: str) -> list[RiskHit]:
    hits: list[RiskHit] = []
    for r in RULES:
        m = r.pattern.search(sentence)
        if not m or _negated(sentence, m):
            continue
        sev, vals = r.severity, []
        score = SEVERITY_SCORE[sev]
        if r.id == "late_interest":
            pcts = V.parse_percents(sentence)
            if pcts:
                vals = [p.raw for p in pcts]
                rate = max(p.value for p in pcts)
                per_month = re.search(r"per month|monthly", sentence, re.I)
                score = 0.75 if (rate >= 1.5 and per_month) or rate >= 18 else 0.5
        if r.id == "penalty":
            m = V.parse_money(sentence)
            if m:
                vals = [x.raw for x in m]
                amt = max(float(x.value) for x in m)
                score = 0.9 if amt >= 1e6 else 0.75 if amt >= 1e5 else 0.55
        hits.append(RiskHit(r.id, r.category, r.title, severity_from_score(score), score, r.precision, sentence.strip(),
                            r.action, r.reasoning, vals))
    if _PAYMENT_OBLIGATION.search(sentence):
        money = V.parse_money(sentence)
        if money:
            amt = max(float(m.value) for m in money)
            if amt >= 1e6:
                score = 0.9 if amt >= 1e7 else 0.7 if amt >= 5e6 else 0.5
                hits.append(RiskHit("payment_obligation", "financial", f"Material payment obligation ({money[0].raw})",
                                    severity_from_score(score), score, 0.7, sentence.strip(),
                                    "Confirm budget approval and payment schedule.",
                                    "A payment obligation of this size is financially material.", [m.raw for m in money]))
    short_notice = re.search(r"\b(\d{1,2})\s*(?:calendar\s*)?days?'?\s+(?:written\s+|prior\s+)?notice", sentence, re.I)
    if short_notice and int(short_notice.group(1)) <= 7 and re.search(r"terminat|cancel|chang|modif", sentence, re.I):
        hits.append(RiskHit("short_notice", "operational", f"Short notice period ({short_notice.group(0).strip()})", "medium",
                            0.5, 0.65, sentence.strip(), "Assess whether the notice window is operationally workable.",
                            "Very short notice limits time to react or find alternatives.", [short_notice.group(0)]))
    return hits
