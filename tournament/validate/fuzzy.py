"""Fuzzy resolution of a free-text name to a roster player id (stdlib difflib).

Confidence tiers (caller decides what to auto-apply vs. flag):
- 1.00  exact full-name match
- 0.95  unambiguous single first-name match ("Jarem" -> "Jarem Miller")
- ratio close match above cutoff (typo, e.g. "Sunny uou" -> "Sunny You")
- None  no confident match -> raise a validation issue for a human
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass

from ..model.entities import Player
from ..ingest.normalize import name_key

AUTO_THRESHOLD = 0.86   # >= this: resolve automatically
# >= this (but < auto): suggest "did you mean"; below it, treat as a genuinely
# unregistered person and create a placeholder. Set high enough that weak
# coincidental overlaps (e.g. "Kaitong Li" vs "Simon Li" ~0.67) don't produce
# misleading suggestions.
SUGGEST_CUTOFF = 0.74


@dataclass(slots=True)
class Resolution:
    player_id: str | None
    confidence: float
    suggestion: str | None = None   # suggested full name when not auto-resolved
    ambiguous: bool = False


class NameResolver:
    def __init__(self, players: dict[str, Player]) -> None:
        self.players = players
        self._by_full: dict[str, str] = {}
        self._first_index: dict[str, list[str]] = {}
        for pid, p in players.items():
            self._by_full[name_key(p.full)] = pid
            self._first_index.setdefault(name_key(p.first), []).append(pid)
        self._all_keys = list(self._by_full.keys())

    def resolve(self, raw_name: str) -> Resolution:
        key = name_key(raw_name)
        if not key:
            return Resolution(None, 0.0)

        # 1. Exact full-name match.
        if key in self._by_full:
            return Resolution(self._by_full[key], 1.0)

        # 2. Single-token -> unambiguous first name.
        if " " not in key:
            hits = self._first_index.get(key, [])
            if len(hits) == 1:
                return Resolution(hits[0], 0.95)
            if len(hits) > 1:
                return Resolution(None, 0.5, ambiguous=True,
                                  suggestion=self.players[hits[0]].full)

        # 3. Close match on full name (typos).
        best = difflib.get_close_matches(key, self._all_keys, n=1,
                                         cutoff=SUGGEST_CUTOFF)
        if best:
            ratio = difflib.SequenceMatcher(None, key, best[0]).ratio()
            pid = self._by_full[best[0]]
            if ratio >= AUTO_THRESHOLD:
                return Resolution(pid, round(ratio, 3))
            return Resolution(None, round(ratio, 3),
                              suggestion=self.players[pid].full)

        return Resolution(None, 0.0)
