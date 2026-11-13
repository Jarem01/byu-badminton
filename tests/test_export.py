"""M9: CSV export outputs."""

import os
import tempfile
import unittest

from tournament.export.csv_out import rows_to_csv
from tournament.server.service import TournamentService
from tournament.store.repository import Repository

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "messy_legacy.csv")


class TestCsvHelper(unittest.TestCase):
    def test_rows_to_csv(self):
        out = rows_to_csv(["A", "B"], [[1, "x"], [2, "y,z"]])
        lines = out.splitlines()
        self.assertEqual(lines[0], "A,B")
        self.assertIn('"y,z"', lines[2])  # comma-containing field is quoted


class TestServiceExports(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.svc = TournamentService(Repository(os.path.join(self.d.name, "t.json")))
        self.svc.import_preview("file", FIXTURE, "auto")
        self.svc.import_commit()
        self.svc.build_divisions(rng_seed=2026)

    def tearDown(self):
        self.d.cleanup()

    def test_roster_export(self):
        name, text = self.svc.export_csv("roster")
        self.assertEqual(name, "roster.csv")
        self.assertIn("Name,Gender,Skill", text.splitlines()[0])
        self.assertIn("Brian Chi", text)

    def test_schedule_export(self):
        ms = next(d for d in self.svc.divisions() if d["event"] == "MS")
        self.svc.generate_bracket(ms["id"], "single_elim", "ranking")
        self.svc.generate_schedule()
        name, text = self.svc.export_csv("schedule_time")
        self.assertTrue(text.splitlines()[0].startswith("Time,Court,Division"))
        self.assertGreater(len(text.splitlines()), 1)

    def test_standings_and_results_export(self):
        xd = next(d for d in self.svc.divisions() if d["event"] == "XD")
        self.svc.generate_bracket(xd["id"], "group_knockout", "ranking",
                                  num_groups=2, main_draw=4)
        # Play one pool match to create a result row.
        view = self.svc.bracket_view(xd["id"])
        pool_match = next(m for r in view["rounds"] if r["part"] == "pool"
                          for m in r["matches"] if m["ready"])
        self.svc.record_result(xd["id"], pool_match["id"], [[21, 15], [21, 10]])
        _n, standings = self.svc.export_csv("standings")
        self.assertIn("Division,Pool,Rank", standings.splitlines()[0])
        _n2, results = self.svc.export_csv("results")
        self.assertIn("Division,Round,Side 1", results.splitlines()[0])
        self.assertGreater(len(results.splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
