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

    def test_chosen_center_courts_are_honoured(self):
        # The knockout courts used to be fixed at 2,3,6,7; the organizer can pick
        # them now, and the scheduler follows.
        t = Tournament()
        single_elim_division(t, "ms", "MS", 8)
        blocks = generate_schedule(t, Settings(court_count=6, center_courts=(1, 5)),
                                   ["ms"])
        semi_final = t.brackets["ms"].rounds[1].match_ids
        by_match = {b.match_id: b for b in blocks}
        for mid in semi_final:                       # SF and final are knockout
            self.assertIn(by_match[mid].court_id, ("court-1", "court-5"))

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

    def test_group_stage_uses_short_timed_games(self):
        # The group stage of group_knockout is an ordinary round-robin match, so
        # it is a short single timed game (pool_timing); only the knockout plays
        # full best-of-N. Costing pools as full matches made a 5-pair group stage
        # look like five 40-minute rounds.
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
        br = GK.generate(div, seed_entries(t, div, "ranking"),
                         num_groups=2, main_draw=4)
        t.brackets["gk"] = br
        s = Settings()
        generate_schedule(t, s, ["gk"])
        seen = set()
        for b in t.schedule:
            part = br.matches[b.match_id].bracket_part
            seen.add(part)
            want = s.pool_timing if part == "pool" else s.timing
            self.assertEqual(b.play_min, want.play_min, part)
        self.assertEqual(seen, {"pool", "main"})      # both stages were scheduled

    def test_full_length_pools_when_pool_single_game_is_off(self):
        # Organizers who want best-of-3 group play can turn the flag off.
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
        s = Settings(pool_single_game=False)
        generate_schedule(t, s, ["gk"])
        for b in t.schedule:
            self.assertEqual(b.play_min, s.timing.play_min)

    def test_run_order_schedules_the_first_event_first(self):
        # Two unrelated divisions on one court: whichever the organizer put first
        # in the run order is played first, end to end.
        from tournament.engine import bracket_rr as RR
        t = Tournament()

        def add(div_id, tag, sort_no):
            refs = []
            for i in range(4):
                pid = f"{tag}{i}"
                t.players[pid] = Player(id=pid, first=tag, last=str(i), skill=4 - i)
                refs.append(EntryRef("player", pid))
            div = Division(id=div_id, event="MS", label=div_id, entry_refs=refs,
                           format="round_robin", sort_no=sort_no)
            t.divisions[div_id] = div
            t.brackets[div_id] = RR.generate(div, seed_entries(t, div, "ranking"))

        add("second", "B", 1)
        add("first", "A", 0)
        generate_schedule(t, Settings(court_count=1, schedule_mode="separated"),
                          ["first", "second"])
        div_of = {mid: did for did, br in t.brackets.items() for mid in br.matches}
        first_starts = [b.start_min for b in t.schedule if div_of[b.match_id] == "first"]
        second_starts = [b.start_min for b in t.schedule if div_of[b.match_id] == "second"]
        self.assertTrue(first_starts and second_starts)
        self.assertLess(max(first_starts), min(second_starts))

    def _two_divisions(self):
        from tournament.engine import bracket_rr as RR
        t = Tournament()

        def add(div_id, tag, sort_no):
            refs = []
            for i in range(4):
                pid = f"{tag}{i}"
                t.players[pid] = Player(id=pid, first=tag, last=str(i), skill=4 - i)
                refs.append(EntryRef("player", pid))
            div = Division(id=div_id, event="MS", label=div_id, entry_refs=refs,
                           format="round_robin", sort_no=sort_no)
            t.divisions[div_id] = div
            t.brackets[div_id] = RR.generate(div, seed_entries(t, div, "ranking"))

        add("first", "A", 0)
        add("second", "B", 1)
        return t

    def test_separated_mode_finishes_one_event_before_the_next(self):
        t = self._two_divisions()
        generate_schedule(t, Settings(court_count=4, schedule_mode="separated"),
                          ["first", "second"])
        div_of = {mid: did for did, br in t.brackets.items() for mid in br.matches}
        first_end = max(b.end_min for b in t.schedule if div_of[b.match_id] == "first")
        second_start = min(b.start_min for b in t.schedule
                           if div_of[b.match_id] == "second")
        self.assertGreaterEqual(second_start, first_end)

    def test_integrated_mode_shares_the_courts(self):
        t = self._two_divisions()
        generate_schedule(t, Settings(court_count=4, schedule_mode="integrated"),
                          ["first", "second"])
        div_of = {mid: did for did, br in t.brackets.items() for mid in br.matches}
        first_end = max(b.end_min for b in t.schedule if div_of[b.match_id] == "first")
        second_start = min(b.start_min for b in t.schedule
                           if div_of[b.match_id] == "second")
        self.assertLess(second_start, first_end)      # they overlap

    def test_pool_games_may_use_every_court(self):
        # With 7 courts and only 3 side courts, holding pool play off the center
        # courts left them idle. Pools may use any court again, so a busy round
        # spills onto the center courts instead of queueing for court 1.
        from tournament.engine import bracket_rr as RR
        t = Tournament()
        for k, tag in enumerate(("A", "B", "C")):
            refs = []
            for i in range(4):
                pid = f"{tag}{i}"
                t.players[pid] = Player(id=pid, first=tag, last=str(i), skill=4 - i)
                refs.append(EntryRef("player", pid))
            div = Division(id=tag, event="MS", label=tag, entry_refs=refs,
                           format="round_robin", sort_no=k)
            t.divisions[tag] = div
            t.brackets[tag] = RR.generate(div, seed_entries(t, div, "ranking"))
        generate_schedule(t, Settings(court_count=7), list(t.divisions))
        used = {b.court_id for b in t.schedule}
        self.assertTrue({"court-2", "court-3", "court-6", "court-7"} & used,
                        used)          # a center court took pool play

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

    def test_early_knockout_rounds_use_all_courts(self):
        # 16-draw single elim on 4 courts: the round of 16 may use the outer
        # courts; only QF/SF/final are pinned to the center courts. Regression:
        # every knockout match used to sit on the two center courts, which
        # stretched a 16-draw to 6:25 PM instead of ~5:05 PM.
        t = Tournament()
        single_elim_division(t, "ms", "MS", 16)
        s = Settings(court_count=4)
        blocks = generate_schedule(t, s, ["ms"])
        br = t.brackets["ms"]
        court_of = {b.match_id: int(b.court_id.rsplit("-", 1)[1]) for b in blocks}
        r16 = next(r for r in br.rounds if len(r.match_ids) == 8)
        used = {court_of[mid] for mid in r16.match_ids}
        self.assertTrue(used - set(s.center_courts),
                        f"round of 16 should use outer courts, used {used}")
        qf = next(r for r in br.rounds if len(r.match_ids) == 4)
        for mid in qf.match_ids:
            self.assertIn(court_of[mid], set(s.center_courts))
        # And the round of 16 now fits in two slots, not four.
        self.assertLessEqual(max(b.start_min for b in blocks
                                 if b.match_id in r16.match_ids), 40)

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


