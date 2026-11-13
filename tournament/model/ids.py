"""Stable, human-readable ID generation (no external uuid dependency).

IDs are slugs derived from a name plus a numeric suffix on collision, e.g.
``player-nicholas-chin`` or ``player-nicholas-chin-2``. Deterministic given the
same insertion order, which keeps saved tournaments diffable and reproducible.
"""

from __future__ import annotations

import re

_slug_strip = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """Lowercase, ASCII-ish slug. Empty input yields ``x``."""
    s = _slug_strip.sub("-", text.strip().lower()).strip("-")
    return s or "x"


class IdFactory:
    """Hands out unique IDs of the form ``<prefix>-<slug>`` with a numeric
    suffix appended only when needed to avoid collisions."""

    def __init__(self) -> None:
        self._used: set[str] = set()

    def make(self, prefix: str, *parts: str) -> str:
        base = f"{prefix}-{slugify('-'.join(p for p in parts if p))}"
        candidate = base
        n = 2
        while candidate in self._used:
            candidate = f"{base}-{n}"
            n += 1
        self._used.add(candidate)
        return candidate

    def reserve(self, existing_id: str) -> None:
        """Register an ID that was loaded from disk so new IDs won't clash."""
        self._used.add(existing_id)
