"""Scheduling an entry-based team draw: rubbers (not ties) are scheduled;
sequential + concurrent; no player double-booked."""

import unittest

from tournament.config import Settings
from tournament.engine import format_registry, tie
from tournament.engine.seeding import seed_entries
from tournament.model.entities import (
    Division, EntryRef, Pair, Player, Team, TeamFormat, Tournament,
)
from tournament.schedule.scheduler import generate_schedule, player_conflicts


def team_xd(n_teams=4, pairs_per_team=3, play_mode="sequential"):
    t = Tournament(mode="team")
    refs = []
    for ti in range(n_teams):
        ents = []
        for j in range(pairs_per_team):
            key = f"t{ti}p{j}"
            a, b = key + "a", key + "b"
            t.players[a] = Player(id=a, first=key, last="A", gender="M", skill=9 - ti, events=["XD"])
            t.players[b] = Player(id=b, first=key, last="B", gender="F", skill=9 - ti, events=["XD"])
            t.pairs[key] = Pair(id=key, player_ids=[a, b], event="XD")
            ents.append(EntryRef("pair", key))
        tid = f"team-{ti}"
        t.teams[tid] = Team(id=tid, name=f"Team {ti}", entries=ents,
                            player_ids=[p for e in ents for p in t.pairs[e.ref_id].player_ids])
        refs.append(EntryRef("team", tid))
    div = Division(id="dt", event="XD", label="Team", entry_refs=refs,
                   format="single_elim", team_type="mixed",
                   team_format=TeamFormat(events=["XD"], play_mode=play_mode))
    t.divisions["dt"] = div
    br = format_registry.generate("single_elim", div, seed_entries(t, div, "ranking"))
    t.brackets["dt"] = br
    tie.fill_ties_from_draw(t, br)
    return t, br


class TestTeamSchedule(unittest.TestCase):
    def test_schedules_rubbers_not_ties(self):
        t, br = team_xd(4)
        blocks = generate_schedule(t, Settings(court_count=8), ["dt"])
        self.assertTrue(blocks)
        for b in blocks:
            self.assertEqual(br.matches[b.match_id].bracket_part, "rubber")

    def test_no_double_booking(self):
        t, br = team_xd(4)
        generate_schedule(t, Settings(court_count=8), ["dt"])
        self.assertEqual(player_conflicts(t), [])

    def test_concurrent_tie_rubbers_share_start(self):
        t, br = team_xd(4, play_mode="concurrent")
        blocks = generate_schedule(t, Settings(court_count=8), ["dt"])
        by_tie = {}
        for b in blocks:
            by_tie.setdefault(br.matches[b.match_id].parent_id, []).append(b)
        found = False
        for bs in by_tie.values():
            if len(bs) > 1:
                found = True
                self.assertEqual(len({b.start_min for b in bs}), 1)
                self.assertEqual(len({b.court_id for b in bs}), len(bs))
        self.assertTrue(found)

    def test_sequential_staggers_on_one_court(self):
        t, br = team_xd(2, play_mode="sequential")
        blocks = generate_schedule(t, Settings(court_count=1), ["dt"])
        self.assertGreater(len({b.start_min for b in blocks}), 1)


if __name__ == "__main__":
    unittest.main()
