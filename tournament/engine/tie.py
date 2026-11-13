"""Team ties (entry-based dual-meet).

A team draw is an ordinary bracket over ``team`` entries; each match in it is a
**tie**. This module builds a tie's **rubbers** by matching the two teams'
intact entries by event and rank (A's XD#1 vs B's XD#1, A's MS#1 vs B's MS#1,
...), one rubber per matchup. Entries are used exactly as registered -- no
re-pairing. Where the two teams have unequal counts in an event, only the
matchable rubbers are created (min of the two); the surplus entries sit out and
are reported as "no opponent". The tie is decided by rubber majority
(threshold = floor(count/2)+1); an even split goes to the tiebreak chain
(rubbers -> games -> points) unless draws are allowed.
"""

from __future__ import annotations

from collections import defaultdict

from ..config import EVENT_LABELS
from ..model.entities import Bracket, EntryRef, Match, Result, Tournament
from .advancement import propagate, unpropagate
from .seeding import entry_strength
from .team_build import ALL_EVENTS, entry_event


def is_tie(match: Match) -> bool:
    return match.bracket_part != "rubber"


def _team_entries_by_event(t: Tournament, team) -> dict[str, list[EntryRef]]:
    by_ev: dict[str, list[EntryRef]] = defaultdict(list)
    for e in team.entries:
        by_ev[entry_event(t, e)].append(e)
    for ev in by_ev:
        by_ev[ev].sort(key=lambda e: (-entry_strength(t, e), e.key()))   # strongest first
    return by_ev


def _tie_style(fmt, ev: str) -> str:
    """Tie format for an event: a per-event override, else the division's."""
    if fmt and fmt.event_rules.get(ev):
        return fmt.event_rules[ev]
    return fmt.tie_format if fmt else "position"


def build_tie_rubbers(t: Tournament, bracket: Bracket, tie: Match) -> None:
    """Create the tie's rubbers. Per event, either POSITION (rank vs rank, one
    match per slot) or CROSS (every A entry plays every B entry). Idempotent."""
    if tie.sub_match_ids or not (tie.side1 and tie.side2):
        return
    teamA = t.teams.get(tie.side1.ref_id)
    teamB = t.teams.get(tie.side2.ref_id)
    if not teamA or not teamB:
        return
    A = _team_entries_by_event(t, teamA)
    B = _team_entries_by_event(t, teamB)
    div = t.divisions.get(bracket.division_id)
    fmt = div.team_format if div else None
    order = 0
    for ev in ALL_EVENTS:                       # stable, readable event order
        ae, be = A.get(ev, []), B.get(ev, [])
        if not ae or not be:
            continue
        label = EVENT_LABELS.get(ev, ev)
        if _tie_style(fmt, ev) == "cross":
            matchups = [(ae[i], be[j], f"{label} {i + 1}v{j + 1}")
                        for i in range(len(ae)) for j in range(len(be))]
        else:                                   # position: rank vs rank
            matchups = [(ae[i], be[i], f"{label} {i + 1}")
                        for i in range(min(len(ae), len(be)))]
        for a, b, lbl in matchups:
            rid = f"{tie.id}-r{order}"
            bracket.matches[rid] = Match(
                id=rid, division_id=tie.division_id,
                round_name=f"{tie.round_name} · {lbl}", bracket_part="rubber",
                parent_id=tie.id, seq=tie.seq * 100 + order, side1=a, side2=b)
            tie.sub_match_ids.append(rid)
            order += 1


def handicap_bonus(t: Tournament, rubber: Match, fmt) -> tuple[int, int]:
    """Per-game head start (side1_bonus, side2_bonus) for the lower-rated side
    when handicap is on: H = min(cap, round(|ratingA - ratingB|))."""
    if not (fmt and fmt.handicap and rubber.side1 and rubber.side2):
        return (0, 0)
    sa, sb = entry_strength(t, rubber.side1), entry_strength(t, rubber.side2)
    h = min(fmt.handicap_cap, round(abs(sa - sb)))
    if h <= 0:
        return (0, 0)
    return (h, 0) if sa < sb else (0, h)


def record_rubber(t: Tournament, bracket: Bracket, rubber: Match,
                  games: list[list[int]], fmt) -> Match:
    """Record a team rubber, deciding the winner with any handicap applied to
    the weaker side. Raw game scores are stored/shown unchanged."""
    b1, b2 = handicap_bonus(t, rubber, fmt)
    wa = sum(1 for g in games if len(g) == 2 and (g[0] + b1) > (g[1] + b2))
    wb = sum(1 for g in games if len(g) == 2 and (g[1] + b2) > (g[0] + b1))
    if wa == wb:
        raise ValueError("games are tied; no rubber winner")
    winner = rubber.side1 if wa > wb else rubber.side2
    rubber.result = Result(games=games, winner=winner)
    return rubber


