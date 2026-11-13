"""A team draw is an ordinary bracket over team entries; ties decide from their
entry rubbers and the winning team advances."""

import unittest

from tournament.engine import format_registry, tie
from tournament.engine.advancement import champion, record_result
from tournament.engine.seeding import seed_entries
from tournament.model.entities import (
    Division, EntryRef, Pair, Player, Team, TeamFormat, Tournament,
)


def team_xd_tournament(n_teams, pairs_per_team=3):
    """Each team = pairs_per_team XD pairs; team ti is stronger than ti+1."""
    t = Tournament(mode="team")
    refs = []
    for ti in range(n_teams):
        ents = []
        for j in range(pairs_per_team):
            key = f"t{ti}p{j}"
            a, b = key + "a", key + "b"
            skill = 9 - ti                      # team 0 strongest
            t.players[a] = Player(id=a, first=key, last="A", gender="M", skill=skill, events=["XD"])
            t.players[b] = Player(id=b, first=key, last="B", gender="F", skill=skill, events=["XD"])
            t.pairs[key] = Pair(id=key, player_ids=[a, b], event="XD")
            ents.append(EntryRef("pair", key))
        tid = f"team-{ti}"
        t.teams[tid] = Team(id=tid, name=f"Team {ti}", entries=ents,
                            player_ids=[p for e in ents for p in t.pairs[e.ref_id].player_ids])
        refs.append(EntryRef("team", tid))
    div = Division(id="dt", event="XD", label="Team XD", entry_refs=refs,
                   format="single_elim", team_type="mixed",
                   team_format=TeamFormat(events=["XD"]))
    t.divisions["dt"] = div
    seeds = seed_entries(t, div, "ranking")
    br = format_registry.generate("single_elim", div, seeds)
    t.brackets["dt"] = br
    tie.fill_ties_from_draw(t, br)
    return t, div, br, seeds


class TestTeamDraw(unittest.TestCase):
    def test_first_round_ties_get_entry_rubbers(self):
        t, div, br, seeds = team_xd_tournament(4)
        ties = [m for m in br.matches.values() if m.bracket_part != "rubber"
                and m.side1 and m.side2 and m.side1.kind == "team"]
        self.assertTrue(ties)
        for m in ties:
            self.assertEqual(len(m.sub_match_ids), 3)     # 3 XD pairs each
            for rid in m.sub_match_ids:
                r = br.matches[rid]
                self.assertEqual(r.side1.kind, "pair")

    def test_favorites_win_the_title(self):
        t, div, br, seeds = team_xd_tournament(4)
        seed_of = {s.entry.key(): s.seed_no for s in seeds}
        for _ in range(400):
            progressed = False
            for m in list(br.matches.values()):
                if (m.bracket_part == "rubber" and m.result is None
                        and m.side1 and m.side2):
                    parent = br.matches[m.parent_id]
                    s1 = seed_of.get(parent.side1.key(), 999)
                    s2 = seed_of.get(parent.side2.key(), 999)
                    record_result(br, m.id,
                                  [[21, 5], [21, 5]] if s1 < s2 else [[5, 21], [5, 21]])
                    progressed = True
            tie.fill_ties_from_draw(t, br)
            if not progressed:
                break
        self.assertEqual(champion(br), seeds[0].entry)


if __name__ == "__main__":
    unittest.main()
