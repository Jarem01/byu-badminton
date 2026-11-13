"""Team-model persistence (entry-based). New fields round-trip via the codec
with no registration, and individual documents are unaffected."""

import unittest

from tournament.model.codec import from_jsonable, to_jsonable
from tournament.model.entities import (
    Division, EntryRef, Player, Team, TeamFormat, Tournament,
)


class TestTeamModel(unittest.TestCase):
    def test_round_trip(self):
        t = Tournament(mode="team")
        t.players["a"] = Player(id="a", first="A", last="X", gender="M", skill=8,
                                events=["XD"])
        t.teams["t1"] = Team(id="t1", name="Red",
                             entries=[EntryRef("pair", "p1"), EntryRef("player", "q1")],
                             player_ids=["a", "b", "q1"], captain_id="a")
        fmt = TeamFormat(events=["XD", "MS"], play_mode="concurrent",
                         dead_rubbers="all", rank_by="league_points",
                         win_points=3, allow_draw=True)
        t.divisions["d"] = Division(id="d", event="XD", label="Team",
                                    entry_refs=[EntryRef("team", "t1")],
                                    team_type="mixed", team_format=fmt)
        back = from_jsonable(Tournament, to_jsonable(t))
        self.assertEqual(back.mode, "team")
        team = back.teams["t1"]
        self.assertEqual([e.kind for e in team.entries], ["pair", "player"])
        f = back.divisions["d"].team_format
        self.assertEqual(f.events, ["XD", "MS"])
        self.assertEqual(f.rank_by, "league_points")
        self.assertEqual(f.win_points, 3)
        self.assertTrue(f.allow_draw)
        self.assertEqual(f.play_mode, "concurrent")

    def test_entry_label_team(self):
        t = Tournament(mode="team")
        t.teams["t1"] = Team(id="t1", name="Red")
        self.assertEqual(t.entry_label(EntryRef("team", "t1")), "Red")
        self.assertEqual(t.entry_label(EntryRef("team", "missing")), "missing")

    def test_individual_doc_unchanged(self):
        t = Tournament()
        t.players["p"] = Player(id="p", first="A", last="B")
        back = from_jsonable(Tournament, to_jsonable(t))
        self.assertEqual(back.mode, "individual")
        self.assertEqual(back.teams, {})


if __name__ == "__main__":
    unittest.main()
