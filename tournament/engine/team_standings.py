"""Team-league standings ('point system').

For team round-robin / pool play, rank teams by a configurable metric:
- ``tie_wins``      -> ties won (classic).
- ``league_points`` -> win/draw/loss points (e.g. 2/1/0).
- ``rubbers``       -> total rubbers won (cumulative, no-elimination style).
Tiebreak chain in all cases: rubber differential -> point differential -> seed.
Reads the tie matches (each carries winner + a [w1,w2] rubber tally) and their
rubbers (for point-for/against).
"""

from __future__ import annotations

from ..model.entities import Bracket, Tournament


def _team_stats(t, bracket, team_key, ties, fmt):
    tw = tl = td = rf = rl = pf = pa = played = 0
    for m in ties:
        if not (m.result and m.side1 and m.side2):
            continue
        if team_key not in (m.side1.key(), m.side2.key()):
            continue
        played += 1
        is_s1 = m.side1.key() == team_key
        tally = m.result.games[0] if m.result.games else [0, 0]
        rf += tally[0] if is_s1 else tally[1]
        rl += tally[1] if is_s1 else tally[0]
        if m.result.winner is None:
            td += 1
        elif m.result.winner.key() == team_key:
            tw += 1
        else:
            tl += 1
        for rid in m.sub_match_ids:
            rm = bracket.matches.get(rid)
            if not (rm and rm.result and rm.result.winner):
                continue
            for g in rm.result.games:
                if len(g) == 2:
                    pf += g[0] if is_s1 else g[1]
                    pa += g[1] if is_s1 else g[0]
    pts = tw * fmt.win_points + td * fmt.draw_points + tl * fmt.loss_points
    return {"played": played, "wins": tw, "losses": tl, "draws": td,
            "rubbers_for": rf, "rubbers_against": rl, "rubber_diff": rf - rl,
            "points_for": pf, "points_against": pa, "point_diff": pf - pa,
            "league_points": pts}


def _sort_key(row, rank_by):
    primary = {"tie_wins": row["wins"], "league_points": row["league_points"],
               "rubbers": row["rubbers_for"],
               "points": row["points_for"]}.get(rank_by, row["wins"])
    return (-primary, -row["rubber_diff"], -row["point_diff"], row["_seed"])


def team_standings_for(t: Tournament, bracket: Bracket, team_refs, ties, fmt):
    seed_of = {s.entry.key(): s.seed_no for s in bracket.seeds}
    rows = []
    for ref in team_refs:
        r = _team_stats(t, bracket, ref.key(), ties, fmt)
        r["key"] = ref.key()
        r["label"] = t.entry_label(ref)
        team = t.teams.get(ref.ref_id)
        r["color"] = team.color if team else ""
        r["_seed"] = seed_of.get(ref.key(), 10 ** 9)
        rows.append(r)
    rows.sort(key=lambda r: _sort_key(r, fmt.rank_by))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        r.pop("_seed", None)
    return rows


def all_team_standings(t: Tournament, bracket: Bracket, fmt) -> list[dict]:
    """One table per pool (round-robin => a single pool of all teams)."""
    from .standings import pool_complete
    out = []
    for pool in bracket.pools:
        ties = [m for m in bracket.matches.values()
                if m.pool_id == pool.id and m.bracket_part != "rubber"]
        out.append({
            "pool": pool.label, "complete": pool_complete(bracket, pool),
            "rank_by": fmt.rank_by,
            "rows": team_standings_for(t, bracket, pool.entry_refs, ties, fmt),
        })
    return out
