"""Utility helpers shared across GOES Manager modules."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

_DURATION_PATTERN = re.compile(r"(?P<value>\d+)(?P<unit>[smhdw])", re.IGNORECASE)

_UNIT_SECONDS = {
    "s": 1,
    "m": 60,
    "h": 60 * 60,
    "d": 24 * 60 * 60,
    "w": 7 * 24 * 60 * 60,
}


def parse_duration_to_seconds(value: str) -> int:
    """Translate a compact duration string like ``"7d6h"`` into seconds."""
    if not value:
        raise ValueError("Duration value is empty")

    total_seconds = 0
    position = 0
    for match in _DURATION_PATTERN.finditer(value):
        if match.start() != position:
            raise ValueError(f"Invalid duration token in '{value}' at index {position}")
        position = match.end()
        amount = int(match.group("value"))
        unit = match.group("unit").lower()
        multiplier = _UNIT_SECONDS[unit]
        total_seconds += amount * multiplier

    if position != len(value):
        raise ValueError(f"Could not parse full duration string '{value}'")

    if total_seconds <= 0:
        raise ValueError("Duration must be greater than zero seconds")

    return total_seconds


def ensure_directory(path: Path) -> None:
    """Create a directory hierarchy if it does not already exist."""
    path.mkdir(parents=True, exist_ok=True)


@dataclass
class JsonWriter:
    """Simple helper to append JSON lines efficiently."""

    path: Path

    def append_many(self, records: Iterable[Dict[str, Any]]) -> int:
        count = 0
        if not records:
            return count

        ensure_directory(self.path.parent)
        with self.path.open("a", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, sort_keys=True))
                handle.write("\n")
                count += 1
        return count


def utc_now() -> datetime:
    """Return the current UTC timestamp with timezone information."""
    return datetime.now(timezone.utc)


def posix_path(path: Path) -> str:
    """Return a POSIX-style string for a path."""
    return path.as_posix()


def resolve_path(base: Path, candidate: str | Path) -> Path:
    """Resolve a possibly relative path using ``base`` when necessary."""
    candidate_path = Path(candidate)
    if candidate_path.is_absolute():
        return candidate_path
    return (base / candidate_path).resolve()


def load_state(path: Path) -> Dict[str, Any]:
    """Load JSON state from disk if it exists, otherwise return an empty mapping."""
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError:
        logging.warning("Could not parse state file %s, resetting state", path)
        return {}


def save_state(path: Path, payload: Dict[str, Any]) -> None:
    """Persist JSON state to disk."""
    ensure_directory(path.parent)
    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    tmp_path.replace(path)
