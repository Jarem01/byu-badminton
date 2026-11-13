"""Group (pool) play followed by a clean power-of-two knockout.

Entrants are distributed into balanced pools by serpentine (snake) seeding so
pool strength is even. Each pool is a round robin. The knockout is always a
**clean power of two with no byes**; we fill it entirely with real teams:

  * ``base`` finishers per pool qualify automatically (top 1 or top 2 -- the
    largest that fits the draw, capped at 2): ``base = min(2, draw // pools)``.
  * the remaining ``draw - base*pools`` slots ("wildcards") go to the
    highest-ranked non-qualifiers across *all* pools, ranked by per-match
    ratios (wins, game diff, point diff) so unequal pools compare fairly.

The draw size is the largest power of two the field can fill with real teams
(``largest_pow2_le(n)``), or a smaller power of two the organizer picks; either
way there are never any byes. Base (pool-position) slots populate as each pool
finishes; wildcard slots need every pool complete (they rank across pools), so
they fill once the whole group stage is done.
"""

from __future__ import annotations

from ..model.entities import (
    Bracket, Division, EntryRef, Pool, Seed,
)
from . import bracket_single
from .standings import pool_complete, pool_standings


def _serpentine(entries: list[EntryRef], num_groups: int) -> list[list[EntryRef]]:
    groups: list[list[EntryRef]] = [[] for _ in range(num_groups)]
    for i, e in enumerate(entries):
        rnd, pos = divmod(i, num_groups)
        g = pos if rnd % 2 == 0 else (num_groups - 1 - pos)
        groups[g].append(e)
    return groups


def choose_num_groups(n: int) -> int:
    return 2 if n <= 10 else 4


def largest_pow2_le(n: int) -> int:
    """Largest power of two <= n (the natural clean main-draw size)."""
    p = 1
    while p * 2 <= n:
        p *= 2
    return p


