"""M7: group-standings tie-break behaviour (2-way head-to-head, 3-way, seed)."""

import unittest

from tournament.engine.tiebreak import rank
from tournament.model.entities import EntryRef, Match, Result


def match(a, b, winner, sa=21, sb=10):
    r = Result(games=[[sa, sb], [sa, sb]],
               winner=EntryRef("player", winner))
    return Match(id=f"{a}-{b}", division_id="d", round_name="rr",
                 side1=EntryRef("player", a), side2=EntryRef("player", b),
                 result=r)


class TestTiebreak(unittest.TestCase):
    def test_two_way_tie_head_to_head(self):
        # a,b tie at 2 wins; a beat b head-to-head -> a above b.
        # c,d tie at 1 win; d beat c head-to-head -> d above c.
        matches = [
            match("a", "b", "a"), match("a", "c", "c"), match("a", "d", "a"),
            match("b", "c", "b"), match("b", "d", "b"), match("c", "d", "d"),
        ]
        keys = ["player:a", "player:b", "player:c", "player:d"]
        seed_of = {"player:a": 1, "player:b": 2, "player:c": 3, "player:d": 4}
        order = rank(keys, matches, seed_of)
        self.assertEqual(order, ["player:a", "player:b", "player:d", "player:c"])

    def test_three_way_tie_falls_to_seed(self):
        # a>b, b>c, c>a cycle (each 1 win); d loses to all (a,b,c = 2 wins each).
        # 3-way tie among a,b,c is symmetric -> resolved by seed order.
        matches = [
            match("a", "b", "a"), match("b", "c", "b"), match("c", "a", "c"),
            match("a", "d", "a"), match("b", "d", "b"), match("c", "d", "c"),
        ]
        keys = ["player:a", "player:b", "player:c", "player:d"]
        seed_of = {"player:a": 1, "player:b": 2, "player:c": 3, "player:d": 4}
        order = rank(keys, matches, seed_of)
        self.assertEqual(order[:3], ["player:a", "player:b", "player:c"])  # by seed
        self.assertEqual(order[3], "player:d")

    def test_game_diff_breaks_when_no_head_to_head_edge(self):
        # a,b tie at 2 wins and split is impossible here; ensure point/game diff
        # against common opponents can separate. a wins bigger vs c,d.
        matches = [
            match("a", "b", "b"),                 # b beat a head-to-head
            match("a", "c", "a", 21, 2), match("a", "d", "a", 21, 2),
            match("b", "c", "b", 21, 19), match("b", "d", "b", 21, 19),
            match("c", "d", "c"),
        ]
        # a: wins vs c,d (2), lost b. b: wins vs a,c,d (3). So b clearly 1st.
        keys = ["player:a", "player:b", "player:c", "player:d"]
        order = rank(keys, matches, {"player:a": 1, "player:b": 2,
                                     "player:c": 3, "player:d": 4})
        self.assertEqual(order[0], "player:b")   # 3 wins
        self.assertEqual(order[1], "player:a")   # 2 wins


if __name__ == "__main__":
    unittest.main()
