"""Merging duplicate players: one form row typed twice, or a misspelt name.

Merging folds the duplicate's registrations, partner requests, pairs and events
into the survivor and removes the duplicate. It refuses when that would leave
inconsistent data -- both entries paired in one event, or a bracket already
drawn for an event the merge touches.
"""

import os
import tempfile
import unittest

from tournament.model.entities import Bracket, Division
from tournament.server.service import Conflict, TournamentService
from tournament.store.repository import Repository

from .test_partnerships import add_player, asks, make_service, row


def event(view, code):
    return next(e for e in view["events"] if e["event"] == code)


class TestMergePlayers(unittest.TestCase):
    def setUp(self):
        self.d, self.svc = make_service()
        self.t = self.svc.t
        # the same person entered twice, the second time with a typo
        add_player(self.t, "keep", "Amy", "Nguyen", "F", ["MD"], 7)
        add_player(self.t, "drop", "Amy", "Nguyen", "F", ["XD"], 7)
        self.t.players["keep"].email = "amy@example.com"
        self.t.players["drop"].email = "amy@example.com"
        add_player(self.t, "p1", "Bea", "Beta", "M", ["MD", "XD"], 6)
        add_player(self.t, "p2", "Cal", "Gamma", "M", ["XD"], 5)
        # p1 asked for the typo'd name
        asks(self.t, "p1", "drop", "XD")      # by player id
        asks(self.t, "keep", "p1", "MD")      # the survivor's own request
        asks(self.t, "drop", "p2", "XD")      # and the duplicate's

    def tearDown(self):
        self.d.cleanup()

    def events_of(self, pid):
        return [e for e in self.t.players[pid].events]

    def test_merge_folds_events_registrations_requests_and_pairs(self):
        self.svc.partnership_assign("XD", "drop", "p2")

        out = self.svc.merge_players("keep", "drop")

        self.assertNotIn("drop", self.t.players)
        self.assertEqual(self.events_of("keep"), ["MD", "XD"])
        # one registration, holding both sets of partner requests
        regs = [r for r in self.t.registrations if r.player_id == "keep"]
        self.assertEqual(len(regs), 1)
        self.assertFalse([r for r in self.t.registrations if r.player_id == "drop"])
        self.assertEqual(sorted((h.event_hint, h.resolved_player_id)
                                for h in regs[0].partner_hints),
                         [("MD", "p1"), ("XD", "p2")])
        # the XD pair now belongs to the survivor
        self.assertEqual(row(out["view"], "XD", "keep")["partner"]["id"], "p2")
        self.assertTrue(any("took over their request" in n for n in out["notes"]))

    def test_a_request_pointing_at_the_duplicate_is_repointed(self):
        self.svc.merge_players("keep", "drop")

        p1_hints = [h for r in self.t.registrations if r.player_id == "p1"
                    for h in r.partner_hints]
        self.assertEqual([h.resolved_player_id for h in p1_hints], ["keep"])
        self.assertEqual(self.svc.partnerships_view()["events"][0]["event"], "MD")

    def test_merge_is_audited_both_ways(self):
        self.svc.merge_players("keep", "drop")

        log = self.svc.repo.read_audit()
        merged = [r for r in log if r["field_name"] == "merged_from"]
        gone = [r for r in log if r["field_name"] == "merged_into"]
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["target"], "player:keep")
        self.assertIn("Amy Nguyen", merged[0]["new_value"])
        self.assertIn("drop", merged[0]["new_value"])
        self.assertEqual(len(gone), 1)
        self.assertEqual(gone[0]["target"], "player:drop")
        self.assertIn("Amy Nguyen", gone[0]["new_value"])

    def test_refuses_when_both_are_paired_in_the_same_event(self):
        self.svc.partnership_assign("XD", "drop", "p2")
        self.svc.partnership_assign("XD", "keep", "p1")

        with self.assertRaises(Conflict) as caught:
            self.svc.merge_players("keep", "drop")
        self.assertIn("both paired in XD", str(caught.exception))
        self.assertIn("drop", self.t.players)
        self.assertEqual(self.events_of("drop"), ["XD"])

    def test_refuses_while_a_bracket_is_drawn_for_a_touched_event(self):
        self.t.divisions["md-a"] = Division(id="md-a", event="MD", label="MD A")
        self.t.brackets["md-a"] = Bracket(division_id="md-a", format="single_elim")

        with self.assertRaises(Conflict) as caught:
            self.svc.merge_players("keep", "drop")
        self.assertIn("MD", str(caught.exception))
        self.assertIn("bracket", str(caught.exception))
        self.assertIn("drop", self.t.players)

    def test_an_unrelated_bracket_does_not_block_the_merge(self):
        self.t.divisions["ws-a"] = Division(id="ws-a", event="WS", label="WS A")
        self.t.brackets["ws-a"] = Bracket(division_id="ws-a", format="single_elim")

        self.svc.merge_players("keep", "drop")
        self.assertNotIn("drop", self.t.players)

    def test_partners_with_each_other_lose_the_pair(self):
        self.svc.partnership_assign("XD", "drop", "keep")

        out = self.svc.merge_players("keep", "drop")

        self.assertNotIn("drop", self.t.players)
        self.assertEqual([pr for pr in self.t.pairs.values() if pr.event == "XD"], [])
        self.assertTrue(any("they were partners" in n for n in out["notes"]))

    def test_singles_entries_follow_the_survivor(self):
        from tournament.model.entities import EntryRef
        add_player(self.t, "keep2", "Dee", "Delta", "F", ["WS"], 6)
        add_player(self.t, "drop2", "Dee", "Deltta", "F", ["WS"], 6)
        self.t.divisions["ws-a"] = Division(id="ws-a", event="WS", label="WS A",
                                           entry_refs=[EntryRef("player", "keep2"),
                                                       EntryRef("player", "drop2")])

        self.svc.merge_players("keep2", "drop2")

        refs = self.t.divisions["ws-a"].entry_refs
        self.assertEqual([r.key() for r in refs], ["player:keep2"])

    def test_the_merge_survives_a_reload(self):
        self.svc.partnership_assign("XD", "drop", "p2")
        self.svc.merge_players("keep", "drop")

        again = TournamentService(self.svc.repo)
        self.assertNotIn("drop", again.t.players)
        self.assertEqual(sorted(again.t.players["keep"].events), ["MD", "XD"])
        self.assertEqual(len([pr for pr in again.t.pairs.values()
                              if "keep" in pr.player_ids]), 1)

    def test_duplicate_warnings_carry_the_players_for_the_buttons(self):
        val = self.svc.validation()
        dup = [i for i in val["issues"] if i["code"] == "duplicate_email"]
        self.assertEqual(len(dup), 1)
        ids = [p["id"] for p in dup[0]["data"]["players"]]
        self.assertEqual(sorted(ids), ["drop", "keep"])
        names = [p["name"] for p in dup[0]["data"]["players"]]
        self.assertIn("Amy Nguyen", names)

    def test_merging_lands_in_the_import_preview(self):
        path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..",
                                            "sample_data", "legacy_mixed.csv"))
        self.svc.import_preview("file", path)
        people = self.svc.players()
        first, second = people[0]["id"], people[1]["id"]
        survivors = len(people) - 1

        out = self.svc.merge_players(first, second)

        self.assertEqual(len(out["players"]), survivors)
        self.assertNotIn(second, [p["id"] for p in out["players"]])
        self.assertEqual(self.svc.repo.load().players, {})   # committed untouched


if __name__ == "__main__":
    unittest.main()
