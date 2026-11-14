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


def form_answers(t):
    """Every partner answer exactly as submitted (the registrations)."""
    return [(r.player_id, h.raw_name, h.event_hint, h.resolved_player_id,
             h.confidence)
            for r in t.registrations for h in r.partner_hints]


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

    def test_assign_pairs_both_without_touching_the_form_answers(self):
        asks(self.svc.t, "m0", "m1", "MD")       # one-sided on the form
        before = form_answers(self.svc.t)
        r = self.svc.partnership_assign("MD", "m0", "m1")
        self.assertEqual(event(r["view"], "MD")["paired"], 1)
        self.assertEqual(row(r["view"], "MD", "m1")["partner"]["id"], "m0")
        # the submitted answers are untouched...
        self.assertEqual(form_answers(self.svc.t), before)
        # ...and the note about the one-sided request is settled by the pair
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

    def test_clear_drops_the_pair_and_keeps_the_form_answers(self):
        before = form_answers(self.svc.t)
        self.svc.partnership_assign("MD", "m0", "m1")
        r = self.svc.partnership_clear("MD", "m0")
        self.assertEqual(event(r["view"], "MD")["paired"], 0)
        self.assertEqual(self.svc.t.pairs, {})
        self.assertEqual(form_answers(self.svc.t), before)
        # and the form pair can be brought back
        self.svc.pairs_auto("MD")
        self.assertEqual(self.svc.t.pair_changes[-1].kind, "from_forms")
        self.svc.pairs_undo("MD")
        self.assertEqual(event(self.svc.partnerships_view(), "MD")["paired"], 0)

    def test_clear_leaves_the_request_visible(self):
        asks(self.svc.t, "m0", "m1", "MD")
        r = self.svc.partnership_clear("MD", "m0")
        self.assertEqual(row(r["view"], "MD", "m0")["status"], "waiting")


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

    def test_setting_pairs_shows_up_in_both_views(self):
        before = form_answers(self.svc.t)
        self.svc.pairs_set("MD", [["m0", "m1"]])
        view = self.svc.partnerships_view()
        self.assertEqual(row(view, "MD", "m0")["status"], "paired")
        self.assertEqual(row(view, "MD", "m2")["status"], "open")
        self.assertEqual(form_answers(self.svc.t), before)
        self.assert_views_agree("MD")

    def test_a_shuffle_leaves_the_form_answers_alone(self):
        asks(self.svc.t, "m0", "m1", "MD")
        before = form_answers(self.svc.t)
        self.svc.pairs_shuffle("MD", 3)
        self.assertEqual(form_answers(self.svc.t), before)
        self.assertEqual(self.svc.t.pair_changes[-1].kind, "shuffle")
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


class TestPlayWithPairings(unittest.TestCase):
    """Shuffling is for experimenting. The form answers stay as submitted, so
    the original request pairs can always be restored, every change is audited,
    and one step at a time can be undone."""

    def setUp(self):
        self.d, self.svc = make_service()
        t = self.svc.t
        for i in range(6):
            add_player(t, f"p{i}", "Player", str(i), "M", ["MD"], 5)
        for a, b in (("p0", "p1"), ("p2", "p3"), ("p4", "p5")):
            asks(t, a, b, "MD")
            asks(t, b, a, "MD")

    def tearDown(self):
        self.d.cleanup()

    def pairs(self, code="MD"):
        return sorted(tuple(sorted(pr.player_ids))
                      for pr in self.svc.t.pairs.values() if pr.event == code)

    def test_shuffle_then_re_pair_from_forms_restores_the_original_pairs(self):
        self.svc.pairs_auto("MD")                 # what the forms asked for
        original = self.pairs()
        self.assertEqual(original, [("p0", "p1"), ("p2", "p3"), ("p4", "p5")])

        self.svc.pairs_shuffle("MD", 4)           # playing around
        self.assertNotEqual(self.pairs(), original)
        # the submissions are untouched by the shuffle
        self.assertEqual(len([h for r in self.svc.t.registrations
                              for h in r.partner_hints if h.event_hint == "MD"]), 6)

        self.svc.pairs_auto("MD")                 # "Re-pair from forms"
        self.assertEqual(self.pairs(), original)

    def test_the_last_change_can_be_undone(self):
        self.svc.pairs_auto("MD")
        original = self.pairs()
        self.svc.pairs_shuffle("MD", 4)
        shuffled = self.pairs()
        out = self.svc.pairs_undo("MD")
        self.assertEqual(self.pairs(), original)
        self.assertEqual(len(self.svc.t.pair_changes), 1)   # only the from_forms step
        self.assertIn("previous pairs", out["notes"][0])
        # and the shuffle is really gone: the next undo goes back to the forms
        self.svc.pairs_undo("MD")
        self.assertEqual(self.pairs(), original)
        self.assertEqual(self.svc.t.pair_changes, [])
        del shuffled

    def test_undo_of_the_first_change_returns_to_the_form_pairs(self):
        self.assertEqual(self.pairs(), [])
        self.svc.partnership_assign("MD", "p0", "p2")
        self.assertEqual(self.pairs(), [("p0", "p2")])
        out = self.svc.pairs_undo("MD")
        self.assertIn("form answers", out["notes"][0])
        self.assertEqual(self.pairs(),
                         [("p0", "p1"), ("p2", "p3"), ("p4", "p5")])

    def test_undo_with_nothing_to_undo_is_refused(self):
        with self.assertRaises(ValueError):
            self.svc.pairs_undo("MD")

    def test_every_change_writes_an_audit_line(self):
        self.svc.pairs_auto("MD")
        self.svc.pairs_shuffle("MD", 4)
        lines = [r for r in self.svc.repo.read_audit()
                 if r["target"] == "pair:MD"]
        self.assertEqual([r["reason"] for r in lines], ["from_forms", "shuffle"])
        self.assertTrue(lines[-1]["old_value"])     # what it was before
        self.assertTrue(lines[-1]["new_value"])     # and after
        self.assertNotEqual(lines[-1]["old_value"], lines[-1]["new_value"])

    def test_the_form_answers_survive_a_reload(self):
        self.svc.pairs_auto("MD")
        original = self.pairs()
        self.svc.pairs_shuffle("MD", 4)
        # a fresh service reads the same document back
        again = TournamentService(Repository(self.svc.repo.path))
        self.assertEqual(len([h for r in again.t.registrations
                              for h in r.partner_hints if h.event_hint == "MD"]), 6)
        self.assertEqual(again.t.pair_changes[-1].kind, "shuffle")
        again.pairs_auto("MD")
        self.assertEqual(sorted(tuple(sorted(pr.player_ids))
                                for pr in again.t.pairs.values()
                                if pr.event == "MD"), original)


