"""Manual pair editing: check the pairings, move players, shuffle, re-pair.

The pairs editor is what lets an organizer fix the import -- "Ann is with Bea,
not Carol" -- before any bracket is drawn.
"""

import os
import tempfile
import unittest

from tournament.model.entities import Player
from tournament.server.service import Conflict, TournamentService
from tournament.store.repository import Repository


def roster(svc, men=8, women=2):
    t = svc.t
    for i in range(men):
        t.players[f"m{i}"] = Player(id=f"m{i}", first="Man", last=str(i), gender="M",
                                    skill=5, events=["MD", "XD"], willing_random=True)
    for i in range(women):
        t.players[f"w{i}"] = Player(id=f"w{i}", first="Woman", last=str(i), gender="F",
                                    skill=5, events=["WD", "XD"], willing_random=True)


class TestPairsView(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.svc = TournamentService(Repository(os.path.join(self.d.name, "t.json")))
        roster(self.svc)

    def tearDown(self):
        self.d.cleanup()

    def event(self, view, code):
        return next(e for e in view["events"] if e["event"] == code)

    def test_lists_pairs_and_unpaired_players(self):
        view = self.svc.pairs_view()
        md = self.event(view, "MD")
        self.assertEqual(md["players"], 8)
        self.assertEqual(md["pairs"], [])            # nothing paired yet
        self.assertEqual(len(md["unpaired"]), 8)
        self.assertTrue(view["editable"])

    def test_set_pairs_moves_players_and_reports_gender_rule(self):
        # a woman entered in MD (the messy import does this) can be paired but
        # the editor flags the gender rule rather than refusing the edit
        self.svc.t.players["w0"].events = ["MD", "WD", "XD"]
        r = self.svc.pairs_set("MD", [["m0", "m1"], ["w0", "m2"], ["m3"]])
        md = self.event(r["view"], "MD")
        labels = sorted(p["label"] for p in md["pairs"])
        self.assertEqual(labels, ["Man 0 / Man 1", "Woman 0 / Man 2"])
        issue = next(p["issue"] for p in md["pairs"] if "Woman 0" in p["label"])
        self.assertIn("two men", issue)
        self.assertEqual([u["id"] for u in md["unpaired"]], ["m3", "m4", "m5", "m6", "m7"])

    def test_duplicate_player_is_refused(self):
        with self.assertRaises(ValueError):
            self.svc.pairs_set("MD", [["m0", "m1"], ["m0", "m2"]])

    def test_player_not_entered_in_event_is_refused(self):
        with self.assertRaises(ValueError):
            self.svc.pairs_set("WD", [["m0", "m1"]])


class TestPairChanges(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.svc = TournamentService(Repository(os.path.join(self.d.name, "t.json")))
        roster(self.svc)

    def tearDown(self):
        self.d.cleanup()

    def test_shuffle_keeps_gender_rules(self):
        self.svc.pairs_shuffle("MD", 2)
        md = next(e for e in self.svc.pairs_view()["events"] if e["event"] == "MD")
        for pair in md["pairs"]:
            self.assertEqual([p["gender"] for p in pair["players"]], ["M", "M"])
        self.assertEqual(len(md["unpaired"]), 0)

    def test_shuffle_leaves_the_odd_xd_player_out(self):
        # 8 men + 2 women: 2 mixed pairs, 6 men with no partner.
        self.svc.pairs_shuffle("XD", 1)
        xd = next(e for e in self.svc.pairs_view()["events"] if e["event"] == "XD")
        self.assertEqual(len(xd["pairs"]), 2)
        self.assertEqual(len(xd["unpaired"]), 6)
        for pair in xd["pairs"]:
            self.assertEqual(sorted(p["gender"] for p in pair["players"]), ["F", "M"])

    def test_rebuild_keeps_the_pairs_that_were_set(self):
        self.svc.pairs_set("MD", [["m0", "m1"], ["m2", "m3"]])
        built = self.svc.build_divisions()
        md = next(d for d in built["divisions"] if d["event"] == "MD")
        # the two hand-made pairs stay; willing leftovers are still auto-paired
        self.assertEqual(md["entries"], 4)
        view = self.svc.pairs_view()
        labels = sorted(p["label"] for p in
                        next(e for e in view["events"] if e["event"] == "MD")["pairs"])
        self.assertEqual(labels[:2], ["Man 0 / Man 1", "Man 2 / Man 3"])

    def test_editing_pairs_rebuilds_existing_divisions(self):
        self.svc.build_divisions()
        before = [d for d in self.svc.divisions() if d["event"] == "MD"][0]
        self.assertTrue(before["entries"] >= 4)
        r = self.svc.pairs_set("MD", [["m0", "m1"]])
        self.assertTrue(r["rebuilt"])
        after = [d for d in self.svc.divisions() if d["event"] == "MD"][0]
        self.assertEqual(after["entries"], 1)       # only the pair that was kept

    def test_pairs_are_locked_once_a_bracket_exists(self):
        self.svc.build_divisions()
        div = next(d for d in self.svc.divisions() if d["event"] == "MD")
        self.svc.generate_bracket(div["id"], "single_elim")
        self.assertFalse(self.svc.pairs_view()["editable"])
        with self.assertRaises(Conflict):
            self.svc.pairs_set("MD", [["m0", "m1"]])

    def test_a_custom_division_survives_a_pair_rebuild(self):
        custom = self.svc.create_custom_division(
            "Friday Social", "player", ["Zed One", "Yan Two", "Xia Three"], "MS")
        self.svc.build_divisions()
        r = self.svc.pairs_set("MD", [["m0", "m1"]])
        self.assertTrue(r["rebuilt"])
        ids = [d["id"] for d in self.svc.divisions()]
        self.assertIn(custom["id"], ids)             # hand-made bracket kept
        self.assertIn("div-md", ids)                 # built one re-created

    def test_building_divisions_keeps_a_custom_division(self):
        custom = self.svc.create_custom_division(
            "Friday Social", "player", ["Zed One", "Yan Two"], "MS")
        self.svc.build_divisions()
        self.assertIn(custom["id"], [d["id"] for d in self.svc.divisions()])

    def test_auto_pairs_willing_players_from_registrations(self):
        r = self.svc.pairs_auto("MD")
        md = next(e for e in r["view"]["events"] if e["event"] == "MD")
        self.assertEqual(len(md["pairs"]), 4)
        self.assertEqual(md["unpaired"], [])


if __name__ == "__main__":
    unittest.main()
