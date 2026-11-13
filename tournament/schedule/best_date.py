"""Best-date helper: rank candidate dates by how many players are available.

Single-day tournaments: availability from the form is advisory only -- it helps
pick the date that works for the most people, it is not a per-match constraint.
"""

from __future__ import annotations

from collections import Counter

from ..model.entities import Tournament


def _rank(counter: Counter, total: int) -> list[dict]:
    return [{"option": opt, "available": n, "total": total,
             "pct": round(100 * n / total) if total else 0}
            for opt, n in counter.most_common()]


def availability_report(t: Tournament) -> dict:
    active = [p for p in t.players.values() if not p.is_stub and not p.withdrawn]
    total = len(active)
    weekend = Counter()
    weekday = Counter()
    for p in active:
        for opt in p.weekend_avail:
            weekend[opt] += 1
        for opt in p.weekday_avail:
            weekday[opt] += 1
    return {"total_players": total,
            "weekends": _rank(weekend, total),
            "weekdays": _rank(weekday, total)}
