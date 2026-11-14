"""M1: data model round-trip + atomic store + audit log."""

import os
import tempfile
import unittest

from tournament.model.entities import (
    Bracket, Division, EntryRef, Match, Override, Pair, Player, Pool,
    Result, Round, ScheduleBlock, Seed, Tournament,
)
from tournament.model.ids import IdFactory, slugify
from tournament.store.repository import Repository


def sample_tournament() -> Tournament:
    t = Tournament(name="Test Cup", date="2026-03-21")
    t.players["player-a"] = Player(
        id="player-a", first="Nicholas", last="Chin", email="a@x.com",
        gender="M", skill=8, events=["MS", "MD"], willing_random=True,
        weekend_avail=["Feb 6-7"], source_row=2,
    )
    t.players["player-b"] = Player(
        id="player-b", first="Sunny", last="You", gender="F",
        skill=None, events=["WD"], is_stub=True,
    )
    t.pairs["pair-1"] = Pair(id="pair-1", player_ids=["player-a", "player-b"],
                             event="XD", origin="requested")
    div = Division(id="div-xd", event="XD", label="Mixed Doubles",
                   entry_refs=[EntryRef("pair", "pair-1")], format="group_knockout")
    t.divisions[div.id] = div
    m = Match(id="m1", division_id="div-xd", round_name="Final",
              side1=EntryRef("player", "player-a"),
              side2=EntryRef("player", "player-b"),
              result=Result(games=[[21, 15], [19, 21], [21, 17]],
                            winner=EntryRef("player", "player-a")),
              next_win_slot=2, seq=3)
    br = Bracket(division_id="div-xd", format="group_knockout",
                 matches={"m1": m}, rounds=[Round(name="Final", match_ids=["m1"])],
                 pools=[Pool(id="pool-a", label="A",
                             entry_refs=[EntryRef("pair", "pair-1")], advance_count=2)],
                 seeds=[Seed(entry=EntryRef("pair", "pair-1"), seed_no=1)],
                 version=2, rng_seed=12345, finalized=True)
    t.brackets["div-xd"] = br
    t.schedule.append(ScheduleBlock(match_id="m1", court_id="c1", start_min=0,
                                    warmup_min=5, play_min=30, buffer_min=5))
    return t


class TestSlugAndIds(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(slugify("Nicholas  Chin"), "nicholas-chin")
        self.assertEqual(slugify("En-Chi Angel"), "en-chi-angel")
        self.assertEqual(slugify("   "), "x")

    def test_id_uniqueness(self):
        f = IdFactory()
        a = f.make("player", "Sunny", "You")
        b = f.make("player", "Sunny", "You")
        self.assertEqual(a, "player-sunny-you")
        self.assertEqual(b, "player-sunny-you-2")
        self.assertNotEqual(a, b)

    def test_reserve(self):
        f = IdFactory()
        f.reserve("player-sunny-you")
        self.assertEqual(f.make("player", "Sunny", "You"), "player-sunny-you-2")


class TestRoundTrip(unittest.TestCase):
    def test_save_and_load_preserves_graph(self):
        t = sample_tournament()
        with tempfile.TemporaryDirectory() as d:
            repo = Repository(os.path.join(d, "tournament.json"))
            repo.save(t)
            self.assertTrue(repo.exists())
            loaded = repo.load()

        self.assertEqual(loaded.name, "Test Cup")
        self.assertEqual(loaded.players["player-a"].skill, 8)
        self.assertEqual(loaded.players["player-a"].events, ["MS", "MD"])
        self.assertIsNone(loaded.players["player-b"].skill)
        self.assertTrue(loaded.players["player-b"].is_stub)
        # Pair modeled as two player ids, not a string.
        self.assertEqual(loaded.pairs["pair-1"].player_ids, ["player-a", "player-b"])
        # Nested Match/Result/EntryRef survive.
        m = loaded.brackets["div-xd"].matches["m1"]
        self.assertEqual(m.result.games, [[21, 15], [19, 21], [21, 17]])
        self.assertEqual(m.result.games_won(), (2, 1))
        self.assertEqual(m.result.winner.ref_id, "player-a")
        self.assertEqual(m.side1.kind, "player")
        self.assertEqual(m.next_win_slot, 2)
        # Bracket flags.
        br = loaded.brackets["div-xd"]
        self.assertTrue(br.finalized)
        self.assertEqual(br.version, 2)
        self.assertEqual(br.rng_seed, 12345)
        self.assertEqual(br.pools[0].advance_count, 2)
        self.assertEqual(loaded.schedule[0].end_min, 40)

    def test_division_markers_and_seed_choice_survive_a_round_trip(self):
        t = sample_tournament()
        t.divisions["div-xd"].custom = True
        t.divisions["div-xd"].seed_method = "random"
        t.divisions["div-xd"].seed_no = 11
        with tempfile.TemporaryDirectory() as d:
            repo = Repository(os.path.join(d, "tournament.json"))
            repo.save(t)
            loaded = repo.load()
        div = loaded.divisions["div-xd"]
        self.assertTrue(div.custom)
        self.assertEqual((div.seed_method, div.seed_no), ("random", 11))
        # An older document without the new keys still loads with the defaults.
        self.assertFalse(loaded.divisions["div-xd"].team_type is not None)

    def test_old_document_loads_with_default_markers(self):
        import json
        t = sample_tournament()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "old.json")
            from tournament.model.codec import to_jsonable
            payload = to_jsonable(t)
            for div in payload["divisions"].values():
                for key in ("custom", "seed_method", "seed_no"):
                    div.pop(key, None)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
            loaded = Repository(path).load()
        div = loaded.divisions["div-xd"]
        self.assertFalse(div.custom)
        self.assertEqual(div.seed_method, "ranking")
        self.assertIsNone(div.seed_no)

    def test_missing_file_returns_empty_tournament(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Repository(os.path.join(d, "nope.json"))
            t = repo.load()
            self.assertEqual(t.players, {})

    def test_atomic_save_leaves_no_tmp(self):
        t = sample_tournament()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "tournament.json")
            repo = Repository(path)
            repo.save(t)
            repo.save(t, backup=True)
            self.assertFalse(os.path.exists(path + ".tmp"))
            self.assertTrue(os.path.exists(path + ".bak"))
            self.assertTrue(repo.restore_backup())

    def test_entry_label(self):
        t = sample_tournament()
        self.assertEqual(t.entry_label(EntryRef("player", "player-a")), "Nicholas Chin")
        self.assertEqual(t.entry_label(EntryRef("pair", "pair-1")),
                         "Nicholas Chin / Sunny You")


class TestAudit(unittest.TestCase):
    def test_append_only_audit(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Repository(os.path.join(d, "tournament.json"))
            repo.append_audit(Override(ts="2026-03-01T10:00:00", actor="me@x.com",
                                       target="player:player-b", field_name="skill",
                                       old_value="", new_value="7", reason="from email"))
            repo.append_audit(Override(ts="2026-03-01T10:05:00", actor="me@x.com",
                                       target="player:player-b", field_name="gender",
                                       old_value="U", new_value="F"))
            rows = repo.read_audit()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["new_value"], "7")
            self.assertEqual(rows[1]["field_name"], "gender")


if __name__ == "__main__":
    unittest.main()
