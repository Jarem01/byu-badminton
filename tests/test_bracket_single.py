"""M4: single-elimination generation, byes, and advancement."""

import os
import unittest

from tournament.engine import bracket_single as SE
from tournament.engine.advancement import champion, record_result
from tournament.engine.grouping import build_divisions
from tournament.engine.seeding import seed_entries
from tournament.ingest.importer import build_tournament
from tournament.ingest.source_csv import read_rows
from tournament.model.entities import Division, EntryRef, Player, Tournament

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "messy_legacy.csv")


def make_division(n):
    """n players with distinct descending skills (p0 strongest)."""
    t = Tournament()
    refs = []
    for i in range(n):
        pid = f"p{i}"
        t.players[pid] = Player(id=pid, first=f"P{i}", last=str(i), skill=n - i)
        refs.append(EntryRef("player", pid))
    div = Division(id="d", event="MS", label="MS", entry_refs=refs)
    seeds = seed_entries(t, div, "ranking")
    return t, div, seeds


def simulate_favorites(bracket, seeds):
    """Play every match with the higher seed (lower seed_no) winning."""
    seed_no = {s.entry.key(): s.seed_no for s in seeds}
    progressed = True
    while progressed:
        progressed = False
        for m in bracket.matches.values():
            if m.result is None and m.is_ready():
                s1 = seed_no.get(m.side1.key(), 999)
                s2 = seed_no.get(m.side2.key(), 999)
                games = [[21, 10], [21, 10]] if s1 < s2 else [[10, 21], [10, 21]]
                record_result(bracket, m.id, games)
                progressed = True


class TestStructure(unittest.TestCase):
    def test_eight_entrants(self):
        t, div, seeds = make_division(8)
        br = SE.generate(div, seeds)
        self.assertEqual([r.name for r in br.rounds],
                         ["Quarterfinal", "Semifinal", "Final"])
        self.assertEqual(len(br.matches), 7)   # 4 + 2 + 1
        # Round 1 top match is seed 1 vs seed 8.
        r1 = [br.matches[mid] for mid in br.rounds[0].match_ids]
        self.assertEqual(r1[0].side1.ref_id, "p0")   # seed 1
        self.assertEqual(r1[0].side2.ref_id, "p7")   # seed 8

    def test_favorite_wins_out(self):
        t, div, seeds = make_division(8)
        br = SE.generate(div, seeds)
        simulate_favorites(br, seeds)
        champ = champion(br)
        self.assertEqual(champ.ref_id, "p0")   # top seed champions


class TestByes(unittest.TestCase):
    def test_five_entrants_byes_to_top_three(self):
        t, div, seeds = make_division(5)
        br = SE.generate(div, seeds)
        r1 = [br.matches[mid] for mid in br.rounds[0].match_ids]
        byes = [m for m in r1 if m.is_bye()]
        self.assertEqual(len(byes), 3)
        # Byes are auto-resolved (walkover) on generation...
        for m in byes:
            self.assertIsNotNone(m.result)
            self.assertTrue(m.result.walkover)
        # ...and the semifinal already has the three bye-winners seeded in.
        sf = [br.matches[mid] for mid in br.rounds[1].match_ids]
        seeded_present = sum(1 for m in sf for s in (m.side1, m.side2) if s)
        self.assertEqual(seeded_present, 3)

    def test_five_entrants_champion(self):
        t, div, seeds = make_division(5)
        br = SE.generate(div, seeds)
        simulate_favorites(br, seeds)
        self.assertEqual(champion(br).ref_id, "p0")


class TestAdvancement(unittest.TestCase):
    def test_winner_flows_to_next_round(self):
        t, div, seeds = make_division(4)
        br = SE.generate(div, seeds)
        # Round 0: (p0 v p3) and (p1 v p2). Winner of match 0 -> Final slot 1.
        m0 = br.matches[br.rounds[0].match_ids[0]]
        record_result(br, m0.id, [[21, 5], [21, 5]])
        final = br.matches[br.rounds[1].match_ids[0]]
        self.assertEqual(final.side1.ref_id, "p0")
        self.assertIsNone(final.side2)  # other semi not played yet

    def test_edit_score_same_winner_keeps_downstream(self):
        t, div, seeds = make_division(4)
        br = SE.generate(div, seeds)
        m0 = br.matches[br.rounds[0].match_ids[0]]
        m1 = br.matches[br.rounds[0].match_ids[1]]
        final = br.matches[br.rounds[1].match_ids[0]]
        record_result(br, m0.id, [[21, 5], [21, 5]])       # p0 wins -> final s1
        record_result(br, m1.id, [[21, 5], [21, 5]])       # p1 wins -> final s2
        record_result(br, final.id, [[21, 5], [21, 5]])    # p0 champion
        self.assertEqual(champion(br).ref_id, "p0")
        # Correct m0's score but SAME winner -> final result must survive.
        record_result(br, m0.id, [[21, 18], [21, 19]])
        self.assertEqual(final.side1.ref_id, "p0")
        self.assertIsNotNone(final.result)
        self.assertEqual(champion(br).ref_id, "p0")

    def test_edit_score_flips_winner_recascades(self):
        t, div, seeds = make_division(4)
        br = SE.generate(div, seeds)
        m0 = br.matches[br.rounds[0].match_ids[0]]   # p0 vs p3
        m1 = br.matches[br.rounds[0].match_ids[1]]
        final = br.matches[br.rounds[1].match_ids[0]]
        record_result(br, m0.id, [[21, 5], [21, 5]])       # p0 advances
        record_result(br, m1.id, [[21, 5], [21, 5]])
        record_result(br, final.id, [[21, 5], [21, 5]])    # p0 champion
        # Now flip m0 so p3 wins -> final's old winner (p0) must be cleared and
        # the final result invalidated (needs replay).
        record_result(br, m0.id, [[10, 21], [10, 21]])
        self.assertEqual(final.side1.ref_id, "p3")
        self.assertIsNone(final.result)
        self.assertIsNone(champion(br))

    def test_tie_rejected(self):
        t, div, seeds = make_division(2)
        br = SE.generate(div, seeds)
        mid = br.rounds[0].match_ids[0]
        with self.assertRaises(ValueError):
            record_result(br, mid, [[21, 10], [10, 21]])  # 1-1 games


class TestTinyBrackets(unittest.TestCase):
    def test_two(self):
        t, div, seeds = make_division(2)
        br = SE.generate(div, seeds)
        self.assertEqual(len(br.matches), 1)
        self.assertEqual(br.rounds[0].name, "Final")

    def test_one_and_zero(self):
        for n in (0, 1):
            t, div, seeds = make_division(n)
            br = SE.generate(div, seeds)
            self.assertEqual(len(br.matches), 0)


class TestFullPipeline(unittest.TestCase):
    def test_real_ms_division(self):
        headers, rows = read_rows(FIXTURE)
        t = build_tournament(headers, rows).tournament
        build_divisions(t, rng_seed=2026)
        ms = next(d for d in t.divisions.values() if d.event == "MS")
        seeds = seed_entries(t, ms, "ranking")
        br = SE.generate(ms, seeds)
        simulate_favorites(br, seeds)
        # The strongest MS entrant (seed 1) should win when favorites hold.
        self.assertEqual(champion(br), seeds[0].entry)


if __name__ == "__main__":
    unittest.main()
