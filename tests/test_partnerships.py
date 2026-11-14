"""Partnerships on the import page: who is paired with whom per event, and
letting the organizer fix a one-sided request or hand someone a partner before
anything is drawn.

The table reads the *registrations* (what people asked for), so a request that
nobody answered is visible and editable, not just a validation note.
"""

import os
import tempfile
import unittest

from tournament.model.entities import (PartnerHint, Player, RegistrationEntry)
from tournament.server.service import Conflict, TournamentService
from tournament.store.repository import Repository


def make_service():
    d = tempfile.TemporaryDirectory()
    svc = TournamentService(Repository(os.path.join(d.name, "t.json")))
    return d, svc


def add_player(t, pid, first, last, gender, events, skill=5, willing=True):
    t.players[pid] = Player(id=pid, first=first, last=last, gender=gender,
                            skill=skill, events=list(events),
                            willing_random=willing)
    t.registrations.append(RegistrationEntry(row_index=-1, player_id=pid))
    return t.players[pid]


def asks(t, player_id, partner_id, event):
    """Record that ``player_id`` named ``partner_id`` for ``event``."""
    reg = next(r for r in t.registrations if r.player_id == player_id)
    reg.partner_hints.append(PartnerHint(raw_name=t.players[partner_id].full,
                                         event_hint=event,
                                         resolved_player_id=partner_id,
                                         confidence=1.0))


def roster(t):
    add_player(t, "m0", "Ann", "Alpha", "F", ["MD", "XD"], 6)
    add_player(t, "m1", "Bea", "Beta", "F", ["MD", "XD"], 7)
    add_player(t, "m2", "Cal", "Gamma", "M", ["MD", "XD"], 8)
    add_player(t, "m3", "Dee", "Delta", "M", ["MD", "XD"], 9)
    add_player(t, "m4", "Eve", "Epsilon", "M", ["MD"], 4)


def event(view, code):
    return next(e for e in view["events"] if e["event"] == code)


def row(view, code, player_id):
    return next(r for r in event(view, code)["rows"]
                if r["player"]["id"] == player_id)


class TestPartnershipView(unittest.TestCase):
    def setUp(self):
        self.d, self.svc = make_service()
        roster(self.svc.t)

    def tearDown(self):
        self.d.cleanup()

    def test_one_row_per_player_with_their_partner(self):
        view = self.svc.partnerships_view()
        md = event(view, "MD")
        self.assertEqual(len(md["rows"]), 5)
        self.assertEqual(md["paired"], 0)
        self.assertEqual(md["open"], 5)
        self.assertTrue(all(r["partner"] is None for r in md["rows"]))

    def test_mutual_request_shows_as_agreed(self):
        asks(self.svc.t, "m0", "m1", "MD")
        asks(self.svc.t, "m1", "m0", "MD")
        view = self.svc.partnerships_view()
        self.assertEqual(row(view, "MD", "m0")["status"], "agreed")
        self.assertEqual(row(view, "MD", "m1")["partner"]["id"], "m0")

    def test_one_sided_request_is_waiting_for_the_asker_and_incoming_for_the_other(self):
        asks(self.svc.t, "m2", "m3", "MD")
        view = self.svc.partnerships_view()
        mine = row(view, "MD", "m2")
        theirs = row(view, "MD", "m3")
        self.assertEqual(mine["status"], "waiting")
        self.assertEqual(mine["partner"]["id"], "m3")
        self.assertIn("has not named", mine["note"])
        self.assertEqual(theirs["status"], "incoming")
        self.assertEqual(theirs["partner"]["id"], "m2")
        self.assertIn("asked for", theirs["note"])

    def test_candidates_are_split_into_in_event_and_elsewhere(self):
        self.svc.t.players["m4"].events = ["MD"]
        md = event(self.svc.partnerships_view(), "MD")
        xd_only = add_player(self.svc.t, "w9", "Willa", "Omega", "F", ["WD"])
        del xd_only
        md = event(self.svc.partnerships_view(), "MD")
        cand = next(c for c in md["candidates"] if c["id"] == "w9")
        self.assertFalse(cand["entered"])
        self.assertTrue(next(c for c in md["candidates"] if c["id"] == "m0")["entered"])

    def test_gender_rule_note_on_a_proposed_pair(self):
        asks(self.svc.t, "m0", "m2", "MD")      # a woman paired with a man in MD
        mine = row(self.svc.partnerships_view(), "MD", "m0")
        self.assertIn("two men", mine["issue"])

    def test_a_request_to_someone_already_paired_is_blocked(self):
        self.svc.partnership_assign("MD", "m2", "m3")
        asks(self.svc.t, "m0", "m2", "MD")
        mine = row(self.svc.partnerships_view(), "MD", "m0")
        self.assertEqual(mine["status"], "blocked")
        self.assertIn("already paired", mine["note"])


