"""Workflow condition language.

A condition is either a leaf {"field": "insight.severity_score", "op": ">=", "value": 0.7} or a group
{"all": [...]} / {"any": [...]} (nestable). Evaluation returns a trace so every decision is explainable.
"""
from __future__ import annotations

from typing import Any

from app.core.exceptions import ValidationFailed

OPS = {">", ">=", "<", "<=", "==", "!=", "in", "not_in", "contains", "exists"}

FIELDS: dict[str, dict[str, Any]] = {
    "insight.severity": {"type": "enum", "values": ["low", "medium", "high", "critical"]},
    "insight.severity_score": {"type": "number"}, "insight.confidence": {"type": "number"},
    "insight.category": {"type": "string"}, "insight.kind": {"type": "string"}, "insight.title": {"type": "string"},
    "insight.evidence_count": {"type": "number"},
    "contradiction.confidence": {"type": "number"}, "contradiction.topic": {"type": "string"}, "contradiction.kind": {"type": "string"},
    "document.type": {"type": "string"}, "document.type_confidence": {"type": "number"}, "document.ocr_used": {"type": "bool"},
    "document.page_count": {"type": "number"}, "document.name": {"type": "string"},
    "document.high_risk_count": {"type": "number"}, "document.max_severity_score": {"type": "number"},
    "document.contradiction_count": {"type": "number"},
}
TRIGGERS = {"document_ready", "insight_created", "contradiction_detected", "manual"}
TRIGGER_FIELDS = {
    "insight_created": ("insight.", "document."), "contradiction_detected": ("contradiction.", "document."),
    "document_ready": ("document.",), "manual": ("insight.", "contradiction.", "document."),
}


def _get(ctx: dict[str, Any], path: str) -> Any:
    cur: Any = ctx
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _cmp(actual: Any, op: str, expected: Any) -> bool:
    if op == "exists":
        return (actual is not None) == bool(expected if expected is not None else True)
    if actual is None:
        return op in ("!=", "not_in")
    try:
        if op == ">":
            return actual > expected
        if op == ">=":
            return actual >= expected
        if op == "<":
            return actual < expected
        if op == "<=":
            return actual <= expected
    except TypeError:
        return False
    if op == "==":
        return str(actual).lower() == str(expected).lower() if isinstance(actual, str) else actual == expected
    if op == "!=":
        return not _cmp(actual, "==", expected)
    if op == "in":
        return str(actual).lower() in [str(x).lower() for x in expected]
    if op == "not_in":
        return str(actual).lower() not in [str(x).lower() for x in expected]
    if op == "contains":
        return str(expected).lower() in str(actual).lower()
    return False


def evaluate(cond: dict[str, Any] | None, ctx: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    trace: list[dict[str, Any]] = []
    if not cond:
        return True, [{"note": "no conditions: always matches"}]

    def walk(node: dict[str, Any]) -> bool:
        if "all" in node:
            return all([walk(c) for c in node["all"]])
        if "any" in node:
            return any([walk(c) for c in node["any"]])
        actual = _get(ctx, node["field"])
        ok = _cmp(actual, node["op"], node.get("value"))
        trace.append({"field": node["field"], "op": node["op"], "expected": node.get("value"), "actual": actual, "passed": ok})
        return ok

    return walk(cond), trace


def validate_conditions(cond: dict[str, Any] | None, trigger: str) -> None:
    if not cond:
        return
    allowed = TRIGGER_FIELDS.get(trigger, ())

    def walk(node: Any, depth: int = 0) -> None:
        if depth > 5 or not isinstance(node, dict):
            raise ValidationFailed("Invalid condition structure")
        if "all" in node or "any" in node:
            kids = node.get("all", node.get("any"))
            if not isinstance(kids, list) or not kids:
                raise ValidationFailed("'all'/'any' must be a non-empty list")
            for k in kids:
                walk(k, depth + 1)
            return
        f, op = node.get("field"), node.get("op")
        if f not in FIELDS:
            raise ValidationFailed(f"Unknown condition field '{f}'", details={"allowed": sorted(FIELDS)})
        if not f.startswith(allowed):
            raise ValidationFailed(f"Field '{f}' is not available for trigger '{trigger}'")
        if op not in OPS:
            raise ValidationFailed(f"Unknown operator '{op}'", details={"allowed": sorted(OPS)})
        spec = FIELDS[f]
        if op in (">", ">=", "<", "<=") and spec["type"] != "number":
            raise ValidationFailed(f"Operator '{op}' only applies to numeric fields; '{f}' is {spec['type']}")
        if op not in ("exists",):
            val = node.get("value")
            if op in ("in", "not_in") and not isinstance(val, list):
                raise ValidationFailed(f"Operator '{op}' needs a list value")
            if spec["type"] == "number" and op not in ("in", "not_in") and not isinstance(val, (int, float)):
                raise ValidationFailed(f"Field '{f}' needs a numeric value")
            if spec["type"] == "enum" and op in ("==", "!=") and str(val).lower() not in spec["values"]:
                raise ValidationFailed(f"Field '{f}' must be one of {spec['values']}")

    walk(cond)
