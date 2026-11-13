"""M7: round-robin generation (circle method)."""

import unittest

from tournament.engine import bracket_rr as RR
from tournament.engine.seeding import seed_entries
from tournament.model.entities import Division, EntryRef, Player, Tournament


def rr_division(n):
    t = Tournament()
    refs = []
    for i in range(n):
        pid = f"p{i}"
        t.players[pid] = Player(id=pid, first=f"P{i}", last=str(i), skill=n - i)
        refs.append(EntryRef("player", pid))
    div = Division(id="d", event="MS", label="MS", entry_refs=refs)
    return t, div, seed_entries(t, div, "ranking")


class TestCircleMethod(unittest.TestCase):
    def test_match_counts(self):
        for n in (2, 3, 4, 5, 6):
            rounds = RR.circle_rounds([EntryRef("player", f"p{i}") for i in range(n)])
            total = sum(len(r) for r in rounds)
            self.assertEqual(total, n * (n - 1) // 2, f"n={n}")

    def test_everyone_plays_everyone_once(self):
        n = 6
        entries = [EntryRef("player", f"p{i}") for i in range(n)]
        rounds = RR.circle_rounds(entries)
        seen = set()
        for r in rounds:
            for a, b in r:
                key = frozenset({a.ref_id, b.ref_id})
                self.assertNotIn(key, seen)  # no repeat pairing
                seen.add(key)
        self.assertEqual(len(seen), n * (n - 1) // 2)

    def test_odd_gives_one_bye_per_round(self):
        n = 5
        entries = [EntryRef("player", f"p{i}") for i in range(n)]
        rounds = RR.circle_rounds(entries)
        for r in rounds:
            self.assertEqual(len(r), 2)  # 5 players -> 2 matches + 1 resting

    def test_generate_bracket(self):
        t, div, seeds = rr_division(4)
        br = RR.generate(div, seeds)
        self.assertEqual(br.format, "round_robin")
        self.assertEqual(len(br.pools), 1)
        self.assertEqual(len(br.matches), 6)


if __name__ == "__main__":
    unittest.main()
