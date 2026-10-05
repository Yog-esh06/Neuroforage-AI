"""Table normalisation: raw cell grids -> {headers, rows} with structure preserved."""
from __future__ import annotations

import re
from typing import Any

_NUM_RE = re.compile(r"^[\(\-\+]?[\$€£₹]?\s*\d[\d,\.]*\s*(?:%|[kKmMbB])?\)?$")


def _clean(cell: Any) -> str:
    if cell is None:
        return ""
    return re.sub(r"\s+", " ", str(cell).replace("\n", " ")).strip()


def is_numeric_cell(cell: str) -> bool:
    return bool(_NUM_RE.match(cell.strip())) if cell else False


def normalize_table(raw_rows: list[list[Any]], *, assume_header: bool | None = None) -> dict[str, Any] | None:
    """Clean a raw grid. Returns None when nothing meaningful remains.

    Header detection: the first row is a header if it has no numeric cells while a later row does, or if
    `assume_header` is forced (spreadsheets / docx tables with a header style).
    """
    rows = [[_clean(c) for c in r] for r in raw_rows if r is not None]
    rows = [r for r in rows if any(r)]
    if not rows:
        return None
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    keep = [j for j in range(width) if any(r[j] for r in rows)]  # drop fully empty columns
    rows = [[r[j] for j in keep] for r in rows]
    if not rows or not rows[0]:
        return None

    first = rows[0]
    has_header = assume_header
    if has_header is None:
        first_numeric = sum(is_numeric_cell(c) for c in first)
        later_numeric = sum(is_numeric_cell(c) for r in rows[1:] for c in r)
        has_header = len(rows) > 1 and first_numeric == 0 and (later_numeric > 0 or all(first))
    if has_header:
        headers = _dedupe([c or f"Column {i + 1}" for i, c in enumerate(first)])
        body = rows[1:]
    else:
        headers = [f"Column {i + 1}" for i in range(len(first))]
        body = rows
    return {"headers": headers, "rows": body, "n_rows": len(body), "n_cols": len(headers), "has_header": bool(has_header)}


def _dedupe(headers: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for h in headers:
        seen[h] = seen.get(h, 0) + 1
        out.append(h if seen[h] == 1 else f"{h} ({seen[h]})")
    return out


def table_to_text(table: dict[str, Any]) -> str:
    """Pipe-delimited rendering used as the element's text."""
    headers, rows = table["headers"], table["rows"]
    lines = [" | ".join(headers)] if table.get("has_header", True) else []
    lines += [" | ".join(r) for r in rows]
    return "\n".join(lines)


def row_to_sentence(headers: list[str], row: list[str]) -> str:
    """Serialise a row as 'Header: value; Header: value' so retrieval sees cell relationships."""
    return "; ".join(f"{h}: {v}" for h, v in zip(headers, row) if v)
