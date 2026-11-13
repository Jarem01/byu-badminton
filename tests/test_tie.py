"""Entry-based ties: rubbers matched by event+rank, dynamic threshold, uneven
counts flagged, majority/tiebreak/draw."""

import unittest

from tournament.engine import format_registry, tie
from tournament.engine.advancement import record_result
from tournament.engine.seeding import seed_entries
from tournament.engine.team_build import entry_players
from tournament.model.entities import (
    Division, EntryRef, Pair, Player, Team, TeamFormat, Tournament,
)


def pair(t, key, ev, skill):
    a, b = f"{key}a", f"{key}b"
    ga, gb = ("M", "F") if ev == "XD" else (("M", "M") if ev == "MD" else ("F", "F"))
    t.players[a] = Player(id=a, first=key, last="A", gender=ga, skill=skill, events=[ev])
    t.players[b] = Player(id=b, first=key, last="B", gender=gb, skill=skill, events=[ev])
    t.pairs[key] = Pair(id=key, player_ids=[a, b], event=ev)
    return EntryRef("pair", key)


def team_div(t, rosters, events, allow_draw=False):
    refs = []
    for i, ents in enumerate(rosters):
        tid = f"team-{i}"
        pids = [p for e in ents for p in entry_players(t, e)]
        t.teams[tid] = Team(id=tid, name=f"Team {i}", entries=ents,
                            player_ids=list(dict.fromkeys(pids)))
        refs.append(EntryRef("team", tid))
    tf = TeamFormat(events=events, allow_draw=allow_draw)
    div = Division(id="d", event=events[0], label="T", entry_refs=refs,
                   team_type="mixed", team_format=tf)
    t.divisions["d"] = div
    br = format_registry.generate("single_elim", div, seed_entries(t, div, "ranking"))
    t.brackets["d"] = br
    tie.fill_ties_from_draw(t, br)
    return div, br


def the_tie(br):
    return next(m for m in br.matches.values() if m.bracket_part != "rubber")


