"""M3: division building and pair formation."""

import os
import unittest

from tournament.engine.grouping import build_divisions
from tournament.ingest.importer import build_tournament
from tournament.ingest.source_csv import read_rows
from tournament.model.entities import (
    PartnerHint, Player, RegistrationEntry, Tournament,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "messy_legacy.csv")


def add_player(t, pid, first, last, gender, events, willing=True, partner=None,
              partner_event=None):
    t.players[pid] = Player(id=pid, first=first, last=last, gender=gender,
                            skill=5, events=events, willing_random=willing)
    hints = []
    if partner:
        hints.append(PartnerHint(raw_name=partner, event_hint=partner_event,
                                 resolved_player_id=partner, confidence=1.0))
    t.registrations.append(RegistrationEntry(row_index=len(t.registrations) + 2,
                                             player_id=pid, partner_hints=hints))


class TestPairFormation(unittest.TestCase):
    def test_explicit_and_leftover(self):
        t = Tournament()
        add_player(t, "a", "A", "A", "M", ["MD"], partner="b", partner_event="MD")
        add_player(t, "b", "B", "B", "M", ["MD"])
        add_player(t, "c", "C", "C", "M", ["MD"], partner="d", partner_event="MD")
        add_player(t, "d", "D", "D", "M", ["MD"])
        add_player(t, "e", "E", "E", "M", ["MD"], willing=False)  # solo, unwilling
        res = build_divisions(t, events=["MD"], rng_seed=1)
        div = next(iter(res.divisions.values()))
        self.assertEqual(len(div.entry_refs), 2)          # two pairs
        self.assertTrue(all(e.kind == "pair" for e in div.entry_refs))
        # Both explicit pairs exist.
        members = {frozenset(t.pairs[e.ref_id].player_ids) for e in div.entry_refs}
        self.assertIn(frozenset({"a", "b"}), members)
        self.assertIn(frozenset({"c", "d"}), members)
        self.assertIn("e", res.unpaired)

    def test_xd_pairs_man_with_woman(self):
        t = Tournament()
        add_player(t, "m1", "M1", "x", "M", ["XD"])
        add_player(t, "m2", "M2", "x", "M", ["XD"])
        add_player(t, "f1", "F1", "y", "F", ["XD"])
        add_player(t, "f2", "F2", "y", "F", ["XD"])
        res = build_divisions(t, events=["XD"], rng_seed=3)
        div = next(iter(res.divisions.values()))
        self.assertEqual(len(div.entry_refs), 2)
        for e in div.entry_refs:
            genders = {t.players[pid].gender for pid in t.pairs[e.ref_id].player_ids}
            self.assertEqual(genders, {"M", "F"})

    def test_auto_pairing_reproducible(self):
        def run():
            t = Tournament()
            for i in range(6):
                add_player(t, f"p{i}", f"P{i}", str(i), "M", ["MD"])
            res = build_divisions(t, events=["MD"], rng_seed=99)
            div = next(iter(res.divisions.values()))
            return sorted(tuple(sorted(t.pairs[e.ref_id].player_ids))
                          for e in div.entry_refs)
        self.assertEqual(run(), run())

    def test_singles_division(self):
        t = Tournament()
        add_player(t, "a", "A", "A", "M", ["MS"])
        add_player(t, "b", "B", "B", "M", ["MS"])
        res = build_divisions(t, events=["MS"], rng_seed=1)
        div = next(iter(res.divisions.values()))
        self.assertEqual(len(div.entry_refs), 2)
        self.assertTrue(all(e.kind == "player" for e in div.entry_refs))


class TestRealDataGrouping(unittest.TestCase):
    def test_divisions_from_real_import(self):
        headers, rows = read_rows(FIXTURE)
        t = build_tournament(headers, rows).tournament
        res = build_divisions(t, rng_seed=2026)
        by_event = {d.event for d in res.divisions.values()}
        # The 2026 form has entrants across all five events.
        self.assertTrue({"MS", "MD", "XD"} <= by_event)
        # Doubles divisions must contain pair entries, singles player entries.
        for d in res.divisions.values():
            kinds = {e.kind for e in d.entry_refs}
            if d.event in ("MD", "WD", "XD"):
                self.assertEqual(kinds, {"pair"})
            else:
                self.assertEqual(kinds, {"player"})


if __name__ == "__main__":
    unittest.main()
