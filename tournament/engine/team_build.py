"""Build teams from registered ENTRIES (entry-based dual-meet model).

An entry is a registration kept intact: a doubles pair (one entry) or a single
(one entry), tagged with its event. Teams are bags of entries; a player's
entries are always kept on the same team (co-location); nobody is dropped. The
builder balances the number of entries per event across teams first (so ties
have matching opponents), then average skill. A per-team x per-event grid + a
gaps list show where entries are missing so the organizer can fill them later.
"""

from __future__ import annotations

import random as _random
from collections import defaultdict

from ..model.entities import EntryRef, Player, Team
from .seeding import entry_strength

ALL_EVENTS = ("MS", "WS", "MD", "WD", "XD")
# Distinct, readable team colors (cycled); shown across rosters/ties/board.
TEAM_COLORS = ["#0047BA", "#E08A00", "#1E8E3E", "#7B3FA0", "#0E7C86",
               "#C0392B", "#B8860B", "#2E5A88", "#AD1457", "#5D6D7E"]
# Events a team type may include (used to gate the entry pool + default events).
TYPE_EVENTS = {
    "mens": ["MS", "MD"],
    "womens": ["WS", "WD"],
    "mixed": ["MS", "WS", "MD", "WD", "XD"],
    "open": ["MS", "WS", "MD", "WD", "XD"],
}


def entry_event(t, ref: EntryRef) -> str:
    if ref.kind == "pair":
        pair = t.pairs.get(ref.ref_id)
        return pair.event if pair else "MS"
    p = t.players.get(ref.ref_id)
    return next((e for e in (p.events if p else []) if e in ("MS", "WS")), "MS")


def entry_players(t, ref: EntryRef) -> list[str]:
    if ref.kind == "pair":
        pair = t.pairs.get(ref.ref_id)
        return list(pair.player_ids) if pair else []
    return [ref.ref_id]


def _active(t, pid: str) -> bool:
    p = t.players.get(pid)
    return bool(p and not p.is_stub and not p.withdrawn)


def build_entries(t, events: list[str]) -> list[EntryRef]:
    """All registered entries whose event is in ``events`` (deduped, stable)."""
    allow = set(events)
    out: list[EntryRef] = []
    for pid_pair in sorted(t.pairs):
        pair = t.pairs[pid_pair]
        if pair.event in allow and all(_active(t, p) for p in pair.player_ids):
            out.append(EntryRef("pair", pair.id))
    for pid in sorted(t.players):
        p = t.players[pid]
        if not _active(t, pid):
            continue
        if any(e in ("MS", "WS") and e in allow for e in p.events):
            out.append(EntryRef("player", pid))
    return out


def _clusters(t, entries: list[EntryRef]) -> list[list[EntryRef]]:
    """Group entries that share a player (co-location) via union-find."""
    parent = {e.key(): e.key() for e in entries}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    by_player: dict[str, list[str]] = defaultdict(list)
    for e in entries:
        for pid in entry_players(t, e):
            by_player[pid].append(e.key())
    for keys in by_player.values():
        for k in keys[1:]:
            parent[find(keys[0])] = find(k)

    refs = {e.key(): e for e in entries}
    groups: dict[str, list[EntryRef]] = defaultdict(list)
    for e in entries:
        groups[find(e.key())].append(e)
    out = list(groups.values())
    out.sort(key=lambda c: (-_cluster_strength(t, c), c[0].key()))
    return out


def _cluster_strength(t, cluster) -> float:
    return sum(entry_strength(t, e) for e in cluster)


def _resolve_num_teams(n_entries, n_clusters, num_teams, per_team) -> int:
    if num_teams:
        k = num_teams
    elif per_team:
        k = max(2, round(n_entries / max(1, per_team)))
    else:
        k = 2
    return max(1, min(k, 32, n_clusters))


