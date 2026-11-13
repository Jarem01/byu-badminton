"""Downstream-only clear + current/upcoming queue in the bracket view."""

import os
import tempfile
import unittest

from tournament.server.service import TournamentService
from tournament.store.repository import Repository

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "messy_legacy.csv")


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.svc = TournamentService(Repository(os.path.join(self.d.name, "t.json")))
        self.svc.import_preview("file", FIXTURE, "auto")
        self.svc.import_commit()
        self.svc.build_divisions(rng_seed=2026)
        self.ms = next(x for x in self.svc.divisions() if x["event"] == "MS")
        self.svc.generate_bracket(self.ms["id"], "single_elim", "ranking")
        self.svc.generate_schedule()

    def tearDown(self):
        self.d.cleanup()


class TestClear(Base):
    def test_clear_scores_keeps_bracket_wipes_results(self):
        view = self.svc.bracket_view(self.ms["id"])
        m = next(x for r in view["rounds"] for x in r["matches"] if x["ready"])
        self.svc.record_result(self.ms["id"], m["id"], [[21, 5], [21, 5]])
        self.assertTrue(any(x["winner"] for r in self.svc.bracket_view(self.ms["id"])["rounds"]
                            for x in r["matches"]))
        self.svc.clear("scores")
        after = self.svc.bracket_view(self.ms["id"])
        self.assertTrue(after["exists"])                          # bracket kept
        self.assertFalse(any(x["winner"] for r in after["rounds"]
                             for x in r["matches"] if not x["walkover"]))  # results gone

    def test_clear_schedule_only(self):
        self.assertTrue(self.svc.schedule_view()["blocks"])
        self.svc.clear("schedule")
        self.assertEqual(self.svc.schedule_view()["blocks"], [])
        self.assertTrue(self.svc.bracket_view(self.ms["id"])["exists"])   # bracket kept

    def test_clear_divisions_keeps_players(self):
        n_players = len(self.svc.players())
        self.svc.clear("divisions")
        self.assertEqual(self.svc.divisions(), [])
        self.assertEqual(len(self.svc.players()), n_players)      # upstream intact

    def test_clear_import_resets_all(self):
        self.svc.clear("import")
        self.assertEqual(self.svc.players(), [])
        self.assertEqual(self.svc.divisions(), [])
        self.assertEqual(self.svc.schedule_view()["blocks"], [])

    def test_unknown_stage_rejected(self):
        with self.assertRaises(ValueError):
            self.svc.clear("nonsense")

    def test_clear_single_match_reverts_downstream(self):
        view = self.svc.bracket_view(self.ms["id"])
        r1 = [m for m in view["rounds"][0]["matches"] if m["ready"]]
        # Play two first-round matches so a semifinal fills.
        self.svc.record_result(self.ms["id"], r1[0]["id"], [[21, 5], [21, 5]])
        w = next(m for r in self.svc.bracket_view(self.ms["id"])["rounds"]
                 for m in r["matches"] if m["id"] == r1[0]["id"])["winner"]
        self.assertIsNotNone(w)
        # Clear that one match -> its winner leaves the next round.
        after = self.svc.clear_match(self.ms["id"], r1[0]["id"])
        cleared = next(m for r in after["rounds"] for m in r["matches"]
                       if m["id"] == r1[0]["id"])
        self.assertIsNone(cleared["winner"])
        self.assertEqual(cleared["games"], [])


class TestStaleSchedule(Base):
    def test_stale_flag_tracks_setting_changes(self):
        self.assertFalse(self.svc.schedule_view()["stale"])   # fresh
        self.svc.update_settings({"court_count": 8})           # changes scheduling
        self.assertTrue(self.svc.schedule_view()["stale"])     # now out of date
        self.svc.generate_schedule()                           # regenerate
        self.assertFalse(self.svc.schedule_view()["stale"])
        # A non-scheduling setting (match points) does NOT mark it stale.
        self.svc.update_settings({"points_to": 15})
        self.assertFalse(self.svc.schedule_view()["stale"])


class TestQueue(Base):
    def test_bye_advanced_semifinal_is_upcoming_not_skipped(self):
        # A 6-player custom division -> 2 first-round byes; both semifinals have a
        # bye-advanced player awaiting an opponent. They must appear in "upcoming"
        # (regression: is_bye() used to hide them).
        r = self.svc.create_custom_division(
            "Six", "player", [f"P{i}:{9-i}" for i in range(6)], "MS")
        self.svc.generate_bracket(r["id"], "single_elim", "ranking")
        q = self.svc.bracket_view(r["id"])["queue"]
        self.assertEqual(len(q["ready"]), 2)       # two real first-round matches
        self.assertGreaterEqual(len(q["upcoming"]), 2)  # both bye-fed semifinals

    def test_queue_ready_and_upcoming(self):
        view = self.svc.bracket_view(self.ms["id"])
        q = view["queue"]
        self.assertTrue(q["ready"])                    # first-round matches ready
        # A later-round match should be listed as upcoming (feeders are ready).
        self.assertTrue(q["upcoming"])
        # Play a ready match; the queue should evolve.
        first = q["ready"][0]
        self.svc.record_result(self.ms["id"], first["id"], [[21, 5], [21, 5]])
        q2 = self.svc.bracket_view(self.ms["id"])["queue"]
        ready_ids = {m["id"] for m in q2["ready"]}
        self.assertNotIn(first["id"], ready_ids)       # played match left the ready list


if __name__ == "__main__":
    unittest.main()
