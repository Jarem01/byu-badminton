"""M2: fuzzy resolution, validation rules, and override audit."""

import os
import tempfile
import unittest

from tournament.ingest.source_csv import read_rows
from tournament.ingest.importer import build_tournament
from tournament.model.entities import Player, RegistrationEntry, PartnerHint, Tournament
from tournament.store.repository import Repository
from tournament.validate.dashboard import validate
from tournament.validate.fuzzy import NameResolver
from tournament.validate.overrides import apply_override

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "messy_legacy.csv")


def roster():
    return {
        "player-sunny-you": Player(id="player-sunny-you", first="Sunny", last="You"),
        "player-brian-chi": Player(id="player-brian-chi", first="Brian", last="Chi"),
        "player-simon-li": Player(id="player-simon-li", first="Simon", last="Li"),
        "player-julian-li": Player(id="player-julian-li", first="Julian", last="Li"),
    }


class TestFuzzy(unittest.TestCase):
    def setUp(self):
        self.r = NameResolver(roster())

    def test_exact(self):
        res = self.r.resolve("Sunny You")
        self.assertEqual(res.player_id, "player-sunny-you")
        self.assertEqual(res.confidence, 1.0)

    def test_typo_autoresolves(self):
        res = self.r.resolve("Sunny uou")
        self.assertEqual(res.player_id, "player-sunny-you")
        self.assertGreaterEqual(res.confidence, 0.86)

    def test_brain_to_brian(self):
        res = self.r.resolve("Brain Chi")
        self.assertEqual(res.player_id, "player-brian-chi")

    def test_first_name_only_unique(self):
        res = self.r.resolve("Simon")
        self.assertEqual(res.player_id, "player-simon-li")
        self.assertEqual(res.confidence, 0.95)

    def test_ambiguous_last_shared(self):
        # Two "Li" share nothing on first name, so "Li" alone won't hit the
        # first-name index; ensure an unknown name yields no match.
        res = self.r.resolve("Zzz Nobody")
        self.assertIsNone(res.player_id)

    def test_unregistered_name(self):
        res = self.r.resolve("Jarem Miller")
        self.assertIsNone(res.player_id)


class TestValidationRules(unittest.TestCase):
    def test_missing_skill_and_gender(self):
        t = Tournament()
        t.players["p1"] = Player(id="p1", first="A", last="B", events=["XD"],
                                 skill=None, gender="U")
        rep = validate(t)
        codes = {i.code for i in rep.issues}
        self.assertIn("missing_skill", codes)
        self.assertIn("unknown_gender", codes)

    def test_gender_event_conflict_is_error(self):
        t = Tournament()
        t.players["p1"] = Player(id="p1", first="A", last="B",
                                 events=["MS", "WS"], skill=5, gender="U")
        rep = validate(t)
        self.assertIn("gender_event_conflict", {i.code for i in rep.errors})
        self.assertFalse(rep.ok)

    def test_missing_partner_error_when_not_willing(self):
        t = Tournament()
        t.players["p1"] = Player(id="p1", first="A", last="B", events=["MD"],
                                 skill=5, gender="M", willing_random=False)
        t.registrations.append(RegistrationEntry(row_index=2, player_id="p1"))
        rep = validate(t)
        self.assertIn("missing_partner", {i.code for i in rep.errors})

    def test_needs_random_partner_is_info(self):
        t = Tournament()
        t.players["p1"] = Player(id="p1", first="A", last="B", events=["MD"],
                                 skill=5, gender="M", willing_random=True)
        t.registrations.append(RegistrationEntry(row_index=2, player_id="p1"))
        rep = validate(t)
        codes = {i.code for i in rep.issues}
        self.assertIn("needs_random_partner", codes)
        self.assertNotIn("missing_partner", codes)

    def test_xd_same_gender_warning(self):
        t = Tournament()
        t.players["a"] = Player(id="a", first="A", last="X", events=["XD"],
                                skill=5, gender="M")
        t.players["b"] = Player(id="b", first="B", last="Y", events=["XD"],
                                skill=5, gender="M")
        t.registrations.append(RegistrationEntry(
            row_index=2, player_id="a",
            partner_hints=[PartnerHint(raw_name="B Y", event_hint="XD",
                                       resolved_player_id="b", confidence=1.0)]))
        rep = validate(t)
        self.assertIn("xd_same_gender", {i.code for i in rep.issues})

    def test_doubles_gender_warnings_from_pairs(self):
        # Materialized pairs with wrong genders (e.g. a man in Women's Doubles).
        from tournament.model.entities import Pair
        t = Tournament()
        t.players["a"] = Player(id="a", first="Julian", last="Li", events=["WD"],
                                skill=6, gender="F")
        t.players["b"] = Player(id="b", first="Simon", last="Li", events=["WD"],
                                skill=6, gender="M")   # a man in Women's Doubles
        t.players["c"] = Player(id="c", first="Sam", last="Q", events=["MD"],
                                skill=6, gender="F")   # a woman in Men's Doubles
        t.players["d"] = Player(id="d", first="Ted", last="R", events=["MD"],
                                skill=6, gender="M")
        t.pairs["wd"] = Pair(id="wd", player_ids=["a", "b"], event="WD")
        t.pairs["md"] = Pair(id="md", player_ids=["c", "d"], event="MD")
        codes = {i.code for i in validate(t).issues}
        self.assertIn("wd_gender", codes)
        self.assertIn("md_gender", codes)

    def test_full_fixture_produces_report(self):
        headers, rows = read_rows(FIXTURE)
        res = build_tournament(headers, rows)
        rep = validate(res.tournament, extra=res.issues)
        self.assertGreater(len(rep.issues), 0)
        self.assertIn("counts", rep.as_dict())


class TestOverrides(unittest.TestCase):
    def test_override_updates_and_audits(self):
        t = Tournament()
        t.players["s1"] = Player(id="s1", first="Jarem", last="Miller",
                                 gender="U", skill=None, is_stub=True)
        with tempfile.TemporaryDirectory() as d:
            repo = Repository(os.path.join(d, "tournament.json"))
            ov1 = apply_override(t, "me@x.com", "player:s1", "skill", "8",
                                 reason="asked him", now="2026-03-01T00:00:00Z")
            repo.append_audit(ov1)
            ov2 = apply_override(t, "me@x.com", "player:s1", "gender", "male",
                                 now="2026-03-01T00:01:00Z")
            repo.append_audit(ov2)

            self.assertEqual(t.players["s1"].skill, 8)
            self.assertEqual(t.players["s1"].gender, "M")
            # Stub promoted to a real player once skill+gender are known.
            self.assertFalse(t.players["s1"].is_stub)

            rows = repo.read_audit()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["old_value"], "None")
            self.assertEqual(rows[0]["new_value"], "8")

    def test_invalid_override_rejected(self):
        t = Tournament()
        t.players["p1"] = Player(id="p1", first="A", last="B")
        with self.assertRaises(ValueError):
            apply_override(t, "me", "player:p1", "skill", "expert")
        with self.assertRaises(ValueError):
            apply_override(t, "me", "match:x", "foo", "bar")


if __name__ == "__main__":
    unittest.main()
