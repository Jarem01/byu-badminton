"""Compute ranked pool standings for display and for knockout advancement."""

from __future__ import annotations

from dataclasses import asdict

from ..config import DEFAULT_SETTINGS
from ..model.entities import Bracket, Pool, Tournament
from .tiebreak import compute_stats, rank


def _pool_matches(bracket: Bracket, pool: Pool):
    return [m for m in bracket.matches.values() if m.pool_id == pool.id]


def pool_complete(bracket: Bracket, pool: Pool) -> bool:
    ms = _pool_matches(bracket, pool)
    playable = [m for m in ms if not m.is_bye()]
    return bool(playable) and all(m.result and m.result.winner for m in playable)


def pool_standings(t: Tournament, bracket: Bracket, pool: Pool,
                   order=None) -> list[dict]:
    order = order or DEFAULT_SETTINGS.tiebreak_order
    keys = [e.key() for e in pool.entry_refs]
    matches = _pool_matches(bracket, pool)
    seed_of = {s.entry.key(): s.seed_no for s in bracket.seeds}
    ranked = rank(keys, matches, seed_of, order)
    stats = compute_stats(set(keys), matches)
    ref_by_key = {e.key(): e for e in pool.entry_refs}
    rows = []
    for pos, k in enumerate(ranked, start=1):
        s = stats[k]
        rows.append({
            "rank": pos, "key": k, "label": t.entry_label(ref_by_key[k]),
            "played": s.played, "wins": s.match_wins, "losses": s.match_losses,
            "game_diff": s.game_diff, "point_diff": s.point_diff,
            "points_for": s.points_for, "points_against": s.points_against,
            "advances": pos <= pool.advance_count,
        })
    return rows


def all_standings(t: Tournament, bracket: Bracket, order=None) -> list[dict]:
    return [{"pool": p.label, "complete": pool_complete(bracket, p),
             "rows": pool_standings(t, bracket, p, order)}
            for p in bracket.pools]