class TestUndoGaps(unittest.TestCase):
    """Undo has to work on a pending import preview, and has to take back the
    event a pairing added to a partner who had not entered it."""

    def setUp(self):
        self.d, self.svc = make_service()
        self.t = self.svc.t
        add_player(self.t, "m0", "Ann", "Alpha", "F", ["MD", "XD"], 6)
        add_player(self.t, "m1", "Bea", "Beta", "M", ["MD", "XD"], 7)
        add_player(self.t, "m2", "Cal", "Gamma", "M", ["XD"], 8)   # XD only

    def tearDown(self):
        self.d.cleanup()

    def pairs(self, code):
        return sorted(tuple(sorted(pr.player_ids))
                      for pr in self.t.pairs.values() if pr.event == code)

    def test_undo_takes_back_an_event_added_to_a_partner(self):
        self.assertNotIn("MD", self.t.players["m2"].events)
        self.svc.partnership_assign("MD", "m0", "m2")   # m2 had not entered MD
        self.assertIn("MD", self.t.players["m2"].events)
        self.assertEqual(self.pairs("MD"), [("m0", "m2")])

        out = self.svc.pairs_undo("MD")

        self.assertNotIn("MD", self.t.players["m2"].events)
        self.assertEqual(self.t.players["m2"].events, ["XD"])
        # and they are not in an MD pair any more
        self.assertFalse(any("m2" in pr.player_ids for pr in self.t.pairs.values()
                             if pr.event == "MD"))
        self.assertTrue(any("removed MD from Cal Gamma's events" in n
                            for n in out["notes"]))
        # and the whole trip is audited
        lines = [r for r in self.svc.repo.read_audit()
                 if r["target"] == "player:m2" and r["field_name"] == "events"]
        self.assertEqual([r["new_value"] for r in lines], ["XD, MD", "XD"])

    def test_undo_keeps_an_event_the_player_is_still_paired_in(self):
        self.svc.partnership_assign("MD", "m0", "m2")     # adds MD to m2, pairs
        self.svc.partnership_assign("MD", "m2", "m1")     # m2 pairs with m1
        self.svc.pairs_undo("MD")                        # back to m0 + m2
        self.assertIn("MD", self.t.players["m2"].events)
        self.assertEqual(self.pairs("MD"), [("m0", "m2")])
        self.svc.pairs_undo("MD")                        # now nothing in MD
        self.assertNotIn("MD", self.t.players["m2"].events)

    def test_undo_works_while_an_import_preview_is_open(self):
        path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..",
                                            "sample_data", "legacy_mixed.csv"))
        self.svc.import_preview("file", path)
        view = self.svc.partnerships_view()
        code = view["events"][0]["event"]
        self.svc.pairs_auto(code)                 # what the forms ask for, here
        form_pairs = {frozenset(pr.player_ids) for pr in self.svc._preview.tournament.pairs.values()
                      if pr.event == code}
        people = [r["player"]["id"] for r in event(self.svc.partnerships_view(),
                                                   code)["rows"]]
        pair = next({a, b} for i, a in enumerate(people) for b in people[i + 1:]
                    if frozenset({a, b}) not in form_pairs)
        first, second = sorted(pair)

        self.svc.partnership_assign(code, first, second)
        self.assertIn(frozenset(pair),
                      {frozenset(pr.player_ids) for pr in self.svc._preview.tournament.pairs.values()
                       if pr.event == code})
        self.assertEqual(row(self.svc.partnerships_view(), code, first)["status"],
                         "paired")

        out = self.svc.pairs_undo(code)

        self.assertNotIn(frozenset(pair),
                         {frozenset(pr.player_ids) for pr in self.svc._preview.tournament.pairs.values()
                          if pr.event == code})
        # the committed tournament was never touched by either edit
        self.assertEqual(len(self.svc.repo.load().players), 0)
        self.assertEqual(self.svc.repo.load().pair_changes, [])
        self.assertTrue(out["view"]["events"])

    def test_shuffle_and_re_pair_also_stay_in_the_preview(self):
        path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..",
                                            "sample_data", "legacy_mixed.csv"))
        self.svc.import_preview("file", path)
        code = self.svc.partnerships_view()["events"][0]["event"]
        self.svc.pairs_shuffle(code, 2)
        self.svc.pairs_auto(code)
        self.svc.pairs_undo(code)
        self.assertEqual(self.svc.repo.load().pairs, {})
        self.assertEqual(self.svc.repo.load().pair_changes, [])
        self.assertIsNotNone(self.svc._preview)     # still previewing


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