class TestSharedCenterCourtRule(unittest.TestCase):
    """The auto-scheduler and the live court board must not drift apart: both
    call the single implementation in ``schedule/courtplan.py``."""

    def test_both_callers_use_the_same_functions(self):
        from tournament.schedule import courtplan, scheduler
        from tournament.server import service
        self.assertIs(scheduler.is_center_court_match,
                      courtplan.is_center_court_match)
        self.assertIs(scheduler.center_court_numbers,
                      courtplan.center_court_numbers)
        self.assertIs(service.is_center_court_match,
                      courtplan.is_center_court_match)
        self.assertIs(service.center_court_numbers,
                      courtplan.center_court_numbers)

    def test_rule_is_dropped_below_two_usable_center_courts(self):
        from tournament.schedule.courtplan import center_court_numbers
        four = Settings(center_courts=(2, 3), court_count=4)
        self.assertEqual(center_court_numbers(four, [1, 2, 3, 4]), [2, 3])
        # Only one of the configured center courts exists at this venue, so
        # reserving it would starve the rest -> the rule is dropped entirely.
        self.assertEqual(center_court_numbers(four, [1, 2]), [])
        self.assertEqual(
            center_court_numbers(Settings(center_courts=(2,), court_count=4),
                                 [1, 2, 3, 4]), [])

    def test_only_finals_stage_knockouts_are_protected(self):
        from tournament.schedule.courtplan import is_center_court_match
        t = Tournament()
        single_elim_division(t, "big", "MD", 16)
        single_elim_division(t, "small", "MD", 8)

        def protected(div_id):
            br = t.brackets[div_id]
            return [m for m in br.matches.values()
                    if is_center_court_match(br, m)]

        # 16 draw: the round of 16 is unrestricted; QF + SF + final are not.
        self.assertEqual((len(t.brackets["big"].matches), len(protected("big"))),
                         (15, 7))
        # 8 draw: its first round already is the quarterfinal.
        self.assertEqual((len(t.brackets["small"].matches),
                          len(protected("small"))), (7, 7))


class TestPlayedMatchesLeaveTheSchedule(unittest.TestCase):
    """A match that has already been played must not be given court time again
    when the schedule is regenerated mid-tournament."""

    def test_played_match_is_not_rescheduled(self):
        from tournament.engine.advancement import record_result
        t = Tournament()
        single_elim_division(t, "d", "MD", 4)
        br = t.brackets["d"]
        settings = Settings(court_count=2, center_courts=())
        before = generate_schedule(t, settings)
        self.assertEqual(len(before), 3)          # two semis + the final
        played = before[0].match_id
        record_result(br, played, [[21, 5], [21, 5]])
        after = generate_schedule(t, settings)
        self.assertNotIn(played, [b.match_id for b in after])
        self.assertEqual(len(after), 2)
