"""Entry-based team building: intact entries, pairs kept together, no player
dropped, per-event balance, and a gaps report."""

import unittest

from tournament.engine import team_build
from tournament.model.entities import Pair, Player, Tournament


def add_pair(t, key, ev, ga, gb, skill):
    a, b = f"{key}a", f"{key}b"
    t.players[a] = Player(id=a, first=key + "A", last="X", gender=ga, skill=skill, events=[ev])
    t.players[b] = Player(id=b, first=key + "B", last="Y", gender=gb, skill=skill, events=[ev])
    t.pairs[key] = Pair(id=key, player_ids=[a, b], event=ev)


def add_single(t, pid, ev, g, skill, club=""):
    t.players[pid] = Player(id=pid, first=pid, last="S", gender=g, skill=skill,
                            events=[ev], club=club)


def xd_pairs(n):
    t = Tournament(mode="team")
    for i in range(n):
        add_pair(t, f"xd{i}", "XD", "M", "F", 9 - (i % 8))
    return t


class TestTeamBuild(unittest.TestCase):
    def test_single_event_splits_pairs_across_teams(self):
        t = xd_pairs(22)
        teams, report = team_build.build_teams(t, "balanced", num_teams=4,
                                               events=["XD"], rng_seed=1)
        self.assertEqual(len(teams), 4)
        total = sum(len(tm.entries) for tm in teams)
        self.assertEqual(total, 22)                       # every pair placed
        for tm in teams:
            self.assertTrue(4 <= len(tm.entries) <= 6)    # ~even
        # grid shows XD counts per team
        self.assertTrue(all("XD" in g["by_event"] for g in report["grid"]))

    def test_no_player_dropped_and_pairs_intact(self):
        t = xd_pairs(10)
        teams, _ = team_build.build_teams(t, "balanced", num_teams=3,
                                          events=["XD"], rng_seed=2)
        # Every entry is a pair kept intact; all players rostered exactly once.
        rostered = [pid for tm in teams for pid in tm.player_ids]
        self.assertEqual(sorted(rostered), sorted(t.players))
        for tm in teams:
            for e in tm.entries:
                self.assertEqual(e.kind, "pair")

    def test_players_multiple_entries_stay_together(self):
        # A player in an XD pair who also entered MS -> both entries same team.
        t = Tournament(mode="team")
        for i in range(6):
            add_pair(t, f"xd{i}", "XD", "M", "F", 6)
        # make xd0a also an MS singles entry
        t.players["xd0a"].events = ["XD", "MS"]
        for i in range(4):
            add_single(t, f"ms{i}", "MS", "M", 6)
        teams, _ = team_build.build_teams(t, "balanced", num_teams=2,
                                          events=["MS", "XD"], rng_seed=1)
        home = {}
        for tm in teams:
            for e in tm.entries:
                for pid in team_build.entry_players(t, e):
                    home.setdefault(pid, tm.id)
        # xd0a's XD-pair team and MS-single team are the same team.
        xd_team = next(tm.id for tm in teams if any(
            e.kind == "pair" and "xd0a" in team_build.entry_players(t, e) for e in tm.entries))
        ms_team = next(tm.id for tm in teams if any(
            e.kind == "player" and e.ref_id == "xd0a" for e in tm.entries))
        self.assertEqual(xd_team, ms_team)

    def test_event_balance_and_gaps(self):
        # 5 XD + 3 MD across 2 teams -> grid + a gaps entry where uneven.
        t = Tournament(mode="team")
        for i in range(5):
            add_pair(t, f"xd{i}", "XD", "M", "F", 6)
        for i in range(3):
            add_pair(t, f"md{i}", "MD", "M", "M", 6)
        teams, report = team_build.build_teams(t, "balanced", num_teams=2,
                                               events=["XD", "MD"], rng_seed=1)
        self.assertEqual(len(report["grid"]), 2)
        # MD is odd across 2 teams -> flagged as a gap.
        self.assertTrue(any(g["event"] == "MD" for g in report["gaps"]))
        self.assertTrue(report["warnings"])

    def test_balanced_actually_balances_rating(self):
        # 24 XD pairs of varied skill into 4 teams -> average team strength close.
        t = Tournament(mode="team")
        skills = [1, 9, 2, 8, 3, 7, 4, 6, 5, 5, 9, 1, 8, 2, 7, 3, 6, 4, 5, 5, 9, 2, 8, 3]
        for i, s in enumerate(skills):
            a, b = f"m{i}", f"w{i}"
            t.players[a] = Player(id=a, first=f"M{i}", last="X", gender="M", skill=s, events=["XD"])
            t.players[b] = Player(id=b, first=f"W{i}", last="Y", gender="F", skill=s, events=["XD"])
            t.pairs[f"p{i}"] = Pair(id=f"p{i}", player_ids=[a, b], event="XD")
        from tournament.engine.seeding import entry_strength
        teams, _ = team_build.build_teams(t, "balanced", num_teams=4, events=["XD"])
        avgs = [sum(entry_strength(t, e) for e in tm.entries) / len(tm.entries)
                for tm in teams]
        self.assertLess(max(avgs) - min(avgs), 1.0)   # tightly balanced

    def test_snake_and_balanced_differ(self):
        t = xd_pairs(20)
        b = team_build.build_teams(t, "balanced", num_teams=4, events=["XD"])[0]
        s = team_build.build_teams(t, "snake", num_teams=4, events=["XD"])[0]
        self.assertNotEqual([tm.player_ids for tm in b], [tm.player_ids for tm in s])

    def test_single_event_splits_in_half(self):
        # 6 XD pairs into 2 teams -> 3 and 3 (even per event), for every method.
        t = xd_pairs(6)
        for method in ("balanced", "snake", "random"):
            teams, _ = team_build.build_teams(t, method, num_teams=2,
                                              events=["XD"], rng_seed=1)
            self.assertEqual(sorted(len(tm.entries) for tm in teams), [3, 3],
                             f"{method} didn't split evenly")

    def test_each_event_split_evenly(self):
        # 8 XD + 6 MD across 2 teams -> 4/4 XD and 3/3 MD.
        t = Tournament(mode="team")
        for i in range(8):
            add_pair(t, f"xd{i}", "XD", "M", "F", (i % 5) + 3)
        for i in range(6):
            add_pair(t, f"md{i}", "MD", "M", "M", (i % 5) + 3)
        teams, _ = team_build.build_teams(t, "balanced", num_teams=2,
                                          events=["XD", "MD"], rng_seed=1)
        counts = [team_build.team_event_counts(t, tm) for tm in teams]
        self.assertEqual(sorted(c["XD"] for c in counts), [4, 4])
        self.assertEqual(sorted(c["MD"] for c in counts), [3, 3])

    def test_colors_assigned(self):
        t = xd_pairs(8)
        teams, _ = team_build.build_teams(t, "balanced", num_teams=4, events=["XD"])
        self.assertTrue(all(tm.color for tm in teams))
        self.assertEqual(len({tm.color for tm in teams}), 4)   # distinct

    def test_deterministic(self):
        t = xd_pairs(12)
        a = team_build.build_teams(t, "random", num_teams=4, events=["XD"], rng_seed=7)[0]
        b = team_build.build_teams(t, "random", num_teams=4, events=["XD"], rng_seed=7)[0]
        self.assertEqual([tm.player_ids for tm in a], [tm.player_ids for tm in b])

    def test_by_club(self):
        t = Tournament(mode="team")
        for i in range(4):
            add_single(t, f"a{i}", "MS", "M", 6, club="Red")
            add_single(t, f"b{i}", "MS", "M", 6, club="Blue")
        teams, _ = team_build.build_teams(t, "by_club", events=["MS"])
        self.assertEqual({tm.name for tm in teams}, {"Red", "Blue"})


if __name__ == "__main__":
    unittest.main()
