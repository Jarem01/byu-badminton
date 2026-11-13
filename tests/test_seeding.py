"""M3: seeding order, bye placement, and seeding methods."""

import unittest

from tournament.engine.seeding import (
    next_power_of_two, num_byes, place_seeds_in_slots, seed_entries,
    standard_bracket_order,
)
from tournament.model.entities import Division, EntryRef, Player, Seed, Tournament


class TestPow2AndByes(unittest.TestCase):
    def test_next_power_of_two(self):
        cases = {1: 1, 2: 2, 3: 4, 4: 4, 5: 8, 7: 8, 8: 8, 9: 16, 16: 16, 17: 32}
        for n, expected in cases.items():
            self.assertEqual(next_power_of_two(n), expected, n)

    def test_num_byes(self):
        self.assertEqual(num_byes(8), 0)
        self.assertEqual(num_byes(5), 3)
        self.assertEqual(num_byes(6), 2)
        self.assertEqual(num_byes(17), 15)   # BWF worked example


class TestBracketOrder(unittest.TestCase):
    def test_small(self):
        self.assertEqual(standard_bracket_order(2), [1, 2])
        self.assertEqual(standard_bracket_order(4), [1, 4, 2, 3])
        self.assertEqual(standard_bracket_order(8), [1, 8, 4, 5, 2, 7, 3, 6])

    def test_properties(self):
        for size in (4, 8, 16, 32):
            order = standard_bracket_order(size)
            self.assertEqual(sorted(order), list(range(1, size + 1)))
            self.assertEqual(order[0], 1)                 # seed 1 top slot
            self.assertEqual(order[size // 2], 2)         # seed 2 opposite half
            # Top 4 seeds each in a different quarter.
            q = size // 4
            quarters = {s: i // q for i, s in enumerate(order)}
            self.assertEqual(len({quarters[s] for s in (1, 2, 3, 4)}), 4)

    def test_rejects_non_power_of_two(self):
        with self.assertRaises(ValueError):
            standard_bracket_order(6)


class TestByePlacement(unittest.TestCase):
    def test_byes_go_to_top_seeds(self):
        seeds = [Seed(EntryRef("player", f"p{i}"), i) for i in range(1, 6)]  # 5 entries
        slots, size = place_seeds_in_slots(seeds)
        self.assertEqual(size, 8)
        self.assertEqual(sum(1 for s in slots if s is None), 3)
        # Round-1 matches: a bye is a match with exactly one side.
        bye_seeds = []
        for i in range(0, size, 2):
            a, b = slots[i], slots[i + 1]
            if (a is None) ^ (b is None):
                present = a or b
                bye_seeds.append(int(present.ref_id[1:]))
        self.assertEqual(sorted(bye_seeds), [1, 2, 3])  # top 3 seeds get byes


def _t_with_skills(skills):
    t = Tournament()
    refs = []
    for i, sk in enumerate(skills):
        pid = f"p{i}"
        t.players[pid] = Player(id=pid, first=f"P{i}", last=str(i), skill=sk)
        refs.append(EntryRef("player", pid))
    div = Division(id="d", event="MS", label="MS", entry_refs=refs)
    return t, div


class TestSeedMethods(unittest.TestCase):
    def test_ranking_orders_by_skill_desc(self):
        t, div = _t_with_skills([3, 9, 6, None])
        seeds = seed_entries(t, div, "ranking")
        order_ids = [s.entry.ref_id for s in seeds]
        self.assertEqual(order_ids, ["p1", "p2", "p0", "p3"])  # 9,6,3,None
        self.assertEqual([s.seed_no for s in seeds], [1, 2, 3, 4])

    def test_ranking_is_deterministic_on_ties(self):
        t, div = _t_with_skills([5, 5, 5])
        a = [s.entry.ref_id for s in seed_entries(t, div, "ranking")]
        b = [s.entry.ref_id for s in seed_entries(t, div, "ranking")]
        self.assertEqual(a, b)

    def test_random_reproducible_with_seed(self):
        t, div = _t_with_skills([1, 2, 3, 4, 5, 6, 7, 8])
        a = [s.entry.ref_id for s in seed_entries(t, div, "random", rng_seed=42)]
        b = [s.entry.ref_id for s in seed_entries(t, div, "random", rng_seed=42)]
        c = [s.entry.ref_id for s in seed_entries(t, div, "random", rng_seed=7)]
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)  # extremely likely different

    def test_manual(self):
        t, div = _t_with_skills([1, 2, 3])
        order = ["player:p2", "player:p0", "player:p1"]
        seeds = seed_entries(t, div, "manual", manual_order=order)
        self.assertEqual([s.entry.ref_id for s in seeds], ["p2", "p0", "p1"])

    def test_manual_rejects_bad_order(self):
        t, div = _t_with_skills([1, 2, 3])
        with self.assertRaises(ValueError):
            seed_entries(t, div, "manual", manual_order=["player:p0"])


if __name__ == "__main__":
    unittest.main()
