"""Deterministic hashing for editorial packages.

Canonical JSON (sorted keys, compact separators, UTF-8) hashed with
sha256. Same logical package always yields the same hash on every
machine — the fact-check report pins this hash so a report can never be
silently applied to a different research package.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, default=str)


def sha256_hex(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def package_hash(payload: dict[str, Any]) -> str:
    """Hash a research package payload (callers exclude package_hash itself)."""
    return sha256_hex(canonical_json(payload))
