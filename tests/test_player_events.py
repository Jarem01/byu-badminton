"""Editing which events a player is entered in, from the players table.

Filling a spot nobody signed up for (or taking back an entry) has to be a
deliberate, audited edit, and it must not leave a pair behind in an event its
player is no longer in.
"""

import os
import tempfile
import unittest

from tournament.model.entities import Bracket, Division
from tournament.server.service import Conflict, TournamentService
from tournament.store.repository import Repository

from .test_partnerships import add_player, make_service, row


def event(view, code):
    return next(e for e in view["events"] if e["event"] == code)


class TestPlayerEvents(unittest.TestCase):
    def setUp(self):
        self.d, self.svc = make_service()
        self.t = self.svc.t
        add_player(self.t, "p0", "Ann", "Alpha", "F", ["MD"], 6)
        add_player(self.t, "p1", "Bea", "Beta", "M", ["MD"], 7)
        add_player(self.t, "p2", "Cal", "Gamma", "M", [], 8)

    def tearDown(self):
        self.d.cleanup()

    def test_add_an_event_to_fill_a_spot(self):
        out = self.svc.player_events("p2", ["MD"])

        self.assertEqual(self.t.players["p2"].events, ["MD"])
        self.assertEqual(out["notes"], ["added MD"])
        self.assertEqual(self.t.players["p0"].events, ["MD"])    # untouched
        # and the partnerships table now lists them in that event
        self.assertIsNotNone(row(out["view"], "MD", "p2"))
        # every edit is audited with before and after
        lines = [r for r in self.svc.repo.read_audit()
                 if r["target"] == "player:p2" and r["field_name"] == "events"]
        self.assertEqual([(r["old_value"], r["new_value"]) for r in lines],
                         [("", "MD")])   # no events -> "MD"

    def test_remove_an_event(self):
        out = self.svc.player_events("p0", [])

        self.assertEqual(self.t.players["p0"].events, [])
        self.assertEqual(out["notes"], ["removed MD"])
        self.assertEqual([r["player"]["id"] for r in event(out["view"], "MD")["rows"]],
                         ["p1"])

    def test_codes_are_validated_and_normalised(self):
        self.svc.player_events("p2", ["xd", " MS ", "XD"])
        self.assertEqual(self.t.players["p2"].events, ["MS", "XD"])
        with self.assertRaises(ValueError):
            self.svc.player_events("p2", ["XX"])
        self.assertEqual(self.t.players["p2"].events, ["MS", "XD"])
        with self.assertRaises(ValueError):
            self.svc.player_events("nobody", ["MD"])

    def test_removing_an_event_they_are_paired_in_is_refused(self):
        self.svc.partnership_assign("MD", "p0", "p1")

        with self.assertRaises(Conflict):
            self.svc.player_events("p0", [])
        self.assertEqual(self.t.players["p0"].events, ["MD"])
        self.assertEqual(self.t.players["p1"].events, ["MD"])
        self.assertFalse([r for r in self.svc.repo.read_audit()
                          if r["target"] == "player:p0"
                          and r["field_name"] == "events"])

        # unpair first, then the entry can go
        self.svc.partnership_clear("MD", "p0")
        self.svc.player_events("p0", [])
        self.assertEqual(self.t.players["p0"].events, [])

    def draw_bracket(self, division_id, code):
        self.t.divisions[division_id] = Division(id=division_id, event=code,
                                                 label=code + " A")
        self.t.brackets[division_id] = Bracket(division_id=division_id,
                                               format="single_elim")

    def test_adding_to_an_event_with_a_drawn_bracket_is_refused(self):
        self.draw_bracket("md-a", "MD")

        with self.assertRaises(Conflict) as caught:
            self.svc.player_events("p2", ["MD"])
        self.assertIn("bracket", str(caught.exception))
        self.assertIn("MD", str(caught.exception))
        self.assertEqual(self.t.players["p2"].events, [])
        self.assertFalse([r for r in self.svc.repo.read_audit()
                          if r["target"] == "player:p2"
                          and r["field_name"] == "events"])

    def test_removing_from_an_event_with_a_drawn_bracket_is_refused(self):
        self.draw_bracket("md-a", "MD")

        with self.assertRaises(Conflict) as caught:
            self.svc.player_events("p0", [])
        self.assertIn("bracket", str(caught.exception))
        self.assertEqual(self.t.players["p0"].events, ["MD"])

    def test_other_events_stay_editable_when_one_bracket_is_drawn(self):
        self.draw_bracket("md-a", "MD")

        out = self.svc.player_events("p2", ["XD"])     # XD has no bracket

        self.assertEqual(out["events"], ["XD"])
        self.assertEqual(out["notes"], ["added XD"])
        # and a no-op edit on the bracketed event is harmless
        self.svc.player_events("p0", ["MD"])
        self.assertEqual(self.t.players["p0"].events, ["MD"])

    def test_the_edit_survives_a_reload(self):
        self.svc.player_events("p2", ["WD", "XD"])
        again = TournamentService(self.svc.repo)
        self.assertEqual(again.t.players["p2"].events, ["WD", "XD"])

    def test_the_edit_lands_in_the_import_preview(self):
        path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..",
                                            "sample_data", "legacy_mixed.csv"))
        self.svc.import_preview("file", path)
        someone = self.svc.players()[0]
        before = list(someone["events"])
        new = before + ["MS"] if "MS" not in before else ["WS"]

        out = self.svc.player_events(someone["id"], new)

        self.assertEqual(out["events"], new)
        self.assertIsNone(self.t.players.get(someone["id"]))    # committed untouched
        self.assertEqual(self.svc.repo.load().players, {})
        self.assertTrue(out["view"]["editable"])                # preview stays editable
