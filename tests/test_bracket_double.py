"""M8: double elimination — WB/LB structure, drops, grand final, reset."""

import unittest

from tournament.engine import bracket_double as DE
from tournament.engine.advancement import record_result
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
                   format="double_elim")
    return t, div, seed_entries(t, div, "ranking")


def win(br, mid, side1_wins=True):
    record_result(br, mid, [[21, 5], [21, 5]] if side1_wins else [[5, 21], [5, 21]])


class TestStructure(unittest.TestCase):
    def test_match_counts_four(self):
        t, div, seeds = make(4)
        br = DE.generate(div, seeds)
        wb = [m for m in br.matches.values() if m.bracket_part == "winners"]
        lb = [m for m in br.matches.values() if m.bracket_part == "losers"]
        gf = [m for m in br.matches.values() if m.bracket_part == "grand_final"]
        self.assertEqual(len(wb), 3)   # n-1
        self.assertEqual(len(lb), 2)   # n-2
        self.assertEqual(len(gf), 2)   # grand final + reset slot

    def test_match_counts_eight(self):
        t, div, seeds = make(8)
        br = DE.generate(div, seeds)
        wb = [m for m in br.matches.values() if m.bracket_part == "winners"]
        lb = [m for m in br.matches.values() if m.bracket_part == "losers"]
        self.assertEqual(len(wb), 7)   # n-1
        self.assertEqual(len(lb), 6)   # n-2

    def test_any_size_generates_and_resolves_byes(self):
        # Non-power-of-two field: byes fill the draw and auto-resolve so no bye
        # match is left playable, and top seeds get first-round byes.
        for n in (5, 6, 7, 11):
            t, div, seeds = make(n)
            br = DE.generate(div, seeds)
            for m in br.matches.values():
                if m.side1 and m.side2:
                    # No unresolved match should contain a bye filler.
                    if m.result is None:
                        self.assertNotEqual(m.side1.kind, "bye", f"n={n}")
                        self.assertNotEqual(m.side2.kind, "bye", f"n={n}")

    def test_wb_losers_drop_into_lb(self):
        t, div, seeds = make(4)
        br = DE.generate(div, seeds)
        wb_r0 = [m for m in br.matches.values()
                 if m.bracket_part == "winners" and m.id.startswith("d-wb-r0")]
        for m in wb_r0:
            self.assertIsNotNone(m.next_lose_match)  # loser has a destination


class TestPlaythrough(unittest.TestCase):
    def _play_all_wb_favorites(self, br, seeds):
        seed_no = {s.entry.key(): s.seed_no for s in seeds}
        progressed = True
        while progressed:
            progressed = False
            for m in list(br.matches.values()):
                if m.bracket_part == "winners" and m.result is None and m.is_ready():
                    s1 = seed_no.get(m.side1.key(), 999)
                    s2 = seed_no.get(m.side2.key(), 999)
                    win(br, m.id, s1 < s2)
                    progressed = True

    def test_favorite_undefeated_is_champion_without_reset(self):
        t, div, seeds = make(4)
        br = DE.generate(div, seeds)
        # Resolve every match with the higher seed winning, all brackets.
        seed_no = {s.entry.key(): s.seed_no for s in seeds}
        progressed = True
        while progressed:
            progressed = False
            for m in list(br.matches.values()):
                if m.id == "d-gf-2":
                    continue  # reset only if needed
                if m.result is None and m.is_ready():
                    s1 = seed_no.get(m.side1.key(), 999)
                    s2 = seed_no.get(m.side2.key(), 999)
                    win(br, m.id, s1 < s2)
                    from tournament.engine.bracket_double import after_result
                    after_result(br, m.id)
                    progressed = True
        # Top seed won WB and the grand final => champion, no reset played.
        self.assertEqual(DE.champion(br), seeds[0].entry)
        self.assertIsNone(br.matches["d-gf-2"].result)

    def test_any_size_favorite_wins(self):
        # Full double-elim playthrough for a non-power-of-two field (6): the top
        # seed should win it all when favorites hold, byes included.
        from tournament.engine.bracket_double import after_result
        t, div, seeds = make(6)
        br = DE.generate(div, seeds)
        seed_no = {s.entry.key(): s.seed_no for s in seeds}
        for _ in range(500):
            progressed = False
            for m in list(br.matches.values()):
                if m.result is not None:
                    continue
                if (m.side1 and m.side2 and m.side1.kind in ("player", "pair")
                        and m.side2.kind in ("player", "pair")):
                    s1 = seed_no.get(m.side1.key(), 999)
                    s2 = seed_no.get(m.side2.key(), 999)
                    win(br, m.id, s1 < s2)
                    after_result(br, m.id)
                    progressed = True
            if not progressed:
                break
        self.assertEqual(DE.champion(br), seeds[0].entry)

    def test_bracket_reset_when_lb_finalist_wins_first_gf(self):
        t, div, seeds = make(4)
        br = DE.generate(div, seeds)
        # Play WB so seed1 reaches the grand final from the winners side.
        self._play_all_wb_favorites(br, seeds)
        # Play LB so someone arrives as the LB finalist.
        seed_no = {s.entry.key(): s.seed_no for s in seeds}
        progressed = True
        while progressed:
            progressed = False
            for m in list(br.matches.values()):
                if m.bracket_part == "losers" and m.result is None and m.is_ready():
                    win(br, m.id, True)  # slot1 wins
                    progressed = True
        gf1 = br.matches["d-gf-1"]
        self.assertTrue(gf1.is_ready())
        # LB finalist (slot2) wins the first grand final -> reset activates.
        win(br, "d-gf-1", side1_wins=False)
        DE.after_result(br, "d-gf-1")
        reset = br.matches["d-gf-2"]
        self.assertIsNotNone(reset.side1)
        self.assertIsNotNone(reset.side2)
        self.assertIsNone(DE.champion(br))  # not decided until reset is played
        # Play the reset; its winner is the champion.
        win(br, "d-gf-2", side1_wins=True)
        self.assertIsNotNone(DE.champion(br))


if __name__ == "__main__":
    unittest.main()
