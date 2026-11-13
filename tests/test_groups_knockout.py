"""M7: group -> clean power-of-two knockout (no byes).

The knockout is filled entirely with real teams: ``base`` finishers per pool
(top 1 or 2) plus the best-remaining "wildcards" across pools, ranked by
per-match ratios."""

import unittest

from tournament.engine import bracket_groups as GK
from tournament.engine.advancement import champion, record_result
from tournament.engine.seeding import seed_entries
from tournament.model.entities import Division, EntryRef, Player, Tournament


def make(n):
    t = Tournament()
    refs = []
    for i in range(n):
        pid = f"p{i}"
        t.players[pid] = Player(id=pid, first=f"P{i}", last=str(i), skill=n - i)
        refs.append(EntryRef("player", pid))
    div = Division(id="d", event="MS", label="MS", entry_refs=refs,
                   format="group_knockout")
    return t, div, seed_entries(t, div, "ranking")


def play_favorites(t, br, seeds, part):
    seed_no = {s.entry.key(): s.seed_no for s in seeds}
    progressed = True
    while progressed:
        progressed = False
        for m in br.matches.values():
            if m.bracket_part != part:
                continue
            if m.result is None and m.is_ready():
                s1 = seed_no.get(m.side1.key(), 999)
                s2 = seed_no.get(m.side2.key(), 999)
                games = [[21, 5], [21, 5]] if s1 < s2 else [[5, 21], [5, 21]]
                record_result(br, m.id, games)
                progressed = True


def _ko_first_round(br):
    return next(r for r in br.rounds if r.bracket_part == "main")


class TestPlan(unittest.TestCase):
    def test_resolve_group_plan_no_byes(self):
        # 11 teams, 2 pools, target 8-draw: top 2 each (4) + 4 wildcards = 8.
        g, m, base, wild = GK.resolve_group_plan(11, num_groups=2, main_draw=8)
        self.assertEqual((g, m, base, wild), (2, 8, 2, 4))
        # Draw can never exceed the real field (clamped to largest power of two).
        g, m, base, wild = GK.resolve_group_plan(6, num_groups=2, main_draw=32)
        self.assertEqual(m, 4)                 # largest_pow2_le(6)
        self.assertEqual(base * g + wild, m)   # always fills exactly, no byes

    def test_base_capped_at_two(self):
        # Even with a big draw per pool, base never exceeds 2 (top 1 or 2).
        g, m, base, wild = GK.resolve_group_plan(16, num_groups=2, main_draw=16)
        self.assertEqual(base, 2)
        self.assertEqual(wild, 16 - 4)


