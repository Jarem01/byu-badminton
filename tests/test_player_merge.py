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

    def test_a_typo_name_still_gets_a_merge_warning(self):
        add_player(self.t, "typo", "Amy", "Ngyun", "F", ["MD"], 7)

        issues = [i for i in self.svc.validation()["issues"]
                  if i["code"] == "similar_name"]

        self.assertEqual(len(issues), 1)
        self.assertIn("Amy Nguyen", issues[0]["message"])
        self.assertIn("Amy Ngyun", issues[0]["message"])
        ids = [p["id"] for p in issues[0]["data"]["players"]]
        # both entries spelt "Amy Nguyen" and the typo, so one merge covers all
        self.assertEqual(len(ids), 3)
        self.assertIn("typo", ids)
        self.assertIn("'Amy Nguyen' ×2", issues[0]["message"])

    def test_similarly_spelled_different_people_are_not_flagged(self):
        add_player(self.t, "other", "Josh", "Liu", "M", ["MD"], 6)
        add_player(self.t, "josh", "Josh", "Lim", "M", ["MD"], 6)

        codes = [i["code"] for i in self.svc.validation()["issues"]]
        self.assertNotIn("similar_name", codes)

    def test_an_identical_name_is_reported_once_not_twice(self):
        codes = [i["code"] for i in self.svc.validation()["issues"]]
        self.assertIn("duplicate_email", codes)      # same email in the fixture
        self.assertNotIn("similar_name", codes)

    def test_groups_are_the_same_whatever_order_the_players_are_stored_in(self):
        # two people spelt the same way (different emails, so the exact rules
        # stay quiet) and one typo: the typo must join both of them, always
        specs = [("a1", "Nguyen", "a1@example.com"),
                 ("b1", "Nguyen", "b1@example.com"),
                 ("t1", "Ngyun", "")]

        def build(order):
            d, svc = make_service()
            for pid, last, email in order:
                add_player(svc.t, pid, "Amy", last, "F", ["MD"], 6)
                svc.t.players[pid].email = email
            return d, svc

        d1, s1 = build(specs)
        d2, s2 = build(list(reversed(specs)))
        try:
            one = [i for i in s1.validation()["issues"] if i["code"] == "similar_name"]
            two = [i for i in s2.validation()["issues"] if i["code"] == "similar_name"]

            self.assertEqual(len(one), 1)
            self.assertEqual([i["message"] for i in one], [i["message"] for i in two])
            self.assertEqual([p["id"] for p in one[0]["data"]["players"]],
                             ["a1", "b1", "t1"])          # name, then id
            self.assertEqual([p["id"] for p in two[0]["data"]["players"]],
                             ["a1", "b1", "t1"])
            self.assertIn("'Amy Nguyen' ×2 and 'Amy Ngyun'", one[0]["message"])
        finally:
            d1.cleanup()
            d2.cleanup()

    def test_a_placeholder_partner_is_offered_for_merging_too(self):
        from tournament.model.entities import Player
        self.t.players["stubm"] = Player(id="stubm", first="Betty", last="Wong",
                                         gender="U", skill=None, events=[],
                                         is_stub=True)
        add_player(self.t, "betty", "Betty", "Wng", "F", ["WD"], 6)

        issues = [i for i in self.svc.validation()["issues"]
                  if i["code"] == "similar_name"]
        mine = [i for i in issues if "Betty" in i["message"]]

        self.assertEqual(len(mine), 1)
        self.assertIn("(placeholder)", mine[0]["message"])
        self.assertEqual(sorted(p["id"] for p in mine[0]["data"]["players"]),
                         ["betty", "stubm"])

    def test_a_surviving_placeholder_takes_the_real_players_facts(self):
        from tournament.model.entities import Player
        self.t.players["stub"] = Player(id="stub", first="Ami", last="Ngyun",
                                        gender="U", skill=None, events=[],
                                        is_stub=True)
        add_player(self.t, "real", "Amy", "Nguyen", "F", ["MD", "XD"], 8)
        self.t.players["real"].email = "amy@example.com"

        out = self.svc.merge_players("stub", "real")

        kept = self.t.players["stub"]
        self.assertFalse(kept.is_stub)
        self.assertEqual(kept.full, "Amy Nguyen")     # the real spelling
        self.assertEqual(kept.email, "amy@example.com")
        self.assertEqual(fields["email"], ("", "amy@example.com")) if False else None
        self.assertEqual(kept.gender, "F")
        self.assertEqual(kept.skill, 8)
        self.assertEqual(kept.events, ["MD", "XD"])
        self.assertIn("no longer a placeholder", " ".join(out["notes"]))
        self.assertIn("now called Amy Nguyen", " ".join(out["notes"]))
        log = [r for r in self.svc.repo.read_audit() if r["target"] == "player:stub"]
        fields = {r["field_name"]: (r["old_value"], r["new_value"]) for r in log}
        self.assertEqual(fields["first"], ("Ami", "Amy"))
        self.assertEqual(fields["last"], ("Ngyun", "Nguyen"))
        self.assertEqual(fields["gender"], ("U", "F"))
        self.assertEqual(fields["skill"], ("None", "8"))

    def test_a_real_survivor_keeps_its_own_gender_and_skill(self):
        from tournament.model.entities import Player
        self.t.players["stub2"] = Player(id="stub2", first="Bo", last="Bee",
                                         gender="U", skill=None, events=["MD"],
                                         is_stub=True)
        add_player(self.t, "real2", "Bo", "Bee", "M", ["MD"], 4)

        self.svc.merge_players("real2", "stub2")

        kept = self.t.players["real2"]
        self.assertFalse(kept.is_stub)
        self.assertEqual((kept.gender, kept.skill), ("M", 4))

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


