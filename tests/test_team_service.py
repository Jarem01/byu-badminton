"""Team service flow (entry-based): preview grouping, commit, generate, score,
league standings, gaps."""

import os
import tempfile
import unittest

from tournament.model.entities import Pair, Player
from tournament.server.service import TournamentService
from tournament.store.repository import Repository


def messy(svc):
    t = svc.t
    for i in range(12):                       # 12 XD pairs
        m, w = f"xm{i}", f"xw{i}"
        t.players[m] = Player(id=m, first=f"XM{i}", last="X", gender="M", skill=9 - i % 8, events=["XD"])
        t.players[w] = Player(id=w, first=f"XW{i}", last="Y", gender="F", skill=9 - i % 8, events=["XD"])
        t.pairs[f"px{i}"] = Pair(id=f"px{i}", player_ids=[m, w], event="XD")
    for i in range(8):                        # 8 MS singles
        t.players[f"ms{i}"] = Player(id=f"ms{i}", first=f"MS{i}", last="S", gender="M", skill=6, events=["MS"])


OPTS = {"method": "balanced", "num_teams": 4, "team_type": "mixed",
        "template": {"events": ["XD", "MS"]}, "rng_seed": 1, "label": "Team Event"}


class TestTeamService(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.svc = TournamentService(Repository(os.path.join(self.d.name, "t.json")))
        messy(self.svc)

    def tearDown(self):
        self.d.cleanup()

    def test_preview_groups_by_event(self):
        pv = self.svc.team_preview(OPTS)
        self.assertEqual(len(pv["teams"]), 4)
        first = pv["teams"][0]
        events = {g["event"] for g in first["by_event"]}
        self.assertTrue(events <= {"XD", "MS"})
        self.assertIn("grid", pv["report"])
        self.assertEqual(self.svc.t.mode, "individual")     # preview doesn't commit

    def test_commit_no_player_dropped(self):
        r = self.svc.commit_teams(OPTS)
        self.assertEqual(self.svc.t.mode, "team")
        div = self.svc.t.divisions[r["id"]]
        rostered = [pid for ref in div.entry_refs
                    for pid in self.svc.t.teams[ref.ref_id].player_ids]
        self.assertEqual(sorted(rostered), sorted(self.svc.t.players))

    def test_generate_score_and_view(self):
        r = self.svc.commit_teams(OPTS)
        did = r["id"]
        self.svc.generate_bracket(did, "single_elim")
        br = self.svc.t.brackets[did]
        ti = next(m for m in br.matches.values() if m.bracket_part != "rubber"
                  and m.side1 and m.side2 and m.side1.kind == "team")
        view_tie = self.svc.bracket_view(did)["rounds"][0]["matches"][0]
        self.assertTrue(view_tie["is_tie"])
        self.assertTrue(view_tie["rubbers"])
        for rid in list(ti.sub_match_ids):
            self.svc.record_result(did, rid, [[21, 5], [21, 5]])
            if br.matches[ti.id].result and br.matches[ti.id].result.winner:
                break
        # This first-round tie is decided and its winner advanced in the draw.
        self.assertEqual(br.matches[ti.id].result.winner, ti.side1)

    def test_league_standings(self):
        r = self.svc.commit_teams({**OPTS, "format": "round_robin",
                                   "template": {"events": ["XD", "MS"],
                                                "rank_by": "league_points"}})
        did = r["id"]
        self.svc.generate_bracket(did, "round_robin")
        view = self.svc.bracket_view(did)
        self.assertTrue(view["standings"])
        rows = view["standings"][0]["rows"]
        self.assertIn("league_points", rows[0])
        self.assertIn("rubbers_for", rows[0])

    def test_clear_import_wipes_teams(self):
        r = self.svc.commit_teams(OPTS)
        self.svc.generate_bracket(r["id"], "single_elim")
        self.assertTrue(self.svc.t.teams)
        self.svc.clear("import")
        self.assertEqual(self.svc.t.teams, {})        # team rosters gone
        self.assertEqual(self.svc.t.divisions, {})
        self.assertEqual(self.svc.t.brackets, {})
        self.assertEqual(self.svc.t.players, {})

    def test_clear_divisions_wipes_teams_keeps_players(self):
        n_players = len(self.svc.t.players)
        r = self.svc.commit_teams(OPTS)
        self.svc.clear("divisions")
        self.assertEqual(self.svc.t.teams, {})        # teams cleared
        self.assertEqual(len(self.svc.t.players), n_players)  # players kept

    def test_plan_shows_rubbers_and_scoring(self):
        r = self.svc.commit_teams(OPTS)
        plan = self.svc.plan_division(r["id"], start="13:45", end="18:05", court_count=4)
        self.assertTrue(plan["team"])
        self.assertIn("team_format", plan)
        self.assertTrue(plan["scoring_note"])
        fmts = {o["format"] for o in plan["options"]}
        self.assertTrue({"single_elim", "round_robin"} <= fmts)
        for o in plan["options"]:
            if o["ok"]:
                self.assertIn("scoring", o)             # each card describes scoring
        se = next(o for o in plan["options"] if o["format"] == "single_elim")
        first_tie = se["preview"]["rounds"][0]["matches"][0]
        self.assertTrue(first_tie["is_tie"])
        self.assertTrue(first_tie["rubbers"])           # rubbers shown, not bare teams
        self.assertGreater(se["duration_min"], 0)       # real estimate, not 0

    def test_scoring_change_preserves_scores(self):
        # Changing the ranking/point system (same events) must NOT wipe rubber
        # results already entered.
        r = self.svc.commit_teams({**OPTS, "format": "round_robin"})
        did = r["id"]
        self.svc.generate_bracket(did, "round_robin")
        br = self.svc.t.brackets[did]
        rubber = next(m for m in br.matches.values() if m.bracket_part == "rubber")
        self.svc.record_result(did, rubber.id, [[21, 10], [21, 10]])
        self.assertIsNotNone(br.matches[rubber.id].result)
        # Switch ranking to league points (same events) -> score kept.
        self.svc.set_team_format(did, {"events": OPTS["template"]["events"],
                                       "rank_by": "league_points"})
        self.assertIsNotNone(self.svc.t.brackets[did].matches[rubber.id].result)

    def test_points_league_ranking(self):
        r = self.svc.commit_teams({**OPTS, "format": "round_robin",
                                   "template": {"events": ["XD", "MS"],
                                                "rank_by": "points"}})
        self.svc.generate_bracket(r["id"], "round_robin")
        rows = self.svc.bracket_view(r["id"])["standings"][0]["rows"]
        self.assertIn("points_for", rows[0])
        # ranked by points -> first row has the most points_for
        self.assertEqual(rows[0]["points_for"], max(x["points_for"] for x in rows))

    def test_quick_match_length_single_game(self):
        r = self.svc.commit_teams(OPTS)
        self.svc.set_team_format(r["id"], {"events": OPTS["template"]["events"],
                                           "match_length": "quick"})
        self.svc.generate_bracket(r["id"], "single_elim")
        tie = self.svc.bracket_view(r["id"])["rounds"][0]["matches"][0]
        self.assertEqual(tie["rubbers"][0]["max_games"], 1)

    def test_team_1_seeded_first(self):
        r = self.svc.commit_teams(OPTS)
        did = r["id"]
        view = self.svc.generate_bracket(did, "single_elim")
        # Seeds are team-number order: seed 1 is Team 1.
        self.assertEqual(view["seeds"][0]["label"], "Team 1")

    def test_teams_have_colors_in_view(self):
        r = self.svc.commit_teams(OPTS)
        self.svc.generate_bracket(r["id"], "single_elim")
        tie = self.svc.bracket_view(r["id"])["rounds"][0]["matches"][0]
        self.assertIn("color", tie["side1"])
        self.assertIn("color", tie["side2"])

    def test_queue_lists_rubbers(self):
        r = self.svc.commit_teams(OPTS)
        self.svc.generate_bracket(r["id"], "single_elim")
        for item in self.svc.bracket_view(r["id"])["queue"]["ready"]:
            self.assertIn("-r", item["id"])       # rubbers, not ties


if __name__ == "__main__":
    unittest.main()


class TestTeamSources(unittest.TestCase):
    """by_club and manual rosters: the team count comes from the roster."""

    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.svc = TournamentService(Repository(os.path.join(self.d.name, "t.json")))
        t = self.svc.t
        for club in ("Alpha", "Beta"):
            for i in range(4):
                pid = "%s%d" % (club[0].lower(), i)
                t.players[pid] = Player(id=pid, first=club, last=str(i), gender="M",
                                        skill=5, events=["MS"], club=club)

    def tearDown(self):
        self.d.cleanup()

    def opts(self, **kw):
        o = {"team_type": "open", "num_teams": 4, "rng_seed": 1,
             "template": {"events": ["MS"]}, "label": "Clubs"}
        o.update(kw)
        return o

    def test_by_club_does_not_report_a_team_count_shortfall(self):
        pv = self.svc.team_preview(self.opts(method="by_club"))
        self.assertEqual([t["name"] for t in pv["teams"]], ["Alpha", "Beta"])
        self.assertFalse([w for w in pv["report"]["warnings"] if "can be formed" in w])

    def test_manual_does_not_report_a_team_count_shortfall(self):
        pv = self.svc.team_preview(self.opts(
            method="manual", manual={"Reds": ["player:a0", "player:a1"],
                                     "Blues": ["player:b0", "player:b1"]}))
        self.assertEqual([t["name"] for t in pv["teams"]], ["Reds", "Blues"])
        self.assertFalse([w for w in pv["report"]["warnings"] if "can be formed" in w])

    def test_empty_event_is_an_error_not_empty_teams(self):
        with self.assertRaises(ValueError):
            self.svc.team_preview(self.opts(template={"events": ["XD"]}))
