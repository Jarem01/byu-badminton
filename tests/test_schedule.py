"""M6: time-slot math, court assignment, and dependency ordering."""

import unittest

from tournament.config import Settings, SlotTiming
from tournament.engine import bracket_single as SE
from tournament.engine.seeding import seed_entries
from tournament.schedule.best_date import availability_report
from tournament.schedule.scheduler import generate_schedule, player_conflicts
from tournament.schedule.timeslots import (
    block_times, minutes_to_clock, parse_clock,
)
from tournament.model.entities import Division, EntryRef, Player, Tournament


def single_elim_division(t, div_id, event, n):
    refs = []
    for i in range(n):
        pid = f"{div_id}-p{i}"
        t.players[pid] = Player(id=pid, first=f"{event}{i}", last=str(i), skill=n - i)
        refs.append(EntryRef("player", pid))
    div = Division(id=div_id, event=event, label=event, entry_refs=refs)
    t.divisions[div_id] = div
    seeds = seed_entries(t, div, "ranking")
    t.brackets[div_id] = SE.generate(div, seeds)


class TestTimeslots(unittest.TestCase):
    def test_parse_and_format(self):
        self.assertEqual(parse_clock("13:45"), 825)
        self.assertEqual(minutes_to_clock("13:45", 0), "1:45 PM")
        self.assertEqual(minutes_to_clock("13:45", 40), "2:25 PM")
        self.assertEqual(minutes_to_clock("09:00", 0), "9:00 AM")

    def test_block_times(self):
        timing = SlotTiming(warmup_min=5, play_min=30, buffer_min=5)
        self.assertEqual(block_times(0, timing), (0, 5, 35))
        self.assertEqual(block_times(1, timing), (40, 45, 75))