class TestAssign(unittest.TestCase):
    def setUp(self):
        self.d, self.svc = make_service()
        roster(self.svc.t)

    def tearDown(self):
        self.d.cleanup()

    def test_assign_pairs_both_and_settles_the_paperwork(self):
        asks(self.svc.t, "m0", "m1", "MD")       # one-sided before the fix
        r = self.svc.partnership_assign("MD", "m0", "m1")
        md = event(r["view"], "MD")
        self.assertEqual(md["paired"], 1)
        self.assertEqual(row(r["view"], "MD", "m0")["status"], "paired")
        self.assertEqual(row(r["view"], "MD", "m1")["partner"]["id"], "m0")
        # every note and request about the pair is quiet now
        codes = [i["code"] for i in self.svc.validation()["issues"]]
        self.assertNotIn("one_sided_partner", codes)
        # the choice survives a rebuild
        self.svc.build_divisions()
        div = next(d for d in self.svc.t.divisions.values() if d.event == "MD")
        self.assertIn("pair", [ref.kind for ref in div.entry_refs])

    def test_assign_adds_the_event_to_a_partner_who_had_not_entered_it(self):
        r = self.svc.partnership_assign("XD", "m3", "m4")   # m4 only entered MD
        self.assertIn("XD", self.svc.t.players["m4"].events)
        self.assertTrue(any("added XD" in n for n in r["notes"]))
        self.assertEqual(row(r["view"], "XD", "m4")["status"], "paired")
        codes = [i["code"] for i in self.svc.validation()["issues"]]
        self.assertNotIn("partner_not_entered", codes)

    def test_taking_a_partner_frees_the_person_they_were_with(self):
        self.svc.partnership_assign("MD", "m0", "m1")
        r = self.svc.partnership_assign("MD", "m0", "m2")
        self.assertEqual(row(r["view"], "MD", "m0")["partner"]["id"], "m2")
        self.assertEqual(row(r["view"], "MD", "m1")["status"], "open")
        self.assertTrue(any("unpaired" in n for n in r["notes"]))
        self.assertEqual(event(r["view"], "MD")["paired"], 1)

    def test_a_player_cannot_partner_with_themselves(self):
        with self.assertRaises(ValueError):
            self.svc.partnership_assign("MD", "m0", "m0")

    def test_a_placeholder_cannot_be_assigned(self):
        self.svc.t.players["stub"] = Player(id="stub", first="Ghost", last="Player",
                                            is_stub=True, events=["MD"])
        with self.assertRaises(ValueError):
            self.svc.partnership_assign("MD", "m0", "stub")

    def test_assign_rebuilds_divisions_that_already_exist(self):
        self.svc.build_divisions()
        r = self.svc.partnership_assign("MD", "m0", "m1")
        self.assertTrue(r["rebuilt"])
        div = next(d for d in self.svc.divisions() if d["event"] == "MD")
        self.assertEqual(div["entries"], 1)

    def test_partnerships_are_locked_once_a_bracket_exists(self):
        self.svc.build_divisions()
        div = next(d for d in self.svc.divisions() if d["event"] == "MD")
        self.svc.generate_bracket(div["id"], "single_elim")
        self.assertFalse(self.svc.partnerships_view()["editable"])
        with self.assertRaises(Conflict):
            self.svc.partnership_assign("MD", "m0", "m1")


