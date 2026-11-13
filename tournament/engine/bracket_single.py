"""Single-elimination bracket generation.

Seeds are placed by the standard bracket order so top seeds are separated and
byes fall to the top seeds. First-round byes auto-advance on creation.
"""

from __future__ import annotations

from ..model.entities import Bracket, Division, Match, Round, Seed
from .advancement import resolve_byes
from .seeding import place_seeds_in_slots


def round_name(match_count: int) -> str:
    entrants = match_count * 2
    return {1: "Final", 2: "Semifinal", 4: "Quarterfinal"}.get(
        match_count, f"Round of {entrants}")


def generate(division: Division, seeds: list[Seed],
             rng_seed: int | None = None, resolve_byes_now: bool = True) -> Bracket:
    br = Bracket(division_id=division.id, format="single_elim",
                 rng_seed=rng_seed, seeds=list(seeds))
    slots, size = place_seeds_in_slots(seeds)
    if size < 2:
        return br  # 0 or 1 entrant: nothing to play (sole entry is champion)

    seq = 0
    prev_ids: list[str] = []
    current = slots  # round 0 pulls real entrants from the seeded slots
    r = 0
    while len(current) > 1:
        m_count = len(current) // 2
        rnd = Round(name=round_name(m_count), bracket_part="main")
        round_matches: list[Match] = []
        for j in range(m_count):
            mid = f"{division.id}-r{r}-m{j}"
            m = Match(id=mid, division_id=division.id, round_name=rnd.name,
                      bracket_part="main", seq=seq)
            if r == 0:
                m.side1 = current[2 * j]
                m.side2 = current[2 * j + 1]
            br.matches[mid] = m
            rnd.match_ids.append(mid)
            round_matches.append(m)
            seq += 1
        if r > 0:
            for j, pid in enumerate(prev_ids):
                pm = br.matches[pid]
                pm.next_win_match = round_matches[j // 2].id
                pm.next_win_slot = 1 if j % 2 == 0 else 2
        br.rounds.append(rnd)
        prev_ids = [m.id for m in round_matches]
        current = [None] * m_count
        r += 1

    if resolve_byes_now:
        resolve_byes(br)
    return br
