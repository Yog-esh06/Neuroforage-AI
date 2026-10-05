from __future__ import annotations

import hashlib
import json
from typing import Any


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stable_json(obj: Any) -> str:
    """Deterministic JSON used for hash chains (sorted keys, no whitespace, ISO dates)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


def sha256_json(obj: Any) -> str:
    return sha256_bytes(stable_json(obj).encode("utf-8"))
