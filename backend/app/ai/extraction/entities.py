"""Entity extraction: deterministic rules + optional spaCy NER. No LLM involved.

Entity types: PERSON, ORG, LOCATION, DATE, MONEY, PRODUCT, TECHNOLOGY, CONTRACT, REGULATION, EVENT, METRIC.

Methods recorded per mention:
  rule:<name>   regex / lexicon / gazetteer
  spacy         statistical NER model (if the model package is installed)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache

from app.ai.extraction import values as V
from app.core.config import get_settings
from app.utils.text import canonical_key

log = logging.getLogger(__name__)

TYPES = ("PERSON", "ORG", "LOCATION", "DATE", "MONEY", "PRODUCT", "TECHNOLOGY", "CONTRACT", "REGULATION", "EVENT", "METRIC")


@dataclass
class EntityMention:
    text: str
    type: str
    start: int
    end: int
    method: str
    confidence: float = 0.8
    normalized: dict = field(default_factory=dict)

    @property
    def canonical(self) -> str:
        if self.type == "MONEY":
            return f"{self.normalized.get('currency') or ''}{self.normalized.get('amount', self.text)}"
        if self.type == "DATE":
            return str(self.normalized.get("iso", self.text)).lower()
        return canonical_key(self.text)


ORG_SUFFIX = r"(?:Inc\.?|Incorporated|LLC|L\.L\.C\.|Ltd\.?|Limited|Corp\.?|Corporation|Co\.|Company|GmbH|PLC|plc|Pvt\.?(?:\s+Ltd\.?)?|Pty\.?\s+Ltd\.?|LLP|AG|S\.A\.|N\.V\.|Holdings|Group|Technologies|Systems|Solutions|Industries|Partners|Bank|Capital|Labs|University|Institute|Foundation|Agency|Authority|Department|Ministry|Commission)"
_CAP = r"[A-Z][A-Za-z0-9&'\-]+"
ORG_RE = re.compile(rf"\b((?:{_CAP}[ \t]+(?:(?:of|and|&|for)[ \t]+)?){{0,4}}{_CAP}(?:[ \t]+{ORG_SUFFIX})+)(?=\W|$)")
PERSON_TITLE_RE = re.compile(r"\b(?:Mr|Mrs|Ms|Dr|Prof|Hon|Sir)\.?\s+((?:[A-Z][a-z]+(?:\s+[A-Z]\.)?\s+)?[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)")
PERSON_ROLE_RE = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z]\.)?\s+[A-Z][a-z]+(?:-[A-Z][a-z]+)?)\s*,\s*(?:the\s+)?(?:Chief [A-Z][a-z]+ Officer|CEO|CFO|CTO|COO|President|Vice President|VP|Director|Managing Director|Manager|Partner|Founder|General Counsel|Chairman|Principal Investigator|Authorized Signatory)\b")
PERSON_SIGN_RE = re.compile(r"(?:By|Signed|Name|Attn|Attention|Prepared by|Author|Contact)\s*[:\-]\s*([A-Z][a-z]+(?:\s+[A-Z]\.)?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)")
CONTRACT_RE = re.compile(
    r"\b((?:[A-Z][A-Za-z]+[ \t]+){0,3}(?:Master[ \t]+)?(?:Services?|Supply|Licen[sc]e|Software|Consulting|Employment|Lease|Non-Disclosure|Distribution|Purchase|Sales|Service Level|Data Processing|Partnership|Reseller|Subscription)\s+(?:Agreement|Contract)|"
    r"(?:Agreement|Contract|Purchase Order|PO|Amendment|Addendum|Statement of Work|SOW|Invoice)[ \t]*(?:No\.?|Number|#)[ \t]*[:\-]?[ \t]*[A-Z0-9][A-Z0-9\-/]*)", )
REGULATIONS = ["GDPR", "HIPAA", "SOX", "Sarbanes-Oxley", "CCPA", "PCI DSS", "PCI-DSS", "ISO 27001", "ISO 9001", "SOC 2", "SOC2",
               "FERPA", "GLBA", "FCPA", "MiFID II", "Basel III", "IFRS", "GAAP", "FDA", "FISMA", "NIST", "DPDP Act", "IT Act",
               "Companies Act", "Dodd-Frank", "AML", "KYC", "CSRD", "EU AI Act", "ePrivacy"]
REG_RE = re.compile(r"\b(" + "|".join(re.escape(r) for r in sorted(REGULATIONS, key=len, reverse=True)) + r")\b")
TECHNOLOGIES = ["Python", "Java", "JavaScript", "TypeScript", "Kubernetes", "Docker", "PostgreSQL", "MySQL", "MongoDB", "Redis",
                "Kafka", "AWS", "Azure", "Google Cloud", "GCP", "TensorFlow", "PyTorch", "Hadoop", "Spark", "Snowflake",
                "Terraform", "React", "Node.js", "Linux", "Oracle", "SAP", "Salesforce", "SQL", "REST API", "GraphQL",
                "machine learning", "deep learning", "neural network", "transformer", "blockchain", "OAuth", "TLS", "SSO",
                "FAISS", "BERT", "GPT", "LLM", "OCR", "ETL", "CI/CD", "IoT", "5G"]
TECH_RE = re.compile(r"(?<![\w])(" + "|".join(re.escape(t) for t in sorted(TECHNOLOGIES, key=len, reverse=True)) + r")(?![\w])")
LOCATIONS = ["United States", "USA", "U.S.", "United Kingdom", "UK", "India", "Germany", "France", "Singapore", "Canada", "Australia",
             "Japan", "China", "Brazil", "Mexico", "Ireland", "Netherlands", "Switzerland", "Spain", "Italy", "Sweden", "Dubai", "UAE",
             "European Union", "EU", "Europe", "Asia", "Africa", "North America", "California", "Texas", "New York", "London", "Paris",
             "Berlin", "Mumbai", "Bangalore", "Bengaluru", "Delhi", "Hyderabad", "Pune", "Chennai", "Tokyo", "Sydney", "Toronto",
             "Delaware", "Massachusetts", "Washington", "Seattle", "San Francisco", "Boston", "Chicago", "Austin", "Dublin"]
LOC_RE = re.compile(r"(?<![\w])(" + "|".join(re.escape(l) for l in sorted(LOCATIONS, key=len, reverse=True)) + r")(?![\w])")
EVENT_RE = re.compile(r"\b((?:Q[1-4]\s+(?:19|20)\d{2})|(?:FY\s?(?:19|20)?\d{2})|(?:[A-Z][A-Za-z]+\s+(?:Conference|Summit|Symposium|Workshop|Audit|Merger|Acquisition|Incident|Breach|Outage|Launch|IPO)))\b")
METRIC_RE = re.compile(
    r"\b((?:revenue|net income|profit|EBITDA|margin|churn|accuracy|precision|recall|F1(?:-score)?|latency|uptime|throughput|growth|ROI|NPS|CAGR|headcount|backlog)"
    r"(?:\s+(?:of|was|is|at|to|reached|increased to|decreased to|grew to))?\s*[:=]?\s*[\$€£₹]?\d[\d,\.]*\s?(?:%|[kKmMbB]\b|million|billion|ms|s\b)?)", re.I)
PRODUCT_RE = re.compile(r"\b((?:[A-Z][A-Za-z0-9]+(?:\s[A-Z][A-Za-z0-9]+)?)\s(?:Platform|Suite|Pro|Cloud|Engine|Gateway|Portal|Module|Edition|Series|Service|API|SDK|Server|Appliance))\b")

# ORG candidates containing these as first token are most likely sentence-initial noise
_ORG_STOP_START = {"This", "That", "The", "These", "Those", "Such", "Each", "Any", "All", "Both", "Either", "Neither"}
_ROLE_WORDS = {"Chief", "Executive", "Officer", "President", "Vice", "Director", "Managing", "Manager", "Partner", "Founder", "General", "Counsel", "Chairman", "Principal", "Authorized", "Signatory", "Senior", "Head", "CEO", "CFO", "CTO", "COO", "Of", "Of the", "and", "&", "for"}
_INSTITUTION_WORDS = {"Bank", "University", "Institute", "Department", "Ministry", "Commission", "Agency", "Authority", "Foundation", "Group", "Bureau",
                      "College", "Office", "Council", "Board", "Federation", "Association", "Society", "Academy", "Court", "Government"}
_ORG_BAD = {"company", "group", "limited", "corporation", "inc", "ltd", "holdings", "partners", "department", "agency"}
_LEADING_NOISE = re.compile(r"^(?:Between|Among|And|With|By|From|To|For|Of|Within|Under|Per|Whereas|Between)\s+", re.I)
_PARTY_DEF = re.compile(r"\(\s*(?:the\s+|“|\")?\s*[“\"]?(Client|Customer|Supplier|Vendor|Provider|Licensor|Licensee|Company|Buyer|Seller|Contractor|Consultant|Landlord|Tenant|Employer|Employee)[”\"]?\s*\)")


class _Spacy:
    nlp = None
    tried = False


@lru_cache
def _load_spacy():
    if _Spacy.tried:
        return _Spacy.nlp
    _Spacy.tried = True
    try:
        import spacy

        name = get_settings().spacy_model
        _Spacy.nlp = spacy.load(name, disable=["lemmatizer"])
        log.info("spaCy model loaded: %s", name)
    except Exception as e:
        log.info("spaCy model unavailable (%s); using rule-based NER only", e)
        _Spacy.nlp = None
    return _Spacy.nlp


def spacy_available() -> bool:
    return _load_spacy() is not None


_SPACY_MAP = {"PERSON": "PERSON", "ORG": "ORG", "GPE": "LOCATION", "LOC": "LOCATION", "FAC": "LOCATION", "PRODUCT": "PRODUCT",
              "EVENT": "EVENT", "LAW": "REGULATION"}


_GENERIC_PHRASES = {"effective date", "renewal date", "invoice date", "due date", "expiry date", "expiration date", "termination date", "agreement",
                    "amendment", "contract", "supplier", "client", "customer", "vendor", "company", "party", "parties", "provider", "licensor",
                    "licensee", "buyer", "seller", "services", "term", "fees", "schedule", "exhibit", "section", "article", "clause", "annex",
                    "appendix", "confidential information", "force majeure", "governing law", "bill to", "remit to", "bill", "invoice", "ship to", "total", "subtotal"}
_GENERIC_TOKENS = {"date", "effective", "renewal", "invoice", "due", "expiry", "expiration", "termination", "term", "the", "this", "agreement",
                   "amendment", "contract", "party", "parties", "services", "service", "fees", "schedule", "supplier", "client", "customer", "vendor",
                   "company", "total", "amount", "payment", "terms"}


def is_generic_name(name: str) -> bool:
    """Document-structure words and defined-term roles ("the Effective Date", "Supplier") are not real-world entities."""
    if any(ch in name for ch in ",|@:;"):  # table headers / e-mail fragments / list separators are not entity names
        return True
    low = re.sub(r"^(?:the|this|a|an)\s+", "", name.strip().lower())
    toks = re.findall(r"[a-z]+", low)
    return low in _GENERIC_PHRASES or (bool(toks) and all(t in _GENERIC_TOKENS for t in toks))


def _clean_org(text: str) -> str | None:
    t = _LEADING_NOISE.sub("", text.strip(" ,.;:()"))
    toks = t.split()
    while toks and (toks[0] in _ORG_STOP_START or toks[0] in _ROLE_WORDS or toks[0].lower() in ("of", "and", "for")):
        toks = toks[1:]
    t = " ".join(toks)
    # "X of Y" is one organisation only when X is an institution word (Bank of America, University of Texas);
    # otherwise ("Priya Nair of Acme Corp") the organisation is the part after "of".
    m_of = re.match(r"^(.*?)\s+(?:of|for)\s+(.+)$", t)
    if m_of and m_of.group(1).split()[-1] not in _INSTITUTION_WORDS:
        t = m_of.group(2)
        toks = t.split()
    if len(t) < 3 or t.lower() in _ORG_BAD or is_generic_name(t):
        return None
    if len(toks) == 1 and toks[0].lower().rstrip(".") in _ORG_BAD:
        return None
    return t


def _overlaps(span: tuple[int, int], taken: list[tuple[int, int, str]], types: tuple[str, ...] | None = None) -> bool:
    return any(not (span[1] <= a or span[0] >= b) and (types is None or t in types) for a, b, t in taken)


BARE_CONTRACT_RE = re.compile(r"\b(?:this|the)\s+(?:Agreement|Contract|Amendment)\b", re.I)


def find_default_contract(text: str) -> str | None:
    """The first explicitly named contract in a document; bare 'this Agreement' references resolve to it."""
    for m in CONTRACT_RE.finditer(text):
        name = re.sub(r"^(?:This|The)\s+", "", m.group(1).strip())
        if len(name.split()) >= 2:
            return name
    return None


def extract_entities(text: str, *, use_spacy: bool = True, default_contract: str | None = None) -> list[EntityMention]:
    """Return non-overlapping-by-type entity mentions in order of appearance."""
    mentions: list[EntityMention] = []
    taken: list[tuple[int, int, str]] = []

    def add(m: EntityMention):
        mentions.append(m)
        taken.append((m.start, m.end, m.type))

    # --- numeric/structured values (fully deterministic)
    for v in V.parse_money(text):
        add(EntityMention(v.raw, "MONEY", v.start, v.end, "rule:money", 0.95,
                          {"amount": round(float(v.value), 2), "currency": v.currency}))
    for v in V.parse_dates(text):
        if v.precision == "year" and any(abs(v.start - s) < 2 for s, _, _ in taken):
            continue
        add(EntityMention(v.raw, "DATE", v.start, v.end, "rule:date", 0.95, {"iso": v.value, "precision": v.precision}))
    for v in V.parse_durations(text):
        add(EntityMention(v.raw, "METRIC", v.start, v.end, "rule:duration", 0.8, {"kind": "duration", "days": v.value}))
    for m in METRIC_RE.finditer(text):
        if not _overlaps((m.start(), m.end()), taken, ("MONEY",)):
            add(EntityMention(m.group(1).strip(), "METRIC", m.start(1), m.end(1), "rule:metric", 0.75, {"kind": "metric"}))

    # --- lexicon / pattern entities
    for m in CONTRACT_RE.finditer(text):
        name = re.sub(r"^(?:This|The)\s+", "", m.group(1).strip())
        add(EntityMention(name, "CONTRACT", m.start(1), m.end(1), "rule:contract", 0.85))
    if default_contract:
        for m in BARE_CONTRACT_RE.finditer(text):
            if not _overlaps((m.start(), m.end()), taken, ("CONTRACT",)):
                add(EntityMention(default_contract, "CONTRACT", m.start(), m.end(), "rule:contract-ref", 0.7))
    for m in REG_RE.finditer(text):
        add(EntityMention(m.group(1), "REGULATION", m.start(1), m.end(1), "rule:regulation", 0.9))
    for m in TECH_RE.finditer(text):
        add(EntityMention(m.group(1), "TECHNOLOGY", m.start(1), m.end(1), "rule:technology", 0.8))
    for m in LOC_RE.finditer(text):
        add(EntityMention(m.group(1), "LOCATION", m.start(1), m.end(1), "rule:gazetteer", 0.8))
    for m in EVENT_RE.finditer(text):
        if not _overlaps((m.start(1), m.end(1)), taken, ("DATE", "MONEY")):
            add(EntityMention(m.group(1), "EVENT", m.start(1), m.end(1), "rule:event", 0.7))
    for m in PRODUCT_RE.finditer(text):
        if not _overlaps((m.start(1), m.end(1)), taken):
            add(EntityMention(m.group(1), "PRODUCT", m.start(1), m.end(1), "rule:product", 0.6))
    for m in ORG_RE.finditer(text):
        name = _clean_org(m.group(1))
        if name and not _overlaps((m.start(1), m.end(1)), taken, ("CONTRACT", "REGULATION")):
            start = m.start(1) + (m.group(1).find(name) if name in m.group(1) else 0)
            add(EntityMention(name, "ORG", start, start + len(name), "rule:org-suffix", 0.8))
    for rx, label, conf in ((PERSON_TITLE_RE, "title", 0.85), (PERSON_ROLE_RE, "role", 0.85), (PERSON_SIGN_RE, "signature", 0.75)):
        for m in rx.finditer(text):
            if not _overlaps((m.start(1), m.end(1)), taken, ("ORG", "CONTRACT")):
                add(EntityMention(m.group(1).strip(), "PERSON", m.start(1), m.end(1), f"rule:person-{label}", conf))

    # --- statistical NER (adds what rules miss; never overrides structured types)
    nlp = _load_spacy() if use_spacy else None
    if nlp is not None and text.strip():
        try:
            for ent in nlp(text[:100000]).ents:
                etype = _SPACY_MAP.get(ent.label_)
                if not etype:
                    continue
                if _overlaps((ent.start_char, ent.end_char), taken):
                    continue
                name = ent.text.strip()
                if etype == "ORG":
                    name = _clean_org(name) or ""
                if len(name) < 3 or is_generic_name(name):
                    continue
                add(EntityMention(name, etype, ent.start_char, ent.end_char, "spacy", 0.7))
        except Exception as e:  # pragma: no cover - model-specific failures
            log.warning("spaCy extraction failed: %s", e)

    # Defined-term party aliases: 'Acme Corp (the "Client")' -> alias Client = Acme Corp (kept as attribute on ORG)
    for m in _PARTY_DEF.finditer(text):
        prev = [x for x in mentions if x.type == "ORG" and x.end <= m.start() and m.start() - x.end < 6]
        if prev:
            prev[-1].normalized["role"] = m.group(1).title()

    mentions.sort(key=lambda x: (x.start, -(x.end - x.start)))
    return mentions
