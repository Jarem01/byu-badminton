"""Group-standings statistics and a configurable, BWF-aligned tie-break chain.

Ties are broken by the ordered criteria in Settings.tiebreak_order. When players
are tied on matches won, secondary criteria are recomputed *among the tied
players only* (the BWF "matches between those tied" rule), which makes
head-to-head and game/point ratios behave correctly for 2-way and 3+-way ties.
The final fallback is seeded position, so results are always deterministic and
reproducible (never a live coin flip).

Reference: BWF General Competition Regulations, tie-break procedure.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import DEFAULT_SETTINGS
from ..model.entities import EntryRef, Match


@dataclass(slots=True)
class Stat:
    played: int = 0
    match_wins: int = 0
    match_losses: int = 0
    games_won: int = 0
    games_lost: int = 0
    points_for: int = 0
    points_against: int = 0

    @property
    def game_diff(self) -> int:
        return self.games_won - self.games_lost

    @property
    def point_diff(self) -> int:
        return self.points_for - self.points_against


def compute_stats(entry_keys: set[str], matches: list[Match]) -> dict[str, Stat]:
    """Stats for the given entries over the subset of matches played strictly
    between members of ``entry_keys``."""
    stats = {k: Stat() for k in entry_keys}
    for m in matches:
        if not m.result or m.result.winner is None:
            continue
        if m.side1 is None or m.side2 is None:
            continue
        k1, k2 = m.side1.key(), m.side2.key()
        if k1 not in entry_keys or k2 not in entry_keys:
            continue
        g1 = sum(1 for g in m.result.games if len(g) == 2 and g[0] > g[1])
        g2 = sum(1 for g in m.result.games if len(g) == 2 and g[1] > g[0])
        p1 = sum(g[0] for g in m.result.games if len(g) == 2)
        p2 = sum(g[1] for g in m.result.games if len(g) == 2)
        for k, gw, gl, pf, pa in ((k1, g1, g2, p1, p2), (k2, g2, g1, p2, p1)):
            s = stats[k]
            s.played += 1
            s.games_won += gw
            s.games_lost += gl
            s.points_for += pf
            s.points_against += pa
        winner_key = m.result.winner.key()
        stats[winner_key].match_wins += 1
        stats[k2 if winner_key == k1 else k1].match_losses += 1
    return stats


def _value(key: str, crit: str, group_stats: dict[str, Stat],
           overall: dict[str, Stat], seed_of: dict[str, int]) -> float:
    """Higher is better. 'match_wins' uses overall; the tie-break criteria use
    the intra-group stats; 'seed' is the deterministic final fallback."""
    if crit == "match_wins":
        return overall[key].match_wins
    if crit == "head_to_head":
        return group_stats[key].match_wins
    if crit == "game_diff":
        return group_stats[key].game_diff
    if crit == "point_diff":
        return group_stats[key].point_diff
    if crit == "points_for":
        return group_stats[key].points_for
    if crit == "seed":
        return -seed_of.get(key, 9999)
    return 0.0


def rank(entry_keys: list[str], matches: list[Match],
         seed_of: dict[str, int] | None = None,
         order: tuple[str, ...] | None = None) -> list[str]:
    """Return entry keys ranked best-first."""
    order = order or DEFAULT_SETTINGS.tiebreak_order
    seed_of = seed_of or {}
    overall = compute_stats(set(entry_keys), matches)

    def resolve(group: list[str], crits: tuple[str, ...]) -> list[str]:
        if len(group) <= 1:
            return group
        if not crits:
            # Deterministic final fallback: seed, then key.
            return sorted(group, key=lambda k: (seed_of.get(k, 9999), k))
        crit, rest = crits[0], crits[1:]
        gstats = compute_stats(set(group), matches)
        buckets: dict[float, list[str]] = {}
        for k in group:
            v = _value(k, crit, gstats, overall, seed_of)
            buckets.setdefault(v, []).append(k)
        out: list[str] = []
        for v in sorted(buckets, reverse=True):
            out.extend(resolve(buckets[v], rest))
        return out

    return resolve(list(entry_keys), tuple(order))