def resolve_group_plan(n: int, num_groups: int | None = None,
                       main_draw: int | None = None):
    """Resolve (pools, draw, base, wildcards) for a field of ``n`` entrants.

    ``draw`` is snapped to a power of two and clamped so it never exceeds the
    number of real teams (no byes). ``base`` is the guaranteed finishers per
    pool (top 1 or 2, the largest that fits) and ``wildcards`` is the number of
    extra slots filled by the best remaining teams across pools."""
    g = num_groups or choose_num_groups(n)
    g = max(1, min(g, n))
    cap = largest_pow2_le(n)                 # most real teams a clean draw holds
    m = main_draw or cap
    m = largest_pow2_le(m) if m >= 2 else 2  # snap to a power of two
    m = max(2, min(m, cap))
    base = min(2, m // g)                    # top 1 or top 2 per pool
    wildcards = m - base * g                 # filled by best-remaining
    return g, m, base, wildcards


def choose_groups_for_main_draw(n: int, main_draw: int):
    """Legacy helper: pick (num_groups, advance) so num_groups*advance ==
    main_draw with balanced (~4 each) pools. Returns None if the field already
    fills the draw. Retained for reference/tests; live planning uses
    :func:`resolve_group_plan` (which allows wildcard fill, so the qualifier
    count need not divide the draw)."""
    import math
    best = None
    for g in range(1, main_draw + 1):
        if main_draw % g or g > n:
            continue
        advance = main_draw // g
        pool = math.ceil(n / g)
        if advance >= pool:            # everyone in the pool advances -> pointless
            continue
        score = (abs(pool - 4), -g)    # prefer ~4 per pool, then more/smaller pools
        if best is None or score < best[0]:
            best = (score, g, advance)
    return (best[1], best[2]) if best else None


def generate(division: Division, seeds: list[Seed], rng_seed: int | None = None,
             num_groups: int | None = None, main_draw: int | None = None) -> Bracket:
    entries = [s.entry for s in seeds]
    br = Bracket(division_id=division.id, format="group_knockout",
                 rng_seed=rng_seed, seeds=list(seeds))
    if len(entries) < 2:
        return br

    g, m, base, wildcards = resolve_group_plan(len(entries), num_groups, main_draw)

    groups = _serpentine(entries, g)
    seq = 0
    from .bracket_rr import build_pool_matches
    for gi, gentries in enumerate(groups):
        label = chr(65 + gi)
        pool_id = f"{division.id}-pool-{label}"
        br.pools.append(Pool(id=pool_id, label=label,
                             entry_refs=list(gentries), advance_count=base))
        matches, rounds, seq = build_pool_matches(division.id, pool_id, label,
                                                  gentries, seq)
        for mm in matches:
            br.matches[mm.id] = mm
        br.rounds.extend(rounds)

    # Knockout over placeholder slots: rank-major pool qualifiers (all #1s, then
    # #2s) as the top seeds, then wildcards (W#1..) as the lowest seeds. There
    # are exactly ``m`` placeholders and ``m`` is a power of two -> no byes.
    placeholders = [EntryRef("slot", f"{chr(65 + gi)}#{r + 1}")
                    for r in range(base) for gi in range(g)]
    placeholders += [EntryRef("slot", f"W#{w + 1}") for w in range(wildcards)]
    ko_seeds = [Seed(entry=ph, seed_no=i + 1) for i, ph in enumerate(placeholders)]
    ko = bracket_single.generate(division, ko_seeds, resolve_byes_now=False)
    for mid, mm in ko.matches.items():
        br.matches[mid] = mm
    br.rounds.extend(ko.rounds)

    # Record which first-round knockout slot each qualifier feeds. Pool-position
    # slots carry (label, rank); wildcard slots carry ("W", ordinal).
    first_ko = next((r for r in ko.rounds if r.bracket_part == "main"), None)
    if first_ko:
        for mid in first_ko.match_ids:
            mm = br.matches[mid]
            for slot, side in ((1, mm.side1), (2, mm.side2)):
                if side and side.kind == "slot":
                    label, _, ordinal = side.ref_id.partition("#")
                    br.ko_plan.append([mid, slot, label, int(ordinal)])
    return br


def _wildcard_order(t, bracket: Bracket, base: int) -> list[str]:
    """Best-first entry keys among teams that did NOT finish in their pool's top
    ``base`` -- ranked across pools by per-match ratios (fair for unequal pool
    sizes), with seed order as the final deterministic tiebreak."""
    seed_of = {s.entry.key(): s.seed_no for s in bracket.seeds}
    cands = []
    for p in bracket.pools:
        for r in pool_standings(t, bracket, p):
            if r["rank"] > base:
                played = r["played"] or 1
                cands.append((r["wins"] / played, r["game_diff"] / played,
                              r["point_diff"] / played,
                              seed_of.get(r["key"], 9999), r["key"]))
    cands.sort(key=lambda c: (-c[0], -c[1], -c[2], c[3]))
    return [c[4] for c in cands]


def project_qualifiers(t, bracket: Bracket) -> dict[str, str]:
    """Map entry key -> "auto" (guaranteed pool-position qualifier) or
    "wildcard" (currently projected to fill a wildcard slot), based on the
    standings *as they stand right now*. Recomputed on every score report, so
    the projection shifts live as pools progress. Teams not shown are outside
    the projected cut. Wildcards are provisional until every pool completes."""
    if not bracket.pools or not bracket.ko_plan:
        return {}
    base = max((rank for _, _, label, rank in bracket.ko_plan if label != "W"),
               default=0)
    n_wild = sum(1 for _, _, label, _ in bracket.ko_plan if label == "W")
    cls: dict[str, str] = {}
    for p in bracket.pools:
        for r in pool_standings(t, bracket, p):
            if r["rank"] <= base:
                cls[r["key"]] = "auto"
    for key in _wildcard_order(t, bracket, base)[:n_wild]:
        cls[key] = "wildcard"
    return cls


def fill_knockout_from_pools(t, bracket: Bracket) -> bool:
    """Populate the knockout draw from the pools. Pool-position (base) slots
    fill per pool as each finishes; wildcard slots fill once *every* pool is
    complete (they need a cross-pool ranking). Idempotent: a completed pool's
    finishers fill their slots and an incomplete pool's slots revert to
    placeholders, provided that knockout match hasn't been played yet."""
    if not bracket.pools or not bracket.ko_plan:
        return False
    pools = {p.label: p for p in bracket.pools}
    ref_by_key = {e.key(): e for p in bracket.pools for e in p.entry_refs}
    base = max((rank for _, _, label, rank in bracket.ko_plan if label != "W"),
               default=0)
    changed = False

    def put(m, slot, target):
        nonlocal changed
        cur = m.side1 if slot == 1 else m.side2
        if cur != target:
            setattr(m, "side1" if slot == 1 else "side2", target)
            changed = True

    # 1) Pool-position slots -- per pool, as each finishes.
    for mid, slot, label, rank in bracket.ko_plan:
        if label == "W":
            continue
        m = bracket.matches.get(mid)
        if m is None or (m.result and m.result.winner):
            continue                       # don't disturb a played knockout match
        pool = pools.get(label)
        if pool and pool_complete(bracket, pool):
            rows = pool_standings(t, bracket, pool)
            key = next((r["key"] for r in rows if r["rank"] == rank), None)
            put(m, slot, ref_by_key.get(key) if key else None)
        else:
            put(m, slot, EntryRef("slot", f"{label}#{rank}"))

    # 2) Wildcard slots -- need every pool complete to rank across pools.
    wilds = [(mid, slot, w) for mid, slot, label, w in bracket.ko_plan
             if label == "W"]
    if wilds:
        all_done = all(pool_complete(bracket, p) for p in bracket.pools)
        order = _wildcard_order(t, bracket, base) if all_done else []
        for mid, slot, w in wilds:
            m = bracket.matches.get(mid)
            if m is None or (m.result and m.result.winner):
                continue
            if all_done and w <= len(order):
                put(m, slot, ref_by_key.get(order[w - 1]))
            else:
                put(m, slot, EntryRef("slot", f"W#{w}"))
    return changed