def build_teams(t, method: str = "balanced", *, num_teams=None, players_per_team=None,
                events: list[str] | None = None, team_type: str = "open",
                rng_seed: int = 0, manual=None):
    """Return ``(teams, report)``. ``report`` = {grid, gaps, warnings}. Entries
    are kept intact, a player's entries stay together, nobody is dropped."""
    events = events or TYPE_EVENTS.get(team_type, list(ALL_EVENTS))
    entries = build_entries(t, events)

    if method == "manual" and manual:      # {team_name: [entry_key,...]}
        idx = {e.key(): e for e in entries}
        rosters = [[idx[k] for k in ks if k in idx] for ks in manual.values()]
        names = list(manual.keys())
    elif method == "by_club":
        groups: dict[str, list[EntryRef]] = defaultdict(list)
        for e in entries:
            pl = entry_players(t, e)
            club = next((t.players[p].club for p in pl if t.players[p].club), "Unaffiliated")
            groups[club].append(e)
        names = sorted(groups)
        rosters = [groups[n] for n in names]
    else:
        clusters = _clusters(t, entries)
        k = _resolve_num_teams(len(entries), len(clusters), num_teams, players_per_team)
        rosters = _distribute_by_event(t, clusters, k, events, method, rng_seed)
        names = [f"Team {i + 1}" for i in range(len(rosters))]

    teams = []
    for i, roster in enumerate(rosters):
        roster = sorted(roster, key=lambda e: (-entry_strength(t, e), e.key()))
        pids = []
        for e in roster:
            pids.extend(entry_players(t, e))
        teams.append(Team(id=f"team-{i + 1}", name=names[i], entries=list(roster),
                          player_ids=list(dict.fromkeys(pids)),
                          color=TEAM_COLORS[i % len(TEAM_COLORS)]))
    return teams, _report(t, teams, events)


def _cluster_events(t, cluster) -> list[str]:
    return [entry_event(t, e) for e in cluster]


def _distribute_by_event(t, clusters, k, events, method, rng_seed):
    """Split each event as evenly as possible across k teams while keeping every
    person's entries on ONE team (co-location). Whole clusters (a person's set of
    entries) are placed together, so a multi-event player never splits across
    teams; that can leave one event off-by-one -- reported in the grid.

    - balanced (default): place each cluster on the team that is currently
      *shortest in that cluster's events* (even per event), then smallest total,
      then lowest rating. Biggest/strongest clusters go first so they spread out.
    - snake: serpentine draft by rating over whole clusters (0,1,..,k-1,k-1,..,0).
    - random: shuffled order, otherwise the same even-fill rule.
    """
    teams: list[list[EntryRef]] = [[] for _ in range(k)]
    ev_count = [defaultdict(int) for _ in range(k)]
    skill = [0.0] * k

    if method == "random":
        order = list(clusters)
        _random.Random(rng_seed).shuffle(order)
    else:                                       # biggest first, then strongest
        order = sorted(clusters, key=lambda c: (-len(c), -_cluster_strength(t, c),
                                                c[0].key()))

    if method == "snake":
        idx, step = 0, 1
        for cluster in order:
            teams[idx].extend(cluster)
            nxt = idx + step
            if nxt < 0 or nxt >= k:
                step = -step                    # bounce at the ends
            else:
                idx = nxt
        return teams

    for cluster in order:                       # balanced / random
        evs = _cluster_events(t, cluster)
        # Prefer the team with the least load across THIS cluster's events (keeps
        # each event even), then the smallest team overall, then lowest rating.
        i = min(range(k), key=lambda j: (sum(ev_count[j][ev] for ev in evs),
                                         len(teams[j]), skill[j], j))
        for e, ev in zip(cluster, evs):
            teams[i].append(e)
            ev_count[i][ev] += 1
        skill[i] += _cluster_strength(t, cluster)
    return teams


def team_event_counts(t, team: Team) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for e in team.entries:
        counts[entry_event(t, e)] += 1
    return dict(counts)


def _report(t, teams, events):
    """Per-team x per-event grid, plus gaps: events where teams are uneven, so
    some ties will have entries with no opponent."""
    grid = []
    for tm in teams:
        counts = team_event_counts(t, tm)
        grid.append({"team_id": tm.id, "team_name": tm.name,
                     "size": len(tm.entries),
                     "by_event": {ev: counts.get(ev, 0) for ev in events}})
    gaps, warnings = [], []
    for ev in events:
        vals = [g["by_event"].get(ev, 0) for g in grid]
        if not vals:
            continue
        hi, lo = max(vals), min(vals)
        if hi != lo:
            short = [grid[i]["team_name"] for i, v in enumerate(vals) if v < hi]
            gaps.append({"event": ev, "max": hi, "short": short})
            warnings.append(f"{ev}: uneven ({'/'.join(str(v) for v in vals)}) — "
                            f"{', '.join(short)} short of {hi}; those ties will have "
                            f"entries with no opponent until you add more.")
    return {"grid": grid, "gaps": gaps, "warnings": warnings}