class TestClear(unittest.TestCase):
    def setUp(self):
        self.d, self.svc = make_service()
        roster(self.svc.t)

    def tearDown(self):
        self.d.cleanup()

    def test_clear_removes_the_pair_and_both_requests(self):
        self.svc.partnership_assign("MD", "m0", "m1")
        r = self.svc.partnership_clear("MD", "m0")
        self.assertEqual(event(r["view"], "MD")["paired"], 0)
        self.assertEqual(row(r["view"], "MD", "m1")["status"], "open")
        # nothing left that would pair them again at build time
        codes = [i["code"] for i in self.svc.validation()["issues"]]
        self.assertNotIn("one_sided_partner", codes)
        self.assertEqual(self.svc.t.pairs, {})
        # no request is left that would pair them again at build time
        self.assertEqual([h for r in self.svc.t.registrations
                          for h in r.partner_hints if h.event_hint == "MD"], [])

    def test_clear_drops_a_one_sided_request(self):
        asks(self.svc.t, "m0", "m1", "MD")
        r = self.svc.partnership_clear("MD", "m0")
        self.assertEqual(row(r["view"], "MD", "m0")["status"], "open")
        self.assertEqual(row(r["view"], "MD", "m1")["status"], "open")


class TestOnePairEditor(unittest.TestCase):
    """Both pair views read one dataset: any write keeps the roster pairs and
    the registrations in step, so the table and the pair list cannot disagree."""

    def setUp(self):
        self.d, self.svc = make_service()
        roster(self.svc.t)

    def tearDown(self):
        self.d.cleanup()

    def assert_views_agree(self, code):
        pairs = event(self.svc.pairs_view(), code)
        part = event(self.svc.partnerships_view(), code)
        from_pairs = sorted(tuple(sorted(p["players"][i]["id"] for i in (0, 1)))
                            for p in pairs["pairs"])
        from_table = sorted({tuple(sorted((r["player"]["id"], r["partner"]["id"])))
                             for r in part["rows"] if r["status"] == "paired"})
        self.assertEqual(from_pairs, from_table)
        self.assertEqual(sorted(p["id"] for p in pairs["unpaired"]),
                         sorted(r["player"]["id"] for r in part["rows"]
                                if r["status"] != "paired"))

    def test_setting_pairs_records_them_both_ways(self):
        self.svc.pairs_set("MD", [["m0", "m1"]])
        view = self.svc.partnerships_view()
        self.assertEqual(row(view, "MD", "m0")["status"], "paired")
        self.assertEqual(row(view, "MD", "m2")["status"], "open")
        self.assertNotIn("waiting", {r["status"] for r in event(view, "MD")["rows"]})
        self.assert_views_agree("MD")

    def test_a_shuffle_does_not_leave_a_stale_request_behind(self):
        asks(self.svc.t, "m0", "m1", "MD")      # will not survive the shuffle
        self.svc.pairs_shuffle("MD", 3)
        view = self.svc.partnerships_view()
        self.assertNotIn("waiting", {r["status"] for r in event(view, "MD")["rows"]})
        self.assertEqual(event(view, "MD")["paired"], 1)   # the three men
        self.assert_views_agree("MD")

    def test_re_pair_from_forms_matches_what_the_table_shows(self):
        asks(self.svc.t, "m0", "m1", "MD")
        asks(self.svc.t, "m1", "m0", "MD")
        self.svc.pairs_auto("MD")
        view = self.svc.partnerships_view()
        self.assertEqual(row(view, "MD", "m0")["partner"]["id"], "m1")
        self.assertEqual(row(view, "MD", "m0")["status"], "paired")
        self.assert_views_agree("MD")

    def test_unpairing_in_the_table_is_visible_to_the_pair_list(self):
        self.svc.partnership_assign("MD", "m0", "m1")
        self.svc.partnership_clear("MD", "m0")
        pairs = event(self.svc.pairs_view(), "MD")
        self.assertEqual(pairs["pairs"], [])
        self.assert_views_agree("MD")


class TestPreviewEdits(unittest.TestCase):
    def test_partnership_edits_work_on_an_open_import_preview(self):
        d, svc = make_service()
        try:
            path = os.path.join(os.path.dirname(__file__), "..", "sample_data",
                                "legacy_mixed.csv")
            svc.import_preview("file", os.path.abspath(path))
            view = svc.partnerships_view()
            code = view["events"][0]["event"]
            first = event(view, code)["rows"][0]["player"]["id"]
            second = event(view, code)["rows"][1]["player"]["id"]
            r = svc.partnership_assign(code, first, second)
            self.assertEqual(row(r["view"], code, first)["status"], "paired")
            # the committed tournament is untouched until Commit
            self.assertEqual(len(Repository(os.path.join(d.name, "t.json")).load().players), 0)
        finally:
            d.cleanup()


if __name__ == "__main__":
    unittest.main()
