"""Assign matches to courts and time slots on a single-day shared-court grid.

Rules enforced:
- A match starts only after all its feeder matches finish (knockout depth).
- No player is double-booked across events, and each player gets at least
  ``rest_min`` between the end of one match's play and the start of the next.
- Byes and already-decided walkovers are not scheduled (no court time needed).

Greedy earliest-slot placement; deterministic given the same inputs.
"""

from __future__ import annotations

from ..config import Settings
from ..engine.bracket_double import is_inactive_reset
from ..model.entities import Court, Match, ScheduleBlock, Tournament
from .courtplan import center_court_numbers, is_center_court_match


def match_player_ids(t: Tournament, m: Match) -> set[str]:
    ids: set[str] = set()
    for side in (m.side1, m.side2):
        if side is None:
            continue
        if side.kind == "player":
            ids.add(side.ref_id)
        else:
            pair = t.pairs.get(side.ref_id)
            if pair:
                ids.update(pair.player_ids)
    return ids


def _feeders(matches: dict[str, Match]) -> dict[str, list[str]]:
    feeders: dict[str, list[str]] = {mid: [] for mid in matches}
    for m in matches.values():
        for nxt in (m.next_win_match, m.next_lose_match):
            if nxt and nxt in feeders:
                feeders[nxt].append(m.id)
    return feeders


def _depths(matches, feeders) -> dict[str, int]:
    memo: dict[str, int] = {}

    def depth(mid: str) -> int:
        if mid in memo:
            return memo[mid]
        fs = feeders.get(mid, [])
        memo[mid] = 0 if not fs else 1 + max(depth(f) for f in fs)
        return memo[mid]

    return {mid: depth(mid) for mid in matches}


def ensure_courts(t: Tournament, settings: Settings) -> list[Court]:
    # Rebuild whenever the configured count changes, so editing court count in
    # Settings and regenerating actually takes effect.
    if len(t.courts) != settings.court_count:
        t.courts = [Court(id=f"court-{i+1}", name=f"Court {i+1}")
                    for i in range(settings.court_count)]
    return t.courts


def _fits(intervals: list[tuple[int, int]], start: int, end: int) -> bool:
    return all(end <= s or start >= e for (s, e) in intervals)


