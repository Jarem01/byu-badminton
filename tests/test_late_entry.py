"""Late entries: add a player or pair by hand without touching the import."""

import os
import tempfile
import unittest

from tournament.model.entities import Player, Tournament
from tournament.server.service import TournamentService
from tournament.store.repository import Repository

CSV = os.path.join(os.path.dirname(__file__), "..", "sample_data",
                   "clean_singles_16.csv")


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.d.name, "t.json")
        t = Tournament(name="Late Cup", date="2026-04-04")
        roster = [("Cam", "Gamma", "M"), ("Dee", "Delta", "M"),
                  ("Eli", "Epsilon", "M"), ("Fay", "Zeta", "M"),
                  ("Ann", "Alpha", "F"), ("Bea", "Beta", "F")]
        for i, (first, last, gender) in enumerate(roster):
            t.players[f"p{i}"] = Player(
                id=f"p{i}", first=first, last=last, gender=gender, skill=5,
                events=["MD"] if gender == "M" else ["WD"])
        Repository(self.path).save(t)
        self.svc = TournamentService(Repository(self.path))
        self.svc.build_divisions()

    def tearDown(self):
        self.d.cleanup()

    def div(self, event):
        return next(d for d in self.svc.divisions() if d["event"] == event)

    def names(self):
        return [p["name"] for p in self.svc.players()]


class TestLateEntry(Base):
    def test_a_pair_joins_an_event_that_has_not_been_drawn(self):
        before = self.div("MD")["entries"]
        r = self.svc.add_manual_entries("MD", ["Late Ace:6 / New Net:4"])
        self.assertEqual(r["added"], ["Late Ace", "New Net"])
        self.assertEqual(self.div("MD")["entries"], before + 1)
        self.assertEqual(r["entered"], 1)
        self.assertFalse(r["draw"])
        self.assertIn("Late Ace", self.names())
        # The gender rule comes from the event, so no unknown-gender warning.
        player = next(p for p in self.svc.players() if p["name"] == "Late Ace")
        self.assertEqual(player["gender"], "M")
        self.assertEqual(player["events"], ["MD"])

    def test_a_draw_that_exists_is_left_alone(self):
        md = self.div("MD")
        self.svc.generate_bracket(md["id"], "single_elim", "ranking")
        before = len(self.svc.t.brackets[md["id"]].matches)
        r = self.svc.add_manual_entries("MD", ["Late Ace:6 / New Net:4"])
        self.assertTrue(r["draw"])
        # The live draw is untouched; the entrant list it is drawn from grows.
        self.assertEqual(len(self.svc.t.brackets[md["id"]].matches), before)
        self.assertEqual(self.div("MD")["entries"], md["entries"] + 1)
        self.assertTrue(any("regenerate" in n for n in r["notes"]), r["notes"])
        # ...so regenerating the bracket picks the late pair up.
        view = self.svc.generate_bracket(md["id"], "single_elim", "ranking",
                                         force=True)
        self.assertIn("Late Ace / New Net", [s["label"] for s in view["seeds"]])

    def test_the_same_names_are_never_duplicated(self):
        self.svc.add_manual_entries("MD", ["Late Ace:6 / New Net:4"])
        before = (len(self.svc.players()), self.div("MD")["entries"])
        r = self.svc.add_manual_entries("MD", ["Late Ace / New Net"])
        self.assertEqual((len(self.svc.players()), self.div("MD")["entries"]), before)
        self.assertEqual(r["added"], [])
        self.assertEqual(r["entered"], 0)
        self.assertTrue(any("already in the roster" in n for n in r["notes"]))

    def test_one_name_alone_is_added_unpaired(self):
        r = self.svc.add_manual_entries("MD", ["Solo Player:5"])
        self.assertIn("Solo Player", self.names())
        self.assertEqual(r["unpaired"], ["Solo Player"])
        self.assertEqual(r["entered"], 0)
        self.assertTrue(any("pick a partner" in n for n in r["notes"]))

    def test_singles_go_into_the_players_division(self):
        # No MS division here, so the roster grows and the note says so.
        r = self.svc.add_manual_entries("MS", ["New Guy:7"])
        self.assertIn("New Guy", self.names())
        self.assertIsNone(r["division_id"])
        self.assertTrue(any("Build divisions" in n for n in r["notes"]))

    def test_unknown_event_is_refused(self):
        with self.assertRaises(ValueError):
            self.svc.add_manual_entries("XX", ["Someone"])


class TestLateEntrySurvivesImport(Base):
    @unittest.skipUnless(os.path.isfile(CSV), "csv fixture missing")
    def test_reimport_keeps_hand_typed_players(self):
        self.svc.add_manual_entries("MD", ["Late Ace:6 / New Net:4"])
        self.svc.import_preview("file", os.path.abspath(CSV))
        r = self.svc.import_commit()
        names = self.names()
        self.assertIn("Late Ace", names)
        self.assertIn("New Net", names)
        self.assertIn("Late Ace", r["manual_kept"])
        self.assertEqual(r["manual_pairs_kept"], 1)
        # The sheet's own players came through untouched.
        self.assertIn("Mplayer M00", names)

    @unittest.skipUnless(os.path.isfile(CSV), "csv fixture missing")
    def test_a_name_the_sheet_lists_is_not_duplicated(self):
        # Mplayer M00 is row 1 of the fixture; typing them by hand first must
        # not leave two of them after the import.
        self.svc.add_manual_entries("MS", ["Mplayer M00:3"])
        self.svc.import_preview("file", os.path.abspath(CSV))
        r = self.svc.import_commit()
        self.assertEqual(self.names().count("Mplayer M00"), 1)
        self.assertNotIn("Mplayer M00", r["manual_kept"])


if __name__ == "__main__":
    unittest.main()
