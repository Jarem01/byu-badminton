"""Seeding engine.

- ``standard_bracket_order(size)`` -> seed numbers in bracket-slot order such
  that top seeds land in separate halves/quarters (1 & 2 can't meet before the
  final, top 4 not before the semis).
- ``place_seeds_in_slots(seeds)`` -> entrants (or None = bye) per slot, with
  byes falling to the top seeds automatically.
- ``seed_entries(...)`` -> a Seed list by manual / ranking / random(seeded)
  method. Random seeding is reproducible from a saved integer seed.

References: BWF Statutes 5.1 (seed placement, byes = next_pow2 - entries).
"""

from __future__ import annotations

import random
from typing import Callable

from ..model.entities import Division, EntryRef, Seed, Tournament


def next_power_of_two(n: int) -> int:
    if n <= 1:
        return 1
    return 1 << (n - 1).bit_length()


def standard_bracket_order(size: int) -> list[int]:
    """Seed numbers (1..size) in slot order for a power-of-two draw."""
    if size < 1 or (size & (size - 1)) != 0:
        raise ValueError("size must be a power of two")
    order = [1]
    while len(order) < size:
        m = len(order) * 2
        order = [x for s in order for x in (s, m + 1 - s)]
    return order


def num_byes(entry_count: int) -> int:
    return next_power_of_two(entry_count) - entry_count


def place_seeds_in_slots(seeds: list[Seed]) -> tuple[list[EntryRef | None], int]:
    """Map ordered seeds onto bracket slots. Returns (slots, bracket_size).

    Slots holding a seed number greater than the entry count are ``None`` =
    byes, which -- by the standard order -- fall to the top seeds.
    """
    n = len(seeds)
    size = next_power_of_two(n)
    by_no = {s.seed_no: s.entry for s in seeds}
    order = standard_bracket_order(size)
    slots = [by_no.get(seed_num) for seed_num in order]
    return slots, size


def entry_strength(t: Tournament, ref: EntryRef) -> float:
    """Higher = stronger. Average of known skills; unknown counts as 0."""
    if ref.kind == "player":
        p = t.players.get(ref.ref_id)
        return float(p.skill) if p and p.skill is not None else 0.0
    if ref.kind == "team":
        team = t.teams.get(ref.ref_id)
        if not team:
            return 0.0
        skills = [t.players[pid].skill for pid in team.player_ids
                  if pid in t.players and t.players[pid].skill is not None]
        return sum(skills) / len(skills) if skills else 0.0
    pair = t.pairs.get(ref.ref_id)
    if not pair:
        return 0.0
    skills = [t.players[pid].skill for pid in pair.player_ids
              if pid in t.players and t.players[pid].skill is not None]
    return sum(skills) / len(skills) if skills else 0.0


def _entry_label(t: Tournament, ref: EntryRef) -> str:
    return t.entry_label(ref)


def seed_entries(t: Tournament, division: Division, method: str = "ranking",
                 rng_seed: int | None = None,
                 manual_order: list[str] | None = None) -> list[Seed]:
    """Produce a Seed list (seed_no 1..n) for a division's entries."""
    entries = list(division.entry_refs)

    # Team divisions seed by team number (entry order = Team 1, Team 2, ...), so
    # Team 1 is the top seed and shows first in the draw. Teams are already
    # rating-balanced, so rating-seeding adds little.
    if getattr(division, "team_format", None):
        return [Seed(entry=e, seed_no=i + 1, method="manual")
                for i, e in enumerate(entries)]

    if method == "manual":
        if manual_order is None:
            raise ValueError("manual seeding requires manual_order (entry keys)")
        index = {e.key(): e for e in entries}
        missing = [k for k in manual_order if k not in index]
        if missing or len(manual_order) != len(entries):
            raise ValueError("manual_order must list every entry exactly once")
        ordered = [index[k] for k in manual_order]
    elif method == "random":
        rng = random.Random(rng_seed)
        ordered = entries[:]
        rng.shuffle(ordered)
    elif method == "ranking":
        # Strongest first; deterministic tiebreak by label so equal skills are
        # reproducible (never a live coin flip).
        ordered = sorted(entries,
                         key=lambda e: (-entry_strength(t, e), _entry_label(t, e)))
    else:
        raise ValueError(f"Unknown seeding method {method!r}")

    return [Seed(entry=e, seed_no=i + 1, method=method)
            for i, e in enumerate(ordered)]