def generate_schedule(t: Tournament, settings: Settings,
                      division_ids: list[str] | None = None) -> list[ScheduleBlock]:
    """Timeline scheduler on a shared pool of courts. Each match gets its own
    duration (pool matches are short timed games, knockout matches best-of-3),
    starts only after its feeders finish, and never double-books a player or
    violates rest time. Greedy earliest-feasible placement in dependency order."""
    courts = ensure_courts(t, settings)
    division_ids = division_ids or list(t.brackets.keys())

    matches: dict[str, Match] = {}
    fmt_by_match: dict[str, str] = {}
    knockout_of: dict[str, bool] = {}     # match id -> must use a center court
    concurrent_ids: set[str] = set()      # rubbers whose tie plays concurrently
    tie_of: dict[str, str] = {}           # rubber id -> parent tie id
    tie_rubbers: dict[str, list[str]] = {}  # tie id -> its scheduled rubber ids
    team_full_ids: set[str] = set()       # team rubbers played as FULL matches
    quick_ids: set[str] = set()           # team rubbers played as a quick game
    for div_id in division_ids:
        br = t.brackets.get(div_id)
        if not br:
            continue
        div = t.divisions.get(div_id)
        team = bool(div and div.team_format)
        concurrent = team and div.team_format.play_mode == "concurrent"
        for m in br.matches.values():
            if is_inactive_reset(m):
                continue      # double-elim reset that will never be played
            fmt_by_match[m.id] = br.format
            if m.result is not None:
                # Already decided: a bye/walkover needs no court, and a match
                # that has been played must not be scheduled again.
                continue
            if team:
                # A team draw schedules RUBBERS, not the tie aggregates. Skip
                # unfilled/void rubbers and, under 'stop', dead rubbers of a
                # tie that's already clinched.
                if m.bracket_part != "rubber":
                    continue
                if not (m.side1 and m.side2):
                    continue
                parent = br.matches.get(m.parent_id)
                if (parent and parent.result and parent.result.winner
                        and div.team_format.dead_rubbers == "stop"):
                    continue
                knockout_of[m.id] = False     # team rubbers may use any court
                # Match length is set by the team format, NOT the draw format, so
                # a team round-robin/league doesn't shorten its matches.
                if div.team_format.match_length == "quick":
                    quick_ids.add(m.id)
                else:
                    team_full_ids.add(m.id)
                if concurrent:
                    concurrent_ids.add(m.id)
                    tie_of[m.id] = m.parent_id
                    tie_rubbers.setdefault(m.parent_id, []).append(m.id)
            else:
                # Shared rule: only knockout QF/SF/final matches need a center
                # court (see schedule/courtplan.py).
                knockout_of[m.id] = is_center_court_match(br, m)
            matches[m.id] = m

    # For concurrent ties: players and court demand of each whole tie block.
    tie_players = {tid: set().union(*(match_player_ids(t, matches[r]) for r in rs))
                   for tid, rs in tie_rubbers.items()}
    tie_size = {tid: len(rs) for tid, rs in tie_rubbers.items()}

    feeders = _feeders(matches)
    # In group_knockout the pools feed the knockout via standings, not via match
    # links, so add a synthetic dependency: every first-round knockout match must
    # come after ALL of its division's pool matches (the pool stage finishes
    # before the knockout begins).
    for div_id in division_ids:
        br = t.brackets.get(div_id)
        if not br or br.format != "group_knockout":
            continue
        pool_ids = [m.id for m in br.matches.values()
                    if m.bracket_part == "pool" and m.id in matches]
        first_ko = next((r for r in br.rounds if r.bracket_part == "main"), None)
        if not first_ko or not pool_ids:
            continue
        for mid in first_ko.match_ids:
            if mid in feeders:
                feeders[mid].extend(pool_ids)

    # Round ordinal within each pool, so the scheduler interleaves pools by round
    # (round 1 of every pool runs together, then round 2, ...). This spreads a
    # player's own pool matches across time and fills courts with other pools'
    # games while they rest.
    pool_round_ord: dict[str, int] = {}
    for div_id in division_ids:
        br = t.brackets.get(div_id)
        if not br:
            continue
        per_pool: dict[str, int] = {}
        for rnd in br.rounds:
            if rnd.bracket_part != "pool" or not rnd.match_ids:
                continue
            pool_id = br.matches[rnd.match_ids[0]].pool_id
            per_pool[pool_id] = per_pool.get(pool_id, 0) + 1
            for mid in rnd.match_ids:
                pool_round_ord[mid] = per_pool[pool_id]

    depth = _depths(matches, feeders)
    order = sorted(matches.values(),
                   key=lambda m: (depth[m.id], pool_round_ord.get(m.id, 0),
                                  m.division_id, m.seq))

    def timing_for(m: Match):
        # Team rubbers use FULL timing unless the team format is 'quick' -- the
        # draw format (even a league) must not shorten them.
        if m.id in quick_ids:
            return settings.pool_timing
        if m.id in team_full_ids:
            return settings.timing
        # Short timed single games ONLY for a standalone round-robin division;
        # group_knockout pools (and all knockouts) play full best-of-N matches.
        if fmt_by_match.get(m.id) == "round_robin":
            return settings.pool_timing
        return settings.timing

    # QF/SF/final matches may only run on the unobstructed center courts; earlier
    # knockout rounds and pools use any court. Which courts count as center (and
    # the "fewer than two -> don't restrict" fallback) is decided by the shared
    # rule in schedule/courtplan.py -- the same one the court board uses.
    def court_num(c) -> int:
        return int(c.id.rsplit("-", 1)[1])
    center = set(center_court_numbers(settings, [court_num(c) for c in courts]))
    center_courts = [c for c in courts if court_num(c) in center]

    def courts_for(m: Match):
        return center_courts if (knockout_of.get(m.id) and center_courts) else courts

    court_intervals: dict[str, list[tuple[int, int]]] = {c.id: [] for c in courts}
    player_windows: dict[str, list[tuple[int, int]]] = {}
    end_of: dict[str, int] = {}
    blocks: list[ScheduleBlock] = []

    def players_free(pids, play_start, play_end) -> bool:
        # HARD guarantee: no player is ever in two matches at once, and each gets
        # at least rest_min between the end of one match's play and the start of
        # the next. This is the security check that prevents double-booking.
        for pid in pids:
            for (ps, pe) in player_windows.get(pid, ()):
                if not (play_start >= pe + settings.rest_min
                        or ps >= play_end + settings.rest_min):
                    return False
        return True

    def min_separation(pids, play_start, play_end) -> float:
        """Smallest rest gap this placement leaves for any involved player
        (float('inf') if none of them have played yet). Bigger = better spread."""
        best = float("inf")
        for pid in pids:
            for (ps, pe) in player_windows.get(pid, ()):
                if pe <= play_start:
                    best = min(best, play_start - pe)
                elif ps >= play_end:
                    best = min(best, ps - play_end)
        return best

    tie_start: dict[str, int] = {}         # tie id -> shared start (concurrent)

    def earliest_block(tid, floor_t, tm) -> int:
        """Earliest start where a whole concurrent tie fits: all its players free
        and at least (tie size) courts open for the slot."""
        dur = tm.slot_min
        players = tie_players.get(tid, set())
        need = tie_size.get(tid, 1)
        cands = {floor_t}
        for ivs in court_intervals.values():
            for (_s, e) in ivs:
                if e >= floor_t:
                    cands.add(e)
        for pid in players:
            for (_ps, pe) in player_windows.get(pid, ()):
                cands.add(pe + settings.rest_min)
        for T in sorted(c for c in cands if c >= floor_t):
            ps, pe = T + tm.warmup_min, T + tm.warmup_min + tm.play_min
            if not players_free(players, ps, pe):
                continue
            free = sum(1 for c in courts if _fits(court_intervals[c.id], T, T + dur))
            if free >= need:
                return T
        return floor_t

    for m in order:
        tm = timing_for(m)
        dur = tm.slot_min
        min_start = max((end_of[f] for f in feeders[m.id] if f in end_of), default=0)
        pids = match_player_ids(t, m)
        allowed = courts_for(m)
        allowed_ids = {c.id for c in allowed}

        # Concurrent tie: all its rubbers start together. Fix the shared start
        # (whole-tie block fit) when the first rubber is placed.
        forced = None
        if m.id in concurrent_ids:
            tid = tie_of[m.id]
            if tid not in tie_start:
                tie_start[tid] = earliest_block(tid, min_start, tm)
            forced = tie_start[tid]
            min_start = forced

        # Candidate start times: the earliest possible, plus every point an
        # eligible court frees up or a player's rest completes.
        if forced is not None:
            cand = {forced}
        else:
            cand = {min_start}
            for cid, ivs in court_intervals.items():
                if cid not in allowed_ids:
                    continue
                for (_s, e) in ivs:
                    if e >= min_start:
                        cand.add(e)
            for pid in pids:
                for (_ps, pe) in player_windows.get(pid, ()):
                    cand.add(pe + settings.rest_min)

        # Among feasible starts within one slot of the earliest, prefer the one
        # that gives players the MOST rest -- this minimizes back-to-back games
        # without materially lengthening the day.
        chosen_t = chosen_court = None
        best_sep = -1.0
        earliest = None
        for T in sorted(x for x in cand if x >= min_start):
            if earliest is not None and T > earliest + dur:
                break
            play_start, play_end = T + tm.warmup_min, T + tm.warmup_min + tm.play_min
            if not players_free(pids, play_start, play_end):
                continue
            court = next((c for c in allowed
                          if _fits(court_intervals[c.id], T, T + dur)), None)
            if court is None:
                continue
            if earliest is None:
                earliest = T
            sep = min_separation(pids, play_start, play_end)
            if sep > best_sep:               # maximise rest; ties keep the earlier T
                best_sep, chosen_t, chosen_court = sep, T, court
        if chosen_t is None:                       # safety fallback (rare)
            chosen_t = max([min_start] + [e for cid in allowed_ids
                                          for (_s, e) in court_intervals[cid]],
                           default=min_start)
            chosen_court = allowed[0]

        court_intervals[chosen_court.id].append((chosen_t, chosen_t + dur))
        ps = chosen_t + tm.warmup_min
        for pid in pids:
            player_windows.setdefault(pid, []).append((ps, ps + tm.play_min))
        end_of[m.id] = chosen_t + dur
        blocks.append(ScheduleBlock(
            match_id=m.id, court_id=chosen_court.id, start_min=chosen_t,
            warmup_min=tm.warmup_min, play_min=tm.play_min, buffer_min=tm.buffer_min))

    blocks.sort(key=lambda b: (b.start_min, b.court_id))
    t.schedule = blocks
    return blocks


def player_conflicts(t: Tournament) -> list[str]:
    """Report any residual overlapping bookings (should be empty). Useful as a
    post-condition check and for schedules edited by hand."""
    windows: dict[str, list[tuple[int, int, str]]] = {}
    by_id = {}
    for br in t.brackets.values():
        by_id.update(br.matches)
    problems = []
    for b in t.schedule:
        m = by_id.get(b.match_id)
        if not m:
            continue
        for pid in match_player_ids(t, m):
            windows.setdefault(pid, []).append((b.play_start_min,
                                                b.play_start_min + b.play_min, b.match_id))
    for pid, wins in windows.items():
        wins.sort()
        for i in range(1, len(wins)):
            if wins[i][0] < wins[i - 1][1]:
                problems.append(f"{t.players[pid].full if pid in t.players else pid}: "
                                f"overlapping matches {wins[i-1][2]} and {wins[i][2]}")
    return problems
