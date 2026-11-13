"""M10: format registry — implemented formats present, stubs fail clearly."""

import unittest

from tournament.engine import format_registry as FR
from tournament.engine.seeding import seed_entries
from tournament.model.entities import Division, EntryRef, Player, Tournament


class TestRegistry(unittest.TestCase):
    def test_implemented_formats_registered(self):
        for f in ("single_elim", "double_elim", "round_robin", "group_knockout"):
            self.assertIn(f, FR.available_formats())

    def test_stub_formats_raise_clearly(self):
        t = Tournament()
        refs = []
        for i in range(4):
            t.players[f"p{i}"] = Player(id=f"p{i}", first=f"P{i}", last=str(i), skill=5)
            refs.append(EntryRef("player", f"p{i}"))
        div = Division(id="d", event="MS", label="MS", entry_refs=refs)
        seeds = seed_entries(t, div, "ranking")
        for f in ("swiss", "consolation", "compass"):
            with self.assertRaises(NotImplementedError):
                FR.generate(f, div, seeds)

    def test_unknown_format(self):
        t = Tournament()
        div = Division(id="d", event="MS", label="MS")
        with self.assertRaises(ValueError):
            FR.generate("nope", div, [])


if __name__ == "__main__":
    unittest.main()
