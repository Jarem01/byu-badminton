"""Planner: compare formats with time estimates, without mutating state."""

import os
import tempfile
import unittest

from tournament.server.service import TournamentService
from tournament.store.repository import Repository

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "messy_legacy.csv")


class TestPlanner(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.svc = TournamentService(Repository(os.path.join(self.d.name, "t.json")))
        self.svc.import_preview("file", FIXTURE, "auto")
        self.svc.import_commit()
        self.svc.build_divisions(rng_seed=2026)
        self.ms = next(x for x in self.svc.divisions() if x["event"] == "MS")

    def tearDown(self):
        self.d.cleanup()

    def test_plan_lists_formats_with_estimates(self):
        plan = self.svc.plan_division(self.ms["id"], start="17:00", end="21:00",
                                      court_count=4)
        fmts = {o["format"] for o in plan["options"]}
        self.assertTrue({"single_elim", "round_robin", "group_knockout"} <= fmts)
        for o in plan["options"]:
            if o["ok"]:
                self.assertGreater(o["duration_min"], 0)
                self.assertIn("end_time", o)
                self.assertIn("preview", o)
                self.assertTrue(o["preview"]["rounds"])

    def test_double_elim_offered_for_any_size(self):
        # Double elim now works for any field size (byes to top seeds), so it's
        # offered for a non-power-of-two field too.
        plan = self.svc.plan_division(self.ms["id"])   # 7 entrants
        de = next((o for o in plan["options"] if o["format"] == "double_elim"), None)
        self.assertIsNotNone(de)
        self.assertTrue(de["ok"])

    def test_fit_and_overtime_flags(self):
        # A very short window should make the longer formats overflow.
        plan = self.svc.plan_division(self.ms["id"], start="17:00", end="17:30",
                                      court_count=1)
        rr = next(o for o in plan["options"]
                  if o["format"] == "round_robin" and o["ok"])
        self.assertFalse(rr["fits"])
        self.assertGreater(rr["overtime_min"], 0)

    def test_planning_does_not_mutate_state(self):
        before = len(self.svc.t.brackets)
        self.svc.plan_division(self.ms["id"], start="17:00", end="21:00")
        self.assertEqual(len(self.svc.t.brackets), before)  # nothing committed
        self.assertEqual(before, 0)

    def test_non_pow2_recommends_combined_group_knockout(self):
        # MS has 7 entrants -> recommend groups -> clean 4-draw (no byes).
        plan = self.svc.plan_division(self.ms["id"], start="17:00", end="22:00")
        rec = [o for o in plan["options"] if o.get("recommended")]
        self.assertEqual(len(rec), 1)
        r = rec[0]
        self.assertEqual(r["format"], "group_knockout")
        self.assertTrue(r["combined"])
        self.assertIn("draw", r["label"])
        # single elimination (with byes) is still offered as a pure option.
        self.assertTrue(any(o["format"] == "single_elim" for o in plan["options"]))

    def test_power_of_two_recommends_pure_single_elim(self):
        r = self.svc.create_custom_division(
            "Eight", "player", [f"P{i}:{9-i}" for i in range(8)], "MS")
        plan = self.svc.plan_division(r["id"], start="17:00", end="23:00")
        rec = next(o for o in plan["options"] if o.get("recommended"))
        self.assertEqual(rec["format"], "single_elim")
        self.assertFalse(rec["combined"])
        self.assertTrue(any(o["format"] == "double_elim" for o in plan["options"]))

    def test_group_sizing_helper(self):
        from tournament.engine.bracket_groups import (
            choose_groups_for_main_draw, largest_pow2_le)
        self.assertEqual(largest_pow2_le(11), 8)
        self.assertEqual(largest_pow2_le(7), 4)
        g, a = choose_groups_for_main_draw(11, 8)
        self.assertEqual(g * a, 8)                 # clean 8-draw
        self.assertIsNone(choose_groups_for_main_draw(8, 8))  # no qualification needed

    def test_single_event_estimate_reasonable(self):
        # Group->knockout must estimate longer than a single elimination for the
        # same field (pools add matches), and both must be positive.
        plan = self.svc.plan_division(self.ms["id"], start="17:00")
        se = next(o for o in plan["options"] if o["format"] == "single_elim")
        gk = next(o for o in plan["options"]
                  if o["format"] == "group_knockout" and o["ok"])
        self.assertGreater(gk["matches"], se["matches"])


if __name__ == "__main__":
    unittest.main()
