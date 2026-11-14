"""Editable settings (persisted) and custom/manual division creation."""

import os
import tempfile
import unittest

from tournament.server.service import TournamentService
from tournament.store.repository import Repository


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.d.name, "t.json")
        self.svc = TournamentService(Repository(self.path))

    def tearDown(self):
        self.d.cleanup()


class TestSettings(Base):
    def test_update_and_persist(self):
        self.svc.update_settings({"court_count": 6, "day_start": "18:00",
                                  "warmup_min": 6, "play_min": 24, "buffer_min": 5,
                                  "points_to": 15, "hard_cap": 21, "rest_min": 15})
        s = self.svc.get_settings()
        self.assertEqual(s["court_count"], 6)
        self.assertEqual(s["day_start"], "18:00")
        self.assertEqual(s["slot_min"], 35)          # 6+24+5
        self.assertEqual(s["points_to"], 15)
        # Reload from disk -> settings survived.
        svc2 = TournamentService(Repository(self.path))
        self.assertEqual(svc2.get_settings()["court_count"], 6)
        self.assertEqual(svc2.get_settings()["day_start"], "18:00")

    def test_center_courts_are_editable(self):
        # Which courts knockouts may use used to be fixed at 2,3,6,7.
        s = self.svc.update_settings({"center_courts": "1, 4 ;4"})
        self.assertEqual(s["center_courts"], [1, 4])
        self.assertEqual(self.svc.get_settings()["center_courts"], [1, 4])
        svc2 = TournamentService(Repository(self.path))
        self.assertEqual(svc2.get_settings()["center_courts"], [1, 4])
        self.svc.update_settings({"center_courts": ""})      # blank = no restriction
        self.assertEqual(self.svc.get_settings()["center_courts"], [])

    def test_center_courts_rejects_junk_readably(self):
        self.svc.update_settings({"center_courts": "1, 2"})
        before = self.svc.get_settings()["court_count"]
        with self.assertRaises(ValueError) as ctx:
            self.svc.update_settings({"center_courts": "1, court 2",
                                      "court_count": before + 3})
        self.assertIn("numbers like 2, 3, 6, 7", str(ctx.exception))
        after = self.svc.get_settings()
        self.assertEqual(after["center_courts"], [1, 2])
        self.assertEqual(after["court_count"], before)   # nothing half-applied

    def test_settings_feed_scheduler(self):
        self.svc.update_settings({"court_count": 1, "day_start": "09:00"})
        self.svc.create_custom_division("Test", "player",
                                        ["A:8", "B:7", "C:6", "D:5"], "MS")
        div = self.svc.divisions()[0]
        self.svc.generate_bracket(div["id"], "single_elim", "ranking")
        view = self.svc.generate_schedule()
        self.assertEqual(view["day_start"], "09:00")
        # 1 court forces matches into separate slots -> later end time.
        self.assertGreater(view["duration_min"], 0)


class TestCustomDivision(Base):
    def test_singles_with_skills(self):
        r = self.svc.create_custom_division(
            "Ladder", "player", ["Alice Ace:9", "Bob:6", "Carol Lin", "Dan"], "MS")
        self.assertEqual(r["entries"], 4)
        div_id = r["id"]
        # Skill parsed where given.
        alice = next(p for p in self.svc.t.players.values() if p.first == "Alice")
        self.assertEqual(alice.skill, 9)
        view = self.svc.generate_bracket(div_id, "single_elim", "ranking")
        self.assertTrue(view["rounds"])
        # Top skill (Alice, 9) seeds first.
        self.assertEqual(view["seeds"][0]["label"], "Alice Ace")

    def test_pairs(self):
        r = self.svc.create_custom_division(
            "Fun Doubles", "pair", ["Alice / Bob", "Carol / Dan", "Eve / Fay"],
            "MD")
        self.assertEqual(r["entries"], 3)
        div = self.svc.t.divisions[r["id"]]
        self.assertTrue(all(e.kind == "pair" for e in div.entry_refs))
        # Each pair has two real players.
        for e in div.entry_refs:
            self.assertEqual(len(self.svc.t.pairs[e.ref_id].player_ids), 2)

    def test_rejects_too_few(self):
        with self.assertRaises(ValueError):
            self.svc.create_custom_division("Solo", "player", ["Only One"], "MS")

    def test_pair_lines_that_are_not_pairs_are_reported(self):
        r = self.svc.create_custom_division(
            "Odd Doubles", "pair",
            ["Ann One / Bea Two", "Cid Solo", "Dee Four / Eve Five"], "XD")
        self.assertEqual(r["entries"], 2)
        self.assertEqual(r["skipped"], ["Cid Solo"])
        # the skipped line created nobody
        self.assertFalse([p for p in self.svc.t.players.values()
                          if p.first == "Cid"])

    def test_skipped_lines_are_named_when_too_few_remain(self):
        with self.assertRaises(ValueError) as caught:
            self.svc.create_custom_division("Odd Doubles", "pair",
                                            ["Ann One / Bea Two", "Cid Solo"], "XD")
        self.assertIn("Cid Solo", str(caught.exception))

    def test_custom_division_can_be_planned(self):
        r = self.svc.create_custom_division(
            "Open", "player", [f"P{i}:{9-i}" for i in range(8)], "MS")
        plan = self.svc.plan_division(r["id"], start="17:00", end="21:00")
        self.assertTrue(any(o["ok"] for o in plan["options"]))


if __name__ == "__main__":
    unittest.main()
