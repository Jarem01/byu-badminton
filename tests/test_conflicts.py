"""M6: multi-event players are never double-booked across divisions."""

import unittest

from tournament.config import Settings
from tournament.engine import bracket_single as SE
from tournament.engine.seeding import seed_entries
from tournament.schedule.scheduler import (
    generate_schedule, match_player_ids, player_conflicts,
)
from tournament.model.entities import (
    Division, EntryRef, Pair, Player, Tournament,
)


def build():
    t = Tournament()
    # Players; p_shared plays both MS and (as a pair) MD.
    for pid in ("shared", "ms2", "ms3", "ms4", "q1", "m2a", "m2b", "q2"):
        t.players[pid] = Player(id=pid, first=pid, last="x", skill=5, gender="M",
                                events=["MS", "MD"])
    # MS singles division with 4 entrants incl. the shared player.
    ms = Division(id="ms", event="MS", label="MS",
                  entry_refs=[EntryRef("player", p) for p in ("shared", "ms2", "ms3", "ms4")])
    t.divisions["ms"] = ms
    t.brackets["ms"] = SE.generate(ms, seed_entries(t, ms, "ranking"))
    # MD doubles division: (shared,q1) vs (m2a,m2b) etc.
    t.pairs["pairA"] = Pair(id="pairA", player_ids=["shared", "q1"], event="MD")
    t.pairs["pairB"] = Pair(id="pairB", player_ids=["m2a", "m2b"], event="MD")
    md = Division(id="md", event="MD", label="MD",
                  entry_refs=[EntryRef("pair", "pairA"), EntryRef("pair", "pairB")])
    t.divisions["md"] = md
    t.brackets["md"] = SE.generate(md, seed_entries(t, md, "ranking"))
    return t


class TestConflicts(unittest.TestCase):
    def test_shared_player_not_double_booked(self):
        t = build()
        generate_schedule(t, Settings(court_count=4), ["ms", "md"])
        # Post-condition check must find no overlaps.
        self.assertEqual(player_conflicts(t), [])

        # The shared player's two first-round matches must be in different slots.
        by_match = {b.match_id: b for b in t.schedule}
        shared_blocks = []
        for br in t.brackets.values():
            for m in br.matches.values():
                if "shared" in match_player_ids(t, m) and m.id in by_match:
                    shared_blocks.append(by_match[m.id].start_min)
        self.assertEqual(len(set(shared_blocks)), len(shared_blocks),
                         "shared player scheduled at overlapping times")

    def test_round_robin_never_double_books_and_rests(self):
        # Round robin: every player plays many matches. Verify the hard security
        # guarantee — no player is ever in two at once, and each gets >= rest_min.
        from tournament.engine import bracket_rr as RR
        from tournament.engine.seeding import seed_entries
        t = Tournament()
        refs = []
        for i in range(6):
            pid = f"r{i}"
            t.players[pid] = Player(id=pid, first=f"R{i}", last=str(i), skill=6 - i,
                                    events=["MS"])
            refs.append(EntryRef("player", pid))
        div = Division(id="rr", event="MS", label="MS", entry_refs=refs,
                       format="round_robin")
        t.divisions["rr"] = div
        t.brackets["rr"] = RR.generate(div, seed_entries(t, div, "ranking"))
        settings = Settings(court_count=4, rest_min=10)
        generate_schedule(t, settings, ["rr"])
        self.assertEqual(player_conflicts(t), [])
        by_match = {b.match_id: b for b in t.schedule}
        windows = {}
        for br in t.brackets.values():
            for m in br.matches.values():
                if m.id in by_match:
                    b = by_match[m.id]
                    for pid in match_player_ids(t, m):
                        windows.setdefault(pid, []).append(
                            (b.play_start_min, b.play_start_min + b.play_min))
        for wins in windows.values():
            wins.sort()
            for i in range(1, len(wins)):
                self.assertGreaterEqual(wins[i][0] - wins[i - 1][1], settings.rest_min)

    def test_rest_gap_respected(self):
        t = build()
        settings = Settings(court_count=4, rest_min=10)
        generate_schedule(t, settings, ["ms", "md"])
        by_match = {b.match_id: b for b in t.schedule}
        blocks = []
        for br in t.brackets.values():
            for m in br.matches.values():
                if "shared" in match_player_ids(t, m) and m.id in by_match:
                    b = by_match[m.id]
                    blocks.append((b.play_start_min, b.play_start_min + b.play_min))
        blocks.sort()
        for i in range(1, len(blocks)):
            gap = blocks[i][0] - blocks[i - 1][1]
            self.assertGreaterEqual(gap, settings.rest_min)


if __name__ == "__main__":
    unittest.main()