def tie_gaps(t: Tournament, tie: Match) -> list[dict]:
    """Entries that have no opponent in this tie (surplus on the bigger side),
    per event -- surfaced so the organizer can even things out."""
    teamA = t.teams.get(tie.side1.ref_id) if tie.side1 else None
    teamB = t.teams.get(tie.side2.ref_id) if tie.side2 else None
    if not teamA or not teamB:
        return []
    A = _team_entries_by_event(t, teamA)
    B = _team_entries_by_event(t, teamB)
    out = []
    for ev in ALL_EVENTS:
        a, b = len(A.get(ev, [])), len(B.get(ev, []))
        if a != b:
            out.append({"event": ev, "a": a, "b": b, "unmatched": abs(a - b)})
    return out


def _seed_break(bracket: Bracket, tie: Match) -> EntryRef:
    seed_of = {s.entry.key(): s.seed_no for s in bracket.seeds}
    s1 = seed_of.get(tie.side1.key(), 10 ** 9)
    s2 = seed_of.get(tie.side2.key(), 10 ** 9)
    return tie.side1 if s1 <= s2 else tie.side2


def decide_tie(t: Tournament, bracket: Bracket, tie: Match) -> EntryRef | None:
    """Recompute a tie's winner from its rubbers and keep the draw consistent.
    Threshold is per-tie (floor(rubber_count/2)+1). Returns the winning team ref
    (or None if undecided / a recorded draw)."""
    div = t.divisions.get(bracket.division_id)
    fmt = div.team_format if div else None
    rubbers = [bracket.matches[m] for m in tie.sub_match_ids]
    total = len(rubbers)
    threshold = total // 2 + 1

    w1 = w2 = g1 = g2 = p1 = p2 = decided = 0
    for rm in rubbers:
        if rm.result and rm.result.winner:
            decided += 1
            if rm.result.winner == rm.side1:
                w1 += 1
            else:
                w2 += 1
            gw1, gw2 = rm.result.games_won()
            g1 += gw1
            g2 += gw2
            for game in rm.result.games:
                if len(game) == 2:
                    p1 += game[0]
                    p2 += game[1]

    new_winner: EntryRef | None = None
    draw = False
    if total and w1 >= threshold:
        new_winner = tie.side1
    elif total and w2 >= threshold:
        new_winner = tie.side2
    elif total and decided == total:
        # All rubbers played; neither reached the threshold only if it's an even
        # split. Draw (if allowed) else break by games -> points -> seed.
        if w1 != w2:
            new_winner = tie.side1 if w1 > w2 else tie.side2
        elif fmt and fmt.allow_draw:
            draw = True
        elif g1 != g2:
            new_winner = tie.side1 if g1 > g2 else tie.side2
        elif p1 != p2:
            new_winner = tie.side1 if p1 > p2 else tie.side2
        else:
            new_winner = _seed_break(bracket, tie)
    elif total == 0 and tie.side1 and tie.side2:
        new_winner = _seed_break(bracket, tie)     # teams share no event

    old = tie.result.winner if tie.result else None
    tally = [[w1, w2]]
    if draw:                                       # level result, no advancement
        if old is not None:
            unpropagate(bracket, tie)
        tie.result = Result(winner=None, games=tally)
    elif new_winner is None:
        if tie.result is not None:
            unpropagate(bracket, tie)
            tie.result = None
    elif old is None:
        tie.result = Result(winner=new_winner, games=tally)
        propagate(bracket, tie)
    elif old != new_winner:
        unpropagate(bracket, tie)
        tie.result = Result(winner=new_winner, games=tally)
        propagate(bracket, tie)
    else:
        tie.result.games = tally
    return new_winner


def dead_rubbers(fmt, tie: Match, bracket: Bracket) -> set[str]:
    """Rubbers that need not be played: if the tie is decided and policy is
    'stop', every still-unplayed rubber is dead."""
    if (fmt and fmt.dead_rubbers == "all") or not (tie.result and tie.result.winner):
        return set()
    return {mid for mid in tie.sub_match_ids if not bracket.matches[mid].result}


def fill_ties_from_draw(t: Tournament, bracket: Bracket, cap: int = 2) -> bool:
    """For every ready tie (both teams known), build its rubbers and decide it.
    Idempotent; safe after any result. ``cap`` kept for signature compatibility."""
    div = t.divisions.get(bracket.division_id)
    if not (div and div.team_format):
        return False
    changed = False
    for m in list(bracket.matches.values()):
        if not is_tie(m) or (m.result and m.result.walkover):
            continue
        if not (m.side1 and m.side2
                and m.side1.kind == "team" and m.side2.kind == "team"):
            continue
        if not m.sub_match_ids:
            build_tie_rubbers(t, bracket, m)
            changed = True
        decide_tie(t, bracket, m)
    return changed