class TestGroupKnockout(unittest.TestCase):
    def test_structure_two_groups(self):
        t, div, seeds = make(8)
        br = GK.generate(div, seeds, num_groups=2, main_draw=4)
        self.assertEqual(len(br.pools), 2)
        self.assertEqual(sorted(len(p.entry_refs) for p in br.pools), [4, 4])
        # Each pool: RR of 4 -> 6 matches (12 total); knockout of 4 -> 3 matches.
        pool_matches = [m for m in br.matches.values() if m.bracket_part == "pool"]
        ko_matches = [m for m in br.matches.values() if m.bracket_part == "main"]
        self.assertEqual(len(pool_matches), 12)
        self.assertEqual(len(ko_matches), 3)

    def test_knockout_placeholders_before_pools(self):
        t, div, seeds = make(8)
        br = GK.generate(div, seeds, num_groups=2, main_draw=4)
        sides = [br.matches[mid].side1 for mid in _ko_first_round(br).match_ids] + \
                [br.matches[mid].side2 for mid in _ko_first_round(br).match_ids]
        self.assertTrue(all(s.kind == "slot" for s in sides))

    def test_full_flow_favorite_wins(self):
        t, div, seeds = make(8)
        br = GK.generate(div, seeds, num_groups=2, main_draw=4)
        play_favorites(t, br, seeds, "pool")
        self.assertTrue(GK.fill_knockout_from_pools(t, br))
        for mid in _ko_first_round(br).match_ids:
            m = br.matches[mid]
            self.assertIn(m.side1.kind, ("player", "pair"))
            self.assertIn(m.side2.kind, ("player", "pair"))
        play_favorites(t, br, seeds, "main")
        self.assertEqual(champion(br), seeds[0].entry)

    def test_wildcards_fill_clean_draw_no_byes(self):
        # 11 teams, 2 pools, 8-draw: 4 pool qualifiers + 4 best-remaining, all
        # real teams -- no byes anywhere in the knockout.
        t, div, seeds = make(11)
        br = GK.generate(div, seeds, num_groups=2, main_draw=8)
        self.assertEqual(len(_ko_first_round(br).match_ids), 4)   # 8-draw
        play_favorites(t, br, seeds, "pool")
        self.assertTrue(GK.fill_knockout_from_pools(t, br))
        sides = []
        for mid in _ko_first_round(br).match_ids:
            m = br.matches[mid]
            self.assertIsNone(m.result)                 # no auto-forfeit byes
            self.assertIn(m.side1.kind, ("player", "pair"))
            self.assertIn(m.side2.kind, ("player", "pair"))
            sides += [m.side1.key(), m.side2.key()]
        self.assertEqual(len(set(sides)), 8)            # 8 distinct real teams
        play_favorites(t, br, seeds, "main")
        self.assertEqual(champion(br), seeds[0].entry)

    def test_wildcards_wait_for_all_pools(self):
        # Wildcard slots need a cross-pool ranking, so they stay placeholders
        # until EVERY pool is complete -- but base (pool-position) slots for a
        # finished pool fill right away.
        t, div, seeds = make(11)
        br = GK.generate(div, seeds, num_groups=2, main_draw=8)
        pool_a = br.pools[0].id
        seed_no = {s.entry.key(): s.seed_no for s in seeds}
        for m in br.matches.values():
            if m.pool_id == pool_a and m.is_ready():
                s1, s2 = seed_no[m.side1.key()], seed_no[m.side2.key()]
                record_result(br, m.id,
                              [[21, 5], [21, 5]] if s1 < s2 else [[5, 21], [5, 21]])
        GK.fill_knockout_from_pools(t, br)
        sides = [br.matches[mid].side1 for mid in _ko_first_round(br).match_ids] + \
                [br.matches[mid].side2 for mid in _ko_first_round(br).match_ids]
        # Pool A base finishers are placed; wildcard slots remain "W#" slots.
        self.assertTrue(any(s and s.kind in ("player", "pair") for s in sides))
        self.assertTrue(any(s and s.kind == "slot" and s.ref_id.startswith("W")
                            for s in sides))

    def test_project_qualifiers_marks_auto_and_wildcard(self):
        # 11 teams, 2 pools, 8-draw -> 4 auto (top 2 each) + 4 wildcards. The
        # projection is recomputed from current standings, so it updates live.
        t, div, seeds = make(11)
        br = GK.generate(div, seeds, num_groups=2, main_draw=8)
        play_favorites(t, br, seeds, "pool")
        cls = GK.project_qualifiers(t, br)
        self.assertEqual(sum(1 for v in cls.values() if v == "auto"), 4)
        self.assertEqual(sum(1 for v in cls.values() if v == "wildcard"), 4)
        # The 8 projected qualifiers are exactly the 8 who fill the knockout.
        GK.fill_knockout_from_pools(t, br)
        ko_keys = set()
        for mid in _ko_first_round(br).match_ids:
            m = br.matches[mid]
            ko_keys |= {m.side1.key(), m.side2.key()}
        self.assertEqual(set(cls), ko_keys)

    def test_per_pool_population(self):
        # With no wildcards (4-draw), a completed pool populates its knockout
        # slots immediately, without waiting for the other pool.
        t, div, seeds = make(8)
        br = GK.generate(div, seeds, num_groups=2, main_draw=4)
        pool_a = br.pools[0].id
        seed_no = {s.entry.key(): s.seed_no for s in seeds}
        for m in br.matches.values():
            if m.pool_id == pool_a and m.is_ready():
                s1, s2 = seed_no[m.side1.key()], seed_no[m.side2.key()]
                record_result(br, m.id,
                              [[21, 5], [21, 5]] if s1 < s2 else [[5, 21], [5, 21]])
        self.assertTrue(GK.fill_knockout_from_pools(t, br))
        sides = [br.matches[mid].side1 for mid in _ko_first_round(br).match_ids] + \
                [br.matches[mid].side2 for mid in _ko_first_round(br).match_ids]
        kinds = {s.kind for s in sides if s}
        self.assertIn("player", kinds)   # pool A's finishers are placed
        self.assertIn("slot", kinds)     # pool B is still a placeholder


if __name__ == "__main__":
    unittest.main()
