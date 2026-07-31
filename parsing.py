"""Parsing and normalization helpers for the deterministic triage engine."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime
from typing import Any


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[dict[str, Any]]:
    return [item if isinstance(item, dict) else {} for item in value] if isinstance(value, list) else []


def parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def parse_date(value: Any) -> date | None:
    parsed = parse_datetime(value)
    return parsed.date() if parsed is not None else None


def number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def format_number(value: Any) -> str:
    parsed = number(value)
    if parsed is None:
        return str(value)
    return str(int(parsed)) if parsed.is_integer() else str(parsed)


def normalized_text(value: Any) -> str:
    return " ".join(str(value or "").lower().replace("_", " ").split())


def excerpt(value: Any, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
