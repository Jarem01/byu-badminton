"""M2: normalization, partner parsing, and end-to-end legacy import."""

import os
import unittest

from tournament.ingest import normalize as N
from tournament.ingest.partner_parse import parse_partners, looks_like_name
from tournament.ingest.source_csv import read_rows
from tournament.ingest.importer import build_tournament

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "messy_legacy.csv")


class TestNormalize(unittest.TestCase):
    def test_skill(self):
        self.assertEqual(N.parse_skill("8"), 8)
        self.assertEqual(N.parse_skill(" 5 "), 5)
        self.assertIsNone(N.parse_skill(""))
        self.assertIsNone(N.parse_skill("expert"))
        self.assertIsNone(N.parse_skill("0"))      # out of 1..9
        self.assertIsNone(N.parse_skill("12"))

    def test_events(self):
        self.assertEqual(
            N.parse_events("Men's Singles (MS), Men's Doubles (MD), Mixed Doubles (XD)"),
            ["MS", "MD", "XD"])
        self.assertEqual(N.parse_events("Women's Doubles (WD), Mixed Doubles (XD)"),
                         ["WD", "XD"])
        self.assertEqual(N.parse_events(""), [])
        # Deterministic canonical order regardless of input order.
        self.assertEqual(N.parse_events("(XD), (MS)"), ["MS", "XD"])

    def test_gender_inference(self):
        self.assertEqual(N.infer_gender_from_events(["MS", "MD"]), ("M", False))
        self.assertEqual(N.infer_gender_from_events(["WS", "WD"]), ("F", False))
        self.assertEqual(N.infer_gender_from_events(["XD"]), ("U", False))
        self.assertEqual(N.infer_gender_from_events(["MS", "WS"]), ("U", True))

    def test_yes_no(self):
        self.assertTrue(N.parse_yes_no("Yes"))
        self.assertFalse(N.parse_yes_no("no"))
        self.assertTrue(N.parse_yes_no("", default=True))
        self.assertIsNone(N.parse_yes_no("maybe"))


class TestPartnerParse(unittest.TestCase):
    def test_single(self):
        h = parse_partners("Michael Pang")
        self.assertEqual([x.raw_name for x in h], ["Michael Pang"])

    def test_semicolon_two(self):
        h = parse_partners("Brain Chi; Hillary Kam")
        self.assertEqual([x.raw_name for x in h], ["Brain Chi", "Hillary Kam"])

    def test_per_event_tags(self):
        h = parse_partners("Yuen Yuen Chang(XD), Jarem Miller(MD)")
        self.assertEqual([(x.raw_name, x.event_hint) for x in h],
                         [("Yuen Yuen Chang", "XD"), ("Jarem Miller", "MD")])

    def test_space_joined_tags(self):
        h = parse_partners("Stanley Huang(mixed) Yuen Yuen Cheng (women)")
        self.assertEqual([(x.raw_name, x.event_hint) for x in h],
                         [("Stanley Huang", "XD"), ("Yuen Yuen Cheng", "WD")])

    def test_flexible_prose_trims_to_name(self):
        h = parse_partners("Simon or anyone else")
        self.assertEqual([x.raw_name for x in h], ["Simon"])

    def test_no_partner_prose(self):
        self.assertEqual(parse_partners("I don't have a partner:("), [])
        self.assertEqual(parse_partners(
            "I am also willing to do WD! It wouldn't let me select more than one."), [])
        self.assertEqual(parse_partners(""), [])

    def test_looks_like_name(self):
        self.assertTrue(looks_like_name("Sunny You"))
        self.assertFalse(looks_like_name("anyone"))
        self.assertFalse(looks_like_name(":("))

    def test_names_containing_prose_substrings(self):
        # Regression: "na" must not match inside real names like Anna/Keona.
        self.assertTrue(looks_like_name("Anna Child"))
        self.assertTrue(looks_like_name("Keona Wu"))
        self.assertEqual([x.raw_name for x in parse_partners("Anna Child")],
                         ["Anna Child"])
        self.assertEqual([x.raw_name for x in parse_partners("Keona Wu ")],
                         ["Keona Wu"])


class TestLegacyImport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        headers, rows = read_rows(FIXTURE)
        cls.result = build_tournament(headers, rows, schema="auto")
        cls.t = cls.result.tournament

    def test_adapter_detected(self):
        self.assertEqual(self.result.adapter, "legacy")

    def _find(self, full):
        return next((p for p in self.t.players.values() if p.full == full), None)

    def test_known_players(self):
        nick = self._find("Nicholas Chin")
        self.assertIsNotNone(nick)
        self.assertEqual(nick.gender, "M")
        self.assertEqual(nick.skill, 8)
        self.assertEqual(nick.events, ["MS"])

        brian = self._find("Brian Chi")
        self.assertIsNotNone(brian)
        self.assertEqual(brian.skill, 9)
        self.assertEqual(brian.gender, "M")

        sunny = self._find("Sunny You")
        self.assertIsNotNone(sunny)
        self.assertEqual(sunny.gender, "F")

        # Hyphenated / multi-word names survive normalization.
        self.assertIsNotNone(self._find("En-Chi Angel Lin"))

    def test_typo_partner_autoresolved(self):
        # "Sunny uou" -> Sunny You, "Brain Chi" -> Brian Chi should auto-fix.
        codes = {i.code for i in self.result.issues}
        self.assertIn("partner_typo_autofixed", codes)
        # And a resolved hint should point at the real Sunny You.
        sunny = self._find("Sunny You")
        resolved_targets = {
            h.resolved_player_id
            for r in self.t.registrations for h in r.partner_hints
            if h.resolved_player_id}
        self.assertIn(sunny.id, resolved_targets)

    def test_stub_created_for_unregistered_partner(self):
        stubs = [p for p in self.t.players.values() if p.is_stub]
        self.assertTrue(stubs, "expected at least one placeholder partner")
        # Stubs have no skill and unknown-ish gender by construction.
        for s in stubs:
            self.assertIsNone(s.skill)

    def test_import_has_registrations(self):
        self.assertGreater(len(self.t.registrations), 15)
        self.assertGreater(self.result.stats["players"], 15)


if __name__ == "__main__":
    unittest.main()
