"""Tolerant JSON extraction for model output.

Local models wrap JSON in prose or code fences often enough that a strict
``json.loads`` turns a usable proposal into a failed episode. These helpers
recover the first object/array without guessing at meaning; the caller still
validates every field.
"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)


def loads_loose(text: str) -> Any:
    text = (text or "").strip()
    if not text:
        return None
    candidates: list[str] = []
    if text:
        candidates.append(text)
    fenced = _FENCE.findall(text)
    candidates.extend(block.strip() for block in fenced)
    for start, end in (("{", "}"), ("[", "]")):
        first = text.find(start)
        last = text.rfind(end)
        if first >= 0 and last > first:
            candidates.append(text[first : last + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except (TypeError, ValueError):
            continue
    return None


def as_object(text: str) -> dict[str, Any] | None:
    value = loads_loose(text)
    return value if isinstance(value, dict) else None


def as_array(text: str) -> list[Any] | None:
    value = loads_loose(text)
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("candidates", "items", "steps"):
            if isinstance(value.get(key), list):
                return value[key]
    return None