class TestTie(unittest.TestCase):
    def test_rubbers_matched_by_rank(self):
        t = Tournament(mode="team")
        A = [pair(t, "a0", "XD", 9), pair(t, "a1", "XD", 7), pair(t, "a2", "XD", 5)]
        B = [pair(t, "b0", "XD", 8), pair(t, "b1", "XD", 6), pair(t, "b2", "XD", 4)]
        _div, br = team_div(t, [A, B], ["XD"])
        ti = the_tie(br)
        self.assertEqual(len(ti.sub_match_ids), 3)        # min(3,3)
        r0 = br.matches[ti.sub_match_ids[0]]
        # strongest vs strongest (pair a0=9 vs b0=8), entries used intact
        self.assertEqual(r0.side1.ref_id, "a0")
        self.assertEqual(r0.side2.ref_id, "b0")

    def test_uneven_counts_flagged(self):
        t = Tournament(mode="team")
        A = [pair(t, "a0", "XD", 8), pair(t, "a1", "XD", 6), pair(t, "a2", "XD", 4)]
        B = [pair(t, "b0", "XD", 7), pair(t, "b1", "XD", 5)]
        _div, br = team_div(t, [A, B], ["XD"])
        ti = the_tie(br)
        self.assertEqual(len(ti.sub_match_ids), 2)        # min(3,2)
        gaps = tie.tie_gaps(t, ti)
        self.assertTrue(any(g["event"] == "XD" and g["unmatched"] == 1 for g in gaps))

    def test_majority_decides(self):
        t = Tournament(mode="team")
        A = [pair(t, "a0", "XD", 9), pair(t, "a1", "XD", 7), pair(t, "a2", "XD", 5)]
        B = [pair(t, "b0", "XD", 8), pair(t, "b1", "XD", 6), pair(t, "b2", "XD", 4)]
        _div, br = team_div(t, [A, B], ["XD"])
        ti = the_tie(br)
        for rid in ti.sub_match_ids[:2]:                  # side1 wins 2 of 3
            record_result(br, rid, [[21, 5], [21, 5]])
            tie.decide_tie(t, br, ti)
        self.assertEqual(ti.result.winner, ti.side1)
        self.assertEqual(ti.result.games, [[2, 0]])

    def test_even_split_games_tiebreak(self):
        t = Tournament(mode="team")
        A = [pair(t, "a0", "XD", 8), pair(t, "a1", "XD", 6)]
        B = [pair(t, "b0", "XD", 7), pair(t, "b1", "XD", 5)]
        _div, br = team_div(t, [A, B], ["XD"])
        ti = the_tie(br)
        record_result(br, ti.sub_match_ids[0], [[21, 5], [21, 5]])            # A 2-0
        record_result(br, ti.sub_match_ids[1], [[21, 18], [15, 21], [19, 21]])  # B 2-1
        w = tie.decide_tie(t, br, ti)
        self.assertEqual(w, ti.side1)          # 1-1 rubbers; A leads on games (2 vs 1)

    def test_cross_play_all_vs_all(self):
        t = Tournament(mode="team")
        A = [pair(t, "a0", "XD", 8), pair(t, "a1", "XD", 6), pair(t, "a2", "XD", 4)]
        B = [pair(t, "b0", "XD", 7), pair(t, "b1", "XD", 5), pair(t, "b2", "XD", 3)]
        _div, br = team_div(t, [A, B], ["XD"])
        ti = the_tie(br)
        t.divisions["d"].team_format.tie_format = "cross"
        for m in list(br.matches.values()):        # reset + rebuild as cross
            if m.bracket_part == "rubber":
                del br.matches[m.id]
        ti.sub_match_ids = []
        tie.build_tie_rubbers(t, br, ti)
        self.assertEqual(len(ti.sub_match_ids), 9)   # 3 x 3
        pairs_seen = {(br.matches[r].side1.ref_id, br.matches[r].side2.ref_id)
                      for r in ti.sub_match_ids}
        self.assertEqual(len(pairs_seen), 9)         # every A vs every B

    def test_per_event_rule_override(self):
        t = Tournament(mode="team")
        A = [pair(t, "am0", "MS", 8), pair(t, "am1", "MS", 6),
             pair(t, "ax0", "XD", 7), pair(t, "ax1", "XD", 5)]
        B = [pair(t, "bm0", "MS", 7), pair(t, "bm1", "MS", 5),
             pair(t, "bx0", "XD", 6), pair(t, "bx1", "XD", 4)]
        # MS is a "pair" here only for convenience; treat as its own event.
        _div, br = team_div(t, [A, B], ["MS", "XD"])
        ti = the_tie(br)
        fmt = t.divisions["d"].team_format
        fmt.tie_format = "position"
        fmt.event_rules = {"XD": "cross"}
        for m in list(br.matches.values()):
            if m.bracket_part == "rubber":
                del br.matches[m.id]
        ti.sub_match_ids = []
        tie.build_tie_rubbers(t, br, ti)
        ms = [r for r in ti.sub_match_ids if "MS" in br.matches[r].round_name or "Men's Singles" in br.matches[r].round_name]
        # MS position -> 2 rubbers; XD cross -> 2x2 = 4 rubbers; total 6
        self.assertEqual(len(ti.sub_match_ids), 6)

    def test_handicap_flips_close_game(self):
        from tournament.model.entities import TeamFormat
        t = Tournament(mode="team")
        A = [pair(t, "a0", "XD", 3)]          # weaker
        B = [pair(t, "b0", "XD", 9)]          # stronger
        _div, br = team_div(t, [A, B], ["XD"])
        ti = the_tie(br)
        fmt = t.divisions["d"].team_format
        fmt.handicap = True
        rub = br.matches[ti.sub_match_ids[0]]
        # side1 is Team 0 (a0, weaker). Raw it loses 19-21, 19-21; +handicap flips it.
        tie.record_rubber(t, br, rub, [[19, 21], [19, 21]], fmt)
        self.assertEqual(rub.result.winner, rub.side1)   # weaker side wins on handicap
        self.assertEqual(rub.result.games, [[19, 21], [19, 21]])  # raw scores kept

    def test_draw_when_allowed(self):
        t = Tournament(mode="team")
        A = [pair(t, "a0", "XD", 8), pair(t, "a1", "XD", 6)]
        B = [pair(t, "b0", "XD", 7), pair(t, "b1", "XD", 5)]
        _div, br = team_div(t, [A, B], ["XD"], allow_draw=True)
        ti = the_tie(br)
        record_result(br, ti.sub_match_ids[0], [[21, 5], [21, 5]])   # A wins r0
        record_result(br, ti.sub_match_ids[1], [[5, 21], [5, 21]])   # B wins r1
        w = tie.decide_tie(t, br, ti)
        self.assertIsNone(w)                    # 1-1 and draws allowed -> level
        self.assertIsNone(ti.result.winner)
        self.assertEqual(ti.result.games, [[1, 1]])


if __name__ == "__main__":
    unittest.main()
