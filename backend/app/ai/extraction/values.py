"""Deterministic parsing/normalisation of money, dates and durations (shared by entities, contradictions, comparison)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
MONTHS["sept"] = 9

_MONTH_RE = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"

# order matters: most specific first
DATE_PATTERNS = [
    re.compile(rf"\b(?P<m>{_MONTH_RE})\.?\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<y>(?:19|20)\d{{2}})\b", re.I),
    re.compile(rf"\b(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<m>{_MONTH_RE})\.?,?\s+(?P<y>(?:19|20)\d{{2}})\b", re.I),
    re.compile(r"\b(?P<y>(?:19|20)\d{2})-(?P<mn>0?[1-9]|1[0-2])-(?P<d>0?[1-9]|[12]\d|3[01])\b"),
    re.compile(r"\b(?P<mn>0?[1-9]|1[0-2])/(?P<d>0?[1-9]|[12]\d|3[01])/(?P<y>(?:19|20)\d{2})\b"),
    re.compile(rf"\b(?P<m>{_MONTH_RE})\.?,?\s+(?P<y>(?:19|20)\d{{2}})\b", re.I),  # month-year
]
YEAR_ONLY = re.compile(r"\b(?:in|by|until|through|during|fiscal year|FY)\s+((?:19|20)\d{2})\b", re.I)

CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "₹": "INR", "¥": "JPY"}
_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "mm": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9,
          "lakh": 1e5, "lakhs": 1e5, "crore": 1e7, "crores": 1e7, "cr": 1e7}
MONEY_RE = re.compile(
    r"(?P<cur>US\$|USD|EUR|GBP|INR|Rs\.?|[$€£₹¥])\s?(?P<num>\d[\d,]*(?:\.\d+)?)\s?(?P<scale>billion|million|thousand|lakhs?|crores?|bn|mm|mn|cr|[kKmMbB])?\b"
    r"|(?P<num2>\d[\d,]*(?:\.\d+)?)\s?(?P<scale2>billion|million|thousand|lakhs?|crores?)?\s?(?P<cur2>USD|EUR|GBP|INR|dollars|euros|rupees)\b",
    re.I,
)
DURATION_RE = re.compile(
    r"\b(?P<n>\d{1,4}|one|two|three|four|five|six|seven|eight|nine|ten|twelve|eighteen|twenty[- ]four|thirty|sixty|ninety)"
    r"(?:\s*\(\d+\))?[- ]+(?P<unit>day|week|month|year)s?\b", re.I)
_WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
             "twelve": 12, "eighteen": 18, "twenty-four": 24, "twenty four": 24, "thirty": 30, "sixty": 60, "ninety": 90}
PERCENT_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d+)?)\s?(?:%|percent\b|per cent\b)", re.I)


@dataclass(frozen=True)
class ParsedValue:
    kind: str  # date | money | duration | percent
    raw: str
    value: float | str  # money: amount; date: ISO string; duration: days; percent: number
    start: int
    end: int
    currency: str | None = None
    precision: str = ""  # date: day|month|year

    def display(self) -> str:
        return self.raw


def _month_num(tok: str) -> int | None:
    return MONTHS.get(tok.lower().rstrip("."))


def parse_dates(text: str) -> list[ParsedValue]:
    found: list[ParsedValue] = []
    taken: list[tuple[int, int]] = []
    for pat in DATE_PATTERNS:
        for m in pat.finditer(text):
            if any(not (m.end() <= a or m.start() >= b) for a, b in taken):
                continue
            g = m.groupdict()
            y = int(g["y"])
            mo = int(g["mn"]) if g.get("mn") else _month_num(g["m"]) if g.get("m") else None
            if mo is None:
                continue
            d = int(g["d"]) if g.get("d") else None
            try:
                if d:
                    iso, prec = date(y, mo, d).isoformat(), "day"
                else:
                    iso, prec = f"{y:04d}-{mo:02d}", "month"
            except ValueError:
                continue
            taken.append((m.start(), m.end()))
            found.append(ParsedValue("date", m.group(0), iso, m.start(), m.end(), precision=prec))
    for m in YEAR_ONLY.finditer(text):
        if any(not (m.end() <= a or m.start() >= b) for a, b in taken):
            continue
        found.append(ParsedValue("date", m.group(1), m.group(1), m.start(1), m.end(1), precision="year"))
    return sorted(found, key=lambda v: v.start)


def parse_money(text: str) -> list[ParsedValue]:
    out = []
    for m in MONEY_RE.finditer(text):
        num = m.group("num") or m.group("num2")
        cur_tok = (m.group("cur") or m.group("cur2") or "").strip().rstrip(".")
        scale = (m.group("scale") or m.group("scale2") or "").lower()
        try:
            amount = float(num.replace(",", ""))
        except ValueError:
            continue
        amount *= _SCALE.get(scale, 1.0)
        cur = CURRENCY_SYMBOLS.get(cur_tok) or {"us$": "USD", "rs": "INR", "dollars": "USD", "euros": "EUR", "rupees": "INR"}.get(
            cur_tok.lower(), cur_tok.upper() or None)
        if amount < 1 and not scale:
            continue
        out.append(ParsedValue("money", m.group(0).strip(), amount, m.start(), m.end(), currency=cur))
    return out


def parse_durations(text: str) -> list[ParsedValue]:
    out = []
    for m in DURATION_RE.finditer(text):
        n = m.group("n").lower()
        n = int(n) if n.isdigit() else _WORD_NUM.get(n.replace("  ", " "), 0)
        if not n:
            continue
        days = n * {"day": 1, "week": 7, "month": 30, "year": 365}[m.group("unit").lower()]
        out.append(ParsedValue("duration", m.group(0).strip(), float(days), m.start(), m.end()))
    return out


def parse_percents(text: str) -> list[ParsedValue]:
    return [ParsedValue("percent", m.group(0), float(m.group(1)), m.start(), m.end()) for m in PERCENT_RE.finditer(text)]


def parse_all(text: str) -> list[ParsedValue]:
    vals = parse_dates(text) + parse_money(text) + parse_durations(text) + parse_percents(text)
    return sorted(vals, key=lambda v: v.start)


def format_money(amount: float, currency: str | None = None) -> str:
    sym = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹"}.get(currency or "", "")
    if amount >= 1e9:
        s = f"{amount / 1e9:.2f}B"
    elif amount >= 1e6:
        s = f"{amount / 1e6:.2f}M"
    elif amount >= 1e4:
        s = f"{amount / 1e3:.1f}K"
    else:
        s = f"{amount:,.2f}".rstrip("0").rstrip(".")
    return f"{sym}{s}" if sym else f"{s} {currency or ''}".strip()


def money_close(a: float, b: float, rel: float = 0.005) -> bool:
    return abs(a - b) <= rel * max(abs(a), abs(b), 1.0)