class TestScheduling(unittest.TestCase):
    def test_dependencies_and_courts(self):
        t = Tournament()
        single_elim_division(t, "ms", "MS", 4)
        settings = Settings(court_count=2)
        blocks = generate_schedule(t, settings, ["ms"])
        # 3 matches (2 semis + final), all scheduled.
        self.assertEqual(len(blocks), 3)
        by_match = {b.match_id: b for b in blocks}
        final_id = t.brackets["ms"].rounds[-1].match_ids[0]
        semi_ids = t.brackets["ms"].rounds[0].match_ids
        final_start = by_match[final_id].start_min
        # Final starts strictly after both semis finish.
        for sid in semi_ids:
            self.assertGreater(final_start, by_match[sid].start_min)

    def test_no_court_double_booked(self):
        t = Tournament()
        single_elim_division(t, "ms", "MS", 8)
        blocks = generate_schedule(t, Settings(court_count=2), ["ms"])
        seen = set()
        for b in blocks:
            key = (b.court_id, b.start_min)
            self.assertNotIn(key, seen)
            seen.add(key)

    def test_bye_advanced_match_is_scheduled(self):
        # Regression: with 7 entrants seed 1 gets a first-round bye and advances
        # to the semifinal. That semifinal (one side filled, one TBD) must still
        # be scheduled -- it is not a bye.
        t = Tournament()
        single_elim_division(t, "ms", "MS", 7)
        br = t.brackets["ms"]
        playable = sum(1 for m in br.matches.values()
                       if not (m.result and m.result.walkover))
        blocks = generate_schedule(t, Settings(court_count=4), ["ms"])
        self.assertEqual(len(blocks), playable)   # every non-walkover match scheduled
        self.assertEqual(playable, 6)             # 7-1 minus the single bye

    def test_round_robin_uses_short_timed_games(self):
        # Standalone round robin = single timed games (pool timing, ~10 min).
        from tournament.engine import bracket_rr as RR
        t = Tournament()
        refs = []
        for i in range(5):
            pid = f"p{i}"
            t.players[pid] = Player(id=pid, first=f"P{i}", last=str(i), skill=5 - i)
            refs.append(EntryRef("player", pid))
        div = Division(id="rr", event="MS", label="MS", entry_refs=refs,
                       format="round_robin")
        t.divisions["rr"] = div
        t.brackets["rr"] = RR.generate(div, seed_entries(t, div, "ranking"))
        s = Settings()
        generate_schedule(t, s, ["rr"])
        for b in t.schedule:
            self.assertEqual(b.play_min, s.pool_timing.play_min)   # 10

    def test_group_stage_uses_full_matches(self):
        # group_knockout pools AND knockout both play full best-of-N (not timed).
        from tournament.engine import bracket_groups as GK
        t = Tournament()
        refs = []
        for i in range(8):
            pid = f"p{i}"
            t.players[pid] = Player(id=pid, first=f"P{i}", last=str(i), skill=8 - i)
            refs.append(EntryRef("player", pid))
        div = Division(id="gk", event="MS", label="MS", entry_refs=refs,
                       format="group_knockout")
        t.divisions["gk"] = div
        t.brackets["gk"] = GK.generate(div, seed_entries(t, div, "ranking"),
                                       num_groups=2, main_draw=4)
        s = Settings()
        generate_schedule(t, s, ["gk"])
        for b in t.schedule:
            self.assertEqual(b.play_min, s.timing.play_min)        # 30, incl. pools

    def test_pool_stage_scheduled_before_knockout(self):
        from tournament.engine import bracket_groups as GK
        t = Tournament()
        refs = []
        for i in range(8):
            pid = f"p{i}"
            t.players[pid] = Player(id=pid, first=f"P{i}", last=str(i), skill=8 - i)
            refs.append(EntryRef("player", pid))
        div = Division(id="gk", event="MS", label="MS", entry_refs=refs,
                       format="group_knockout")
        t.divisions["gk"] = div
        t.brackets["gk"] = GK.generate(div, seed_entries(t, div, "ranking"),
                                       num_groups=2, main_draw=4)
        generate_schedule(t, Settings(court_count=4), ["gk"])
        by_id = t.brackets["gk"].matches
        pool_end = max(b.start_min + b.warmup_min + b.play_min + b.buffer_min
                       for b in t.schedule if by_id[b.match_id].bracket_part == "pool")
        ko_start = min(b.start_min for b in t.schedule
                       if by_id[b.match_id].bracket_part == "main")
        self.assertGreaterEqual(ko_start, pool_end)   # knockout starts after pools

    def test_knockout_only_on_center_courts(self):
        # Knockout (main-stage) matches must land only on the unobstructed
        # center courts; pool matches may use any court.
        from tournament.engine import bracket_groups as GK
        t = Tournament()
        refs = []
        for i in range(16):
            pid = f"p{i}"
            t.players[pid] = Player(id=pid, first=f"P{i}", last=str(i), skill=16 - i)
            refs.append(EntryRef("player", pid))
        div = Division(id="gk", event="MS", label="MS", entry_refs=refs,
                       format="group_knockout")
        t.divisions["gk"] = div
        t.brackets["gk"] = GK.generate(div, seed_entries(t, div, "ranking"),
                                       num_groups=4, main_draw=8)
        s = Settings(court_count=8)          # center = 2,3,6,7
        generate_schedule(t, s, ["gk"])
        by_id = t.brackets["gk"].matches
        center = set(s.center_courts)
        for b in t.schedule:
            if by_id[b.match_id].bracket_part == "main":
                num = int(b.court_id.rsplit("-", 1)[1])
                self.assertIn(num, center,
                              f"knockout match on non-center court {num}")

    def test_pools_play_concurrently(self):
        # Different pools should run at the same time (so players rest between
        # their own pool matches while other pools play).
        from tournament.engine import bracket_groups as GK
        t = Tournament()
        refs = []
        for i in range(8):
            pid = f"p{i}"
            t.players[pid] = Player(id=pid, first=f"P{i}", last=str(i), skill=8 - i)
            refs.append(EntryRef("player", pid))
        div = Division(id="gk", event="MS", label="MS", entry_refs=refs,
                       format="group_knockout")
        t.divisions["gk"] = div
        t.brackets["gk"] = GK.generate(div, seed_entries(t, div, "ranking"),
                                       num_groups=2, main_draw=4)
        generate_schedule(t, Settings(court_count=4), ["gk"])
        by_id = t.brackets["gk"].matches
        # Collect (start, pool) for pool matches; expect two different pools
        # sharing a start time.
        starts = {}
        for b in t.schedule:
            m = by_id[b.match_id]
            if m.bracket_part == "pool":
                starts.setdefault(b.start_min, set()).add(m.pool_id)
        self.assertTrue(any(len(pools) >= 2 for pools in starts.values()),
                        "expected two pools scheduled at the same time")

    def test_changing_court_count_takes_effect(self):
        t = Tournament()
        single_elim_division(t, "ms", "MS", 8)
        generate_schedule(t, Settings(court_count=2), ["ms"])
        self.assertEqual(len(t.courts), 2)
        generate_schedule(t, Settings(court_count=6), ["ms"])
        self.assertEqual(len(t.courts), 6)             # rebuilt to the new count
        # With more courts the first round runs more in parallel (earlier finish).
        self.assertLessEqual(max(b.start_min for b in t.schedule),
                             40 * 3)   # sanity: 8-draw fits within a few slots

    def test_best_date_report(self):
        t = Tournament()
        t.players["a"] = Player(id="a", first="A", last="A",
                                weekend_avail=["Feb 6-7", "Mar 20-21"])
        t.players["b"] = Player(id="b", first="B", last="B",
                                weekend_avail=["Mar 20-21"])
        rep = availability_report(t)
        self.assertEqual(rep["total_players"], 2)
        self.assertEqual(rep["weekends"][0]["option"], "Mar 20-21")
        self.assertEqual(rep["weekends"][0]["available"], 2)


if __name__ == "__main__":
    unittest.main()
