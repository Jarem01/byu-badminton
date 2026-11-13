"""Live court board: manual assignment, center-court rule, scoring, clearing."""

import os
import tempfile
import unittest

from tournament.server.service import Conflict, TournamentService
from tournament.store.repository import Repository

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "sample_data",
                       "clean_singles_16.csv")


class TestBoard(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.svc = TournamentService(Repository(os.path.join(self.d.name, "t.json")))
        self.svc.import_preview("file", FIXTURE, "auto")
        self.svc.import_commit()
        self.svc.build_divisions(rng_seed=1)
        self.ms = next(x for x in self.svc.divisions() if x["event"] == "MS")
        self.svc.generate_bracket(self.ms["id"], "single_elim", "ranking")

    def tearDown(self):
        self.d.cleanup()

    def _a_ready_knockout(self):
        return next(m for m in self.svc.board_view()["queue"] if m["knockout"])

    def test_board_has_eight_courts_center_marked(self):
        v = self.svc.board_view()
        self.assertEqual(len(v["courts"]), 8)
        centers = {c["num"] for c in v["courts"] if c["center"]}
        self.assertEqual(centers, {2, 3, 6, 7})

    def test_knockout_only_on_center_courts(self):
        m = self._a_ready_knockout()
        with self.assertRaises(Conflict):
            self.svc.board_assign(1, m["id"])          # outer court rejected
        v = self.svc.board_assign(2, m["id"])          # center court ok
        court2 = next(c for c in v["courts"] if c["num"] == 2)
        self.assertEqual(court2["match"]["id"], m["id"])
        # It left the queue while assigned.
        self.assertNotIn(m["id"], [q["id"] for q in v["queue"]])

    def test_result_on_court_frees_it_and_advances(self):
        m = self._a_ready_knockout()
        self.svc.board_assign(2, m["id"])
        v = self.svc.board_result(2, [[21, 10], [21, 12]])
        self.assertIsNone(next(c for c in v["courts"] if c["num"] == 2)["match"])
        # Winner advanced (its match now carries a result in the bracket).
        done = self.svc.t.brackets[self.ms["id"]].matches[m["id"]]
        self.assertIsNotNone(done.result)

    def test_clear_returns_match_to_queue(self):
        m = self._a_ready_knockout()
        self.svc.board_assign(2, m["id"])
        v = self.svc.board_clear(2)
        self.assertIsNone(next(c for c in v["courts"] if c["num"] == 2)["match"])
        self.assertIn(m["id"], [q["id"] for q in v["queue"]])

    def test_occupied_court_rejected(self):
        q = [m for m in self.svc.board_view()["queue"] if m["knockout"]]
        self.svc.board_assign(2, q[0]["id"])
        with self.assertRaises(Conflict):
            self.svc.board_assign(2, q[1]["id"])       # court 2 already busy

    def test_court_dropdown_options_respect_rules(self):
        # Add a round-robin division so there are pool matches too.
        r = self.svc.create_custom_division("RR", "player",
                                            [f"Q{i}:{6-i}" for i in range(5)], "MS")
        self.svc.generate_bracket(r["id"], "round_robin", "ranking")
        v = self.svc.board_view()
        c1 = next(c for c in v["courts"] if c["num"] == 1)   # outer
        c2 = next(c for c in v["courts"] if c["num"] == 2)   # center
        # Outer court never offers a knockout match.
        self.assertTrue(all(not o["knockout"] for o in c1["options"]))
        # Center court lists a knockout first (single_elim R1 is ready).
        self.assertTrue(c2["options"] and c2["options"][0]["knockout"])

    def test_every_court_has_on_deck_including_occupied(self):
        m = self._a_ready_knockout()
        self.svc.board_assign(2, m["id"])
        v = self.svc.board_view()
        # Every court (busy or open) offers an on-deck list when matches remain.
        self.assertTrue(all("options" in c for c in v["courts"]))
        self.assertTrue(next(c for c in v["courts"] if c["num"] == 2)["options"])

    def test_on_deck_consistent_across_courts(self):
        r = self.svc.create_custom_division("RR", "player",
                                            [f"Q{i}:{6-i}" for i in range(5)], "MS")
        self.svc.generate_bracket(r["id"], "round_robin", "ranking")
        q = [m for m in self.svc.board_view()["queue"] if not m["knockout"]]
        self.svc.board_assign(1, q[0]["id"])
        busy = {q[0]["side1"]["key"], q[0]["side2"]["key"]}
        v = self.svc.board_view()
        # A match needing a busy player is 'waiting' on EVERY court (incl. court 1).
        for c in v["courts"]:
            for o in c["options"]:
                if o["side1"]["key"] in busy or o["side2"]["key"] in busy:
                    self.assertFalse(o["ready"])
        # Two center courts show the identical on-deck list.
        c2 = [o["id"] for o in next(c for c in v["courts"] if c["num"] == 2)["options"]]
        c3 = [o["id"] for o in next(c for c in v["courts"] if c["num"] == 3)["options"]]
        self.assertEqual(c2, c3)

    def test_on_deck_lists_ready_before_waiting(self):
        # An open court's on-deck must surface playable matches first, so a court
        # never shows only 'waiting' items while a ready match exists further down.
        r = self.svc.create_custom_division("RR", "player",
                                            [f"Q{i}:{6-i}" for i in range(5)], "MS")
        self.svc.generate_bracket(r["id"], "round_robin", "ranking")
        pools = [q for q in self.svc.board_view()["queue"] if not q["knockout"]]
        self.svc.board_assign(1, pools[0]["id"])       # some players now busy
        v = self.svc.board_view()
        for c in v["courts"]:
            seen_waiting = False
            for o in c["options"]:
                if not o["ready"]:
                    seen_waiting = True
                else:
                    self.assertFalse(seen_waiting,
                                     "a ready match appears after a waiting one")

    def test_upcoming_knockout_shown_then_becomes_ready(self):
        # Group->knockout: before pools finish, the knockout matches appear as
        # read-only "upcoming" placeholders (not in the ready queue). Once pools
        # complete, they leave 'upcoming' and enter the ready queue (draggable).
        r = self.svc.create_custom_division(
            "GK", "player", [f"G{i}:{16-i}" for i in range(16)], "MS")
        self.svc.generate_bracket(r["id"], "group_knockout", "ranking",
                                  num_groups=4, main_draw=8)
        v = self.svc.board_view()
        self.assertTrue(v["upcoming"], "knockout skeleton should be visible early")
        self.assertTrue(all(u["knockout"] for u in v["upcoming"]))
        # None of the upcoming placeholders are in the ready queue yet.
        self.assertFalse(set(u["id"] for u in v["upcoming"])
                         & set(q["id"] for q in v["queue"]))
        # Play every pool match; the first-round knockout should now be ready.
        br = self.svc.t.brackets[r["id"]]
        seed_no = {s.entry.key(): s.seed_no for s in br.seeds}
        progressed = True
        while progressed:
            progressed = False
            for m in list(br.matches.values()):
                if (m.bracket_part == "pool" and m.result is None
                        and m.side1 and m.side2):
                    s1, s2 = seed_no[m.side1.key()], seed_no[m.side2.key()]
                    self.svc.record_result(r["id"], m.id,
                        [[21, 5], [21, 5]] if s1 < s2 else [[5, 21], [5, 21]])
                    progressed = True
        v2 = self.svc.board_view()
        ready_ids = {q["id"] for q in v2["queue"]}
        qf_ids = {m.id for m in br.matches.values() if m.round_name == "Quarterfinal"}
        self.assertTrue(qf_ids & ready_ids, "filled QFs should be ready to play")

    def test_schedule_goes_stale_when_bracket_regenerated(self):
        # Regenerating a bracket (e.g. adding a knockout draw) must flag the
        # existing schedule as stale so the organizer re-generates it.
        self.svc.generate_schedule([self.ms["id"]])
        self.assertFalse(self.svc.schedule_view()["stale"])
        self.svc.generate_bracket(self.ms["id"], "round_robin", "ranking")
        self.assertTrue(self.svc.schedule_view()["stale"])

    def test_no_double_booking(self):
        # In a round robin a player has several matches; once one is on a court,
        # another of their matches can't be placed elsewhere at the same time.
        r = self.svc.create_custom_division("RR", "player",
                                            [f"Q{i}:{6-i}" for i in range(5)], "MS")
        self.svc.generate_bracket(r["id"], "round_robin", "ranking")
        pools = [q for q in self.svc.board_view()["queue"] if not q["knockout"]]
        m1 = pools[0]
        self.svc.board_assign(1, m1["id"])
        busy = {m1["side1"]["key"], m1["side2"]["key"]}
        m2 = next(q for q in pools[1:]
                  if q["side1"]["key"] in busy or q["side2"]["key"] in busy)
        with self.assertRaises(Conflict):
            self.svc.board_assign(4, m2["id"])       # shares a player -> blocked

    def test_pool_match_allowed_on_outer_court(self):
        # A round-robin division's matches are pool matches -> any court is fine.
        r = self.svc.create_custom_division("RR", "player",
                                            [f"Q{i}:{6-i}" for i in range(5)], "MS")
        self.svc.generate_bracket(r["id"], "round_robin", "ranking")
        pool = next(m for m in self.svc.board_view()["queue"] if not m["knockout"])
        v = self.svc.board_assign(1, pool["id"])        # outer court allowed
        self.assertEqual(next(c for c in v["courts"] if c["num"] == 1)["match"]["id"],
                         pool["id"])


if __name__ == "__main__":
    unittest.main()
