"""Round-robin generation via the circle (rotation) method.

Every entrant plays every other once: n*(n-1)/2 matches over n-1 rounds (a dummy
is added for odd counts so exactly one entrant rests each round). Used directly
as a single-pool format and as the pool stage of group_knockout.
"""

from __future__ import annotations

from ..model.entities import Bracket, Division, EntryRef, Match, Pool, Round, Seed


def circle_rounds(entries: list[EntryRef]) -> list[list[tuple[EntryRef, EntryRef]]]:
    arr: list[EntryRef | None] = list(entries)
    if len(arr) % 2:
        arr.append(None)  # dummy => the paired entrant gets a bye that round
    n = len(arr)
    rounds = []
    for _ in range(max(n - 1, 0)):
        pairs = []
        for i in range(n // 2):
            a, b = arr[i], arr[n - 1 - i]
            if a is not None and b is not None:
                pairs.append((a, b))
        rounds.append(pairs)
        arr = [arr[0]] + [arr[-1]] + arr[1:-1]  # fix first, rotate the rest
    return rounds


def build_pool_matches(division_id: str, pool_id: str, label: str,
                       entries: list[EntryRef], seq_start: int
                       ) -> tuple[list[Match], list[Round], int]:
    matches: list[Match] = []
    rounds: list[Round] = []
    seq = seq_start
    for r, pairs in enumerate(circle_rounds(entries), start=1):
        ids = []
        for j, (a, b) in enumerate(pairs):
            mid = f"{division_id}-pool{label}-r{r}-m{j}"
            matches.append(Match(id=mid, division_id=division_id,
                                 round_name=f"Pool {label} · Round {r}",
                                 bracket_part="pool", side1=a, side2=b,
                                 pool_id=pool_id, seq=seq))
            ids.append(mid)
            seq += 1
        if ids:
            rounds.append(Round(name=f"Pool {label} · Round {r}",
                                match_ids=ids, bracket_part="pool"))
    return matches, rounds, seq


def generate(division: Division, seeds: list[Seed],
             rng_seed: int | None = None) -> Bracket:
    entries = [s.entry for s in seeds]
    br = Bracket(division_id=division.id, format="round_robin",
                 rng_seed=rng_seed, seeds=list(seeds))
    if len(entries) < 2:
        return br
    pool_id = f"{division.id}-pool-A"
    pool = Pool(id=pool_id, label="A", entry_refs=list(entries),
                advance_count=len(entries))
    br.pools.append(pool)
    matches, rounds, _ = build_pool_matches(division.id, pool_id, "A", entries, 0)
    for m in matches:
        br.matches[m.id] = m
    br.rounds = rounds
    return br