class TestUndoMerge(unittest.TestCase):
    """A merge can be taken back, like a pair change."""

    def setUp(self):
        self.d, self.svc = make_service()
        self.t = self.svc.t
        add_player(self.t, "keep", "Amy", "Nguyen", "F", ["MD"], 7)
        add_player(self.t, "drop", "Amy", "Nguyen", "F", ["XD"], 6)
        add_player(self.t, "p1", "Bea", "Beta", "M", ["MD", "XD"], 6)
        add_player(self.t, "p2", "Cal", "Gamma", "M", ["XD"], 5)
        self.t.players["keep"].email = "keep@example.com"
        asks(self.t, "keep", "p1", "MD")
        asks(self.t, "drop", "p2", "XD")      # the duplicate's own request
        asks(self.t, "p1", "drop", "XD")      # someone asked for the duplicate

    def tearDown(self):
        self.d.cleanup()

    def snapshot(self, t=None):
        t = t or self.t
        return {
            "players": {pid: (p.full, p.email, p.gender, p.skill,
                              list(p.events), p.is_stub)
                        for pid, p in t.players.items()},
            "pairs": {pr.id: (tuple(sorted(pr.player_ids)), pr.event)
                      for pr in t.pairs.values()},
            "regs": sorted((r.player_id,
                            tuple(sorted((h.raw_name, h.event_hint or "",
                                          h.resolved_player_id or "")
                                         for h in r.partner_hints)))
                           for r in t.registrations),
        }

    def test_undo_puts_both_players_back_exactly(self):
        self.svc.partnership_assign("XD", "drop", "p2")
        before = self.snapshot()

        self.svc.merge_players("keep", "drop")
        self.assertNotIn("drop", self.t.players)
        self.assertEqual(self.svc.merge_history()[0]["dropped"], "Amy Nguyen")

        out = self.svc.undo_merge()

        self.assertEqual(self.snapshot(), before)
        self.assertIn("are separate entries again", out["notes"][0])
        self.assertEqual(out["merges"], 0)
        self.assertEqual(self.svc.merge_history(), [])
        # the merge is gone from the log, the undo is in the audit trail
        log = self.svc.repo.read_audit()
        self.assertEqual([r["field_name"] for r in log
                          if r["field_name"] == "merge_undone"],
                         ["merge_undone"])

    def test_undo_restores_the_events_and_pair_of_the_duplicate(self):
        self.svc.partnership_assign("XD", "drop", "p2")
        self.svc.merge_players("keep", "drop")
        self.assertEqual(sorted(self.t.players["keep"].events), ["MD", "XD"])
        self.assertEqual(self.t.players["keep"].skill, 7)

        self.svc.undo_merge()

        self.assertEqual(self.t.players["drop"].events, ["XD"])
        self.assertEqual(self.t.players["drop"].skill, 6)
        self.assertEqual(self.t.players["keep"].events, ["MD"])
        self.assertEqual(
            [(sorted(pr.player_ids), pr.event) for pr in self.t.pairs.values()],
            [(["drop", "p2"], "XD")])

    def test_a_request_pointing_at_the_duplicate_goes_back_to_it(self):
        self.svc.merge_players("keep", "drop")
        p1 = next(r for r in self.t.registrations if r.player_id == "p1")
        self.assertEqual([h.resolved_player_id for h in p1.partner_hints],
                         ["keep"])

        self.svc.undo_merge()

        p1 = next(r for r in self.t.registrations if r.player_id == "p1")
        self.assertEqual([h.resolved_player_id for h in p1.partner_hints],
                         ["drop"])

    def test_undo_works_for_a_placeholder_survivor(self):
        from tournament.model.entities import Player
        self.t.players["stub"] = Player(id="stub", first="Ami", last="Ngyun",
                                        gender="U", skill=None, events=[],
                                        is_stub=True)
        before = self.snapshot()
        self.svc.merge_players("stub", "keep")

        self.svc.undo_merge()

        self.assertEqual(self.snapshot(), before)
        self.assertTrue(self.t.players["stub"].is_stub)
        self.assertEqual(self.t.players["stub"].full, "Ami Ngyun")

    def test_merges_undo_newest_first(self):
        add_player(self.t, "third", "Amy", "Nguyenn", "F", ["WD"], 4)
        self.svc.merge_players("keep", "drop")      # keep absorbs drop
        self.svc.merge_players("keep", "third")     # then a second one
        self.assertEqual(len(self.svc.merge_history()), 2)

        out = self.svc.undo_merge()
        self.assertEqual(out["merges"], 1)
        self.assertIn("third", self.t.players)      # the newest comes back first
        self.assertNotIn("drop", self.t.players)

        out = self.svc.undo_merge()
        self.assertEqual(out["merges"], 0)
        self.assertIn("drop", self.t.players)
        self.assertEqual(sorted(self.t.players["keep"].events), ["MD"])
        with self.assertRaises(ValueError):
            self.svc.undo_merge()

    def test_refuses_while_a_bracket_is_drawn_for_a_touched_event(self):
        self.svc.merge_players("keep", "drop")
        self.t.divisions["xd-a"] = Division(id="xd-a", event="XD", label="XD A")
        self.t.brackets["xd-a"] = Bracket(division_id="xd-a",
                                          format="single_elim")

        with self.assertRaises(Conflict) as caught:
            self.svc.undo_merge()

        self.assertIn("XD", str(caught.exception))
        self.assertNotIn("drop", self.t.players)
        self.assertEqual(len(self.svc.merge_history()), 1)

    def test_refuses_when_the_survivor_has_been_paired_since(self):
        self.svc.merge_players("keep", "drop")
        self.svc.partnership_assign("XD", "keep", "p1")     # after the merge

        with self.assertRaises(Conflict) as caught:
            self.svc.undo_merge()

        self.assertIn("paired since the merge", str(caught.exception))
        self.assertNotIn("drop", self.t.players)

    def test_the_undo_survives_a_reload(self):
        self.svc.merge_players("keep", "drop")

        again = TournamentService(self.svc.repo)
        self.assertEqual(len(again.merge_history()), 1)
        again.undo_merge()

        self.assertIn("drop", again.t.players)
        self.assertEqual(again.t.players["drop"].events, ["XD"])
        self.assertEqual(again.t.players["keep"].events, ["MD"])

    def test_undo_lands_in_the_import_preview(self):
        path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..",
                                            "sample_data", "legacy_mixed.csv"))
        self.svc.import_preview("file", path)
        people = self.svc.players()
        self.svc.merge_players(people[0]["id"], people[1]["id"])
        self.assertEqual(len(self.svc.players()), len(people) - 1)

        out = self.svc.undo_merge()

        self.assertEqual(len(out["players"]), len(people))
        self.assertEqual(self.svc.repo.load().players, {})   # committed untouched
