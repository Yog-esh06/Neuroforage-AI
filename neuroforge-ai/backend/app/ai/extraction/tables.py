"""Semantic table understanding: column typing, cell relationships and numeric integrity checks."""
from __future__ import annotations

import re
from typing import Any

from app.ai.extraction import values as V

_TOTAL_LABEL = re.compile(r"^\s*(grand\s+)?(total|sum|net total|amount due|balance due|total due|subtotal)\b", re.I)


def _num(cell: str) -> float | None:
    c = cell.strip()
    if not c:
        return None
    neg = c.startswith("(") and c.endswith(")") or c.startswith("-")
    digits = re.sub(r"[^\d\.]", "", c)
    if not digits or digits.count(".") > 1:
        return None
    try:
        v = float(digits)
    except ValueError:
        return None
    return -v if neg else v


def infer_column_type(cells: list[str]) -> str:
    vals = [c for c in cells if c and c.strip()]
    if not vals:
        return "empty"
    n = len(vals)
    money = sum(1 for c in vals if V.parse_money(c) or re.match(r"^\(?[\$€£₹]", c.strip()))
    dates = sum(1 for c in vals if V.parse_dates(c))
    pct = sum(1 for c in vals if re.search(r"%\s*$", c.strip()))
    numeric = sum(1 for c in vals if _num(c) is not None and re.match(r"^[\(\-\+]?[\$€£₹]?\s*[\d,\.]+\)?\s*%?$", c.strip()))
    if money / n >= 0.6:
        return "money"
    if dates / n >= 0.6:
        return "date"
    if pct / n >= 0.6:
        return "percent"
    if numeric / n >= 0.7:
        return "number"
    return "text"


def profile_table(table: dict[str, Any]) -> dict[str, Any]:
    """Column types, numeric summaries, detected totals row and a reconciliation check."""
    headers, rows = table.get("headers") or [], table.get("rows") or []
    cols = []
    for j, h in enumerate(headers):
        cells = [r[j] if j < len(r) else "" for r in rows]
        t = infer_column_type(cells)
        col: dict[str, Any] = {"index": j, "header": h, "type": t}
        if t in ("money", "number", "percent"):
            nums = [n for n in (_num(c) for c in cells) if n is not None]
            if nums:
                col.update({"min": min(nums), "max": max(nums), "sum": round(sum(nums), 2), "count": len(nums)})
        cols.append(col)

    total_row = next((i for i, r in enumerate(rows) if r and _TOTAL_LABEL.match(r[0] or "") or any(_TOTAL_LABEL.match(c or "") for c in r[:2])), None)
    checks = []
    if total_row is not None:
        for j, c in enumerate(cols):
            if c["type"] not in ("money", "number"):
                continue
            body = [_num(r[j]) for i, r in enumerate(rows) if i != total_row and j < len(r)]
            body = [b for b in body if b is not None]
            claimed = _num(rows[total_row][j]) if j < len(rows[total_row]) else None
            if claimed is None or not body:
                continue
            calc = round(sum(body), 2)
            checks.append({"column": c["header"], "claimed_total": claimed, "calculated_sum": calc,
                           "consistent": V.money_close(calc, claimed, 0.01) or claimed < calc and False})
    return {"columns": cols, "total_row_index": total_row, "total_checks": checks,
            "n_rows": len(rows), "n_cols": len(headers)}


def cell_relationships(table: dict[str, Any], limit: int = 200) -> list[dict[str, str]]:
    """(row label, column header, value) triples — the 'cell relationships' of a table."""
    headers, rows = table.get("headers") or [], table.get("rows") or []
    out = []
    for r in rows:
        label = r[0] if r else ""
        for j, v in enumerate(r[1:], start=1):
            if v and j < len(headers):
                out.append({"row": label, "column": headers[j], "value": v})
                if len(out) >= limit:
                    return out
    return out
