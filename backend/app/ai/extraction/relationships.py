"""Relationship extraction between entity mentions inside a sentence.

Approach: for each ordered pair (A before B) in the same sentence, test the connecting text against a typed rule
table (verb/preposition patterns). Rules are deterministic and every relationship records the exact sentence as
evidence. Pairs with no rule fall back to a low-confidence `co_occurs_with` only for informative type pairs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.ai.extraction.entities import EntityMention
from app.utils.text import split_sentences

PARTY = ("ORG", "PERSON")


@dataclass
class Relation:
    source: EntityMention
    target: EntityMention
    relation: str
    confidence: float
    evidence: str
    method: str


@dataclass(frozen=True)
class Rule:
    src: tuple[str, ...]
    dst: tuple[str, ...]
    pattern: re.Pattern
    relation: str
    confidence: float
    swap: bool = False  # connecting text describes dst -> src (passive voice)


def _r(src, dst, pat, rel, conf=0.8, swap=False) -> Rule:
    return Rule(tuple(src.split("|")), tuple(dst.split("|")), re.compile(pat, re.I), rel, conf, swap)


RULES: list[Rule] = [
    _r("ORG|PERSON", "CONTRACT", r"\b(sign(?:ed|s)?|execut(?:ed|es)|entered into|enter(?:s)? into|agreed to|accepted)\b", "signed", 0.9),
    _r("ORG|PERSON", "CONTRACT", r"\b(party to|parties to|bound by|counterparty (?:to|under)|subject to)\b", "party_to", 0.85),
    _r("ORG|PERSON", "CONTRACT", r"\b(between|by and between|with|made by|issued to|issued by)\b", "party_to", 0.7, swap=True),
    _r("ORG|PERSON", "MONEY", r"\b(paid|pays|pay|payable|shall pay|will pay|remit(?:ted|s)?|reimburs\w+)\b", "paid", 0.85),
    _r("ORG|PERSON", "MONEY", r"\b(received|receives|invoiced|billed|charged|owes?|owed)\b", "billed", 0.75),
    _r("ORG|PERSON", "MONEY", r"\b(reported|generated|earned|recorded|posted|achieved)\b", "reported", 0.7),
    _r("ORG|PERSON", "MONEY", r"\b(paid|payable|owed|due|remitted)\s+(?:to|by)\b", "paid", 0.8, swap=True),
    _r("CONTRACT", "MONEY", r"\b(worth|valued at|value of|total value|total|fees?|amount|price|priced at|consideration|for a total|not to exceed|up to|capped at)\b", "worth", 0.85),
    _r("CONTRACT", "MONEY", r"\b(penalty|liquidated damages|late fee|liability cap|limit of liability|cap)\b", "penalty_of", 0.8),
    _r("CONTRACT", "DATE", r"\b(expires?|expir\w+|terminat\w+|ends?|until|through|valid until|term ends)\b", "expires_on", 0.85),
    _r("CONTRACT", "DATE", r"\b(effective|commenc\w+|begins?|starts?|dated|made as of|entered into as of)\b", "effective_from", 0.8),
    _r("CONTRACT", "DATE", r"\b(renew\w*|auto-?renew\w*)\b", "renews_on", 0.7),
    _r("ORG|CONTRACT", "REGULATION", r"\b(compl(?:y|ies|iance) with|in accordance with|governed by|subject to|pursuant to|certified (?:under|to)|adher\w+ to)\b", "complies_with", 0.8),
    _r("ORG|PERSON", "LOCATION", r"\b(operat\w+ (?:in|across)|located in|headquartered in|based in|offices? in|registered in|incorporated in|resident in|domiciled in|established in)\b", "operates_in", 0.85),
    _r("CONTRACT", "LOCATION", r"\b(governed by the laws of|jurisdiction of|laws of|courts of|venue)\b", "governed_in", 0.8),
    _r("ORG", "ORG", r"\b(acquir\w+|bought|purchased)\b", "acquired", 0.8),
    _r("ORG", "ORG", r"\b(subsidiary of|wholly[- ]owned by|owned by|parent of)\b", "subsidiary_of", 0.8),
    _r("ORG", "ORG", r"\b(supplies|supplier to|provides?|provided to|licens(?:es|ed) to|services? to|vendor (?:to|of)|sells? to|delivers? to)\b", "supplies", 0.7),
    _r("ORG", "ORG", r"\b(partner(?:s|ed)? with|partnership with|collaborat\w+ with|joint venture with|alliance with)\b", "partners_with", 0.8),
    _r("ORG", "ORG", r"\b(between|and|by and between)\b", "counterparty_of", 0.5),
    _r("PERSON", "ORG", r"\b(ceo|cfo|cto|coo|president|director|manager|partner|founder|chair\w*|counsel|officer|employee|works? (?:at|for)|employed by|joined|represents?)\b", "works_for", 0.75),
    _r("ORG|PERSON", "TECHNOLOGY", r"\b(uses?|using|built (?:on|with)|deploys?|runs? on|leverages?|implemented (?:in|with)|based on|powered by|adopts?)\b", "uses", 0.7),
    _r("ORG", "PRODUCT", r"\b(sells?|offers?|develops?|launch\w+|markets?|provides?|released?)\b", "offers", 0.7),
    _r("PRODUCT", "TECHNOLOGY", r"\b(uses?|built (?:on|with)|runs? on|based on|powered by|implemented (?:in|with))\b", "uses", 0.65),
    _r("ORG|PERSON", "METRIC", r"\b(reported|achieved|recorded|reached|delivered|grew to|increased to|decreased to)\b", "reported", 0.65),
    _r("ORG", "EVENT", r"\b(hosted|announced|completed|experienced|suffered|launched|held)\b", "involved_in", 0.6),
    _r("PERSON", "CONTRACT", r"\b(authori[sz]ed|signator\w+|signature)\b", "signed", 0.6),
    _r("ORG|PERSON|CONTRACT", "REGULATION", r"\b(regulat\w+|under|per|according to)\b", "complies_with", 0.5),
]

# Informative type pairs worth recording as weak co-occurrence when no rule matched
_COOCCUR_OK = {("ORG", "CONTRACT"), ("PERSON", "ORG"), ("ORG", "ORG"), ("CONTRACT", "REGULATION"), ("ORG", "PRODUCT"),
               ("ORG", "LOCATION"), ("PERSON", "CONTRACT"), ("CONTRACT", "CONTRACT")}
MAX_PAIR_DISTANCE = 240


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    spans, pos = [], 0
    for s in split_sentences(text):
        i = text.find(s, pos)
        if i < 0:
            continue
        spans.append((i, i + len(s)))
        pos = i + len(s)
    return spans or [(0, len(text))]


def extract_relationships(text: str, mentions: list[EntityMention]) -> list[Relation]:
    out: list[Relation] = []
    seen: set[tuple] = set()
    for s0, s1 in _sentence_spans(text):
        sent_ms = [m for m in mentions if m.start >= s0 and m.end <= s1]
        if len(sent_ms) < 2:
            continue
        sentence = text[s0:s1].strip()
        for i, a in enumerate(sent_ms):
            for b in sent_ms[i + 1:]:
                if a.type == b.type == "DATE" or a.canonical == b.canonical and a.type == b.type:
                    continue
                gap = b.start - a.end
                if gap < 0 or gap > MAX_PAIR_DISTANCE:
                    continue
                between = text[a.end:b.start]
                matched: Rule | None = None
                # another party between the two mentions means the connecting verb belongs to that party, not to `a`
                blocked = any(a.end <= m.start and m.end <= b.start and m.type in PARTY and m is not a and m is not b for m in sent_ms)
                for rule in RULES:
                    if blocked and not (a.type in PARTY and b.type in PARTY):
                        continue
                    if rule.swap:
                        ok = a.type in rule.dst and b.type in rule.src
                    else:
                        ok = a.type in rule.src and b.type in rule.dst
                    if ok and rule.pattern.search(between):
                        matched = rule
                        break
                if matched:
                    src, dst = (b, a) if matched.swap else (a, b)
                    rel, conf, method = matched.relation, matched.confidence, "rule"
                    # distance decay: far-apart mentions are less certain
                    conf = round(conf * (1.0 if gap < 80 else 0.9 if gap < 160 else 0.8), 3)
                elif (a.type, b.type) in _COOCCUR_OK and gap < 120:
                    src, dst, rel, conf, method = a, b, "co_occurs_with", 0.3, "co-occurrence"
                else:
                    continue
                key = (src.canonical, src.type, dst.canonical, dst.type, rel, s0)
                if key in seen:
                    continue
                seen.add(key)
                out.append(Relation(src, dst, rel, conf, sentence, method))
    return out
