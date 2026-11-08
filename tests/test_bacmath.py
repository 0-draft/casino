#!/usr/bin/env python3
"""
Tests for the odds.

The numbers in every issue comment come from bacmath.outcomes(), so it is held
to the figures every reference publishes for a full eight-deck shoe, and to a
Monte Carlo of the same dealing code the game uses on a shoe that is far from
full. The tableau is checked cell by cell against the printed one.
"""

import pathlib
import random
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import bacmath  # noqa: E402

# The banker's tableau as casinos print it: banker total -> the player's third
# card values on which the banker draws.
TABLEAU = {
    0: set(range(10)),
    1: set(range(10)),
    2: set(range(10)),
    3: set(range(10)) - {8},
    4: {2, 3, 4, 5, 6, 7},
    5: {4, 5, 6, 7},
    6: {6, 7},
    7: set(),
}


class Tableau(unittest.TestCase):
    def test_banker_against_the_printed_table(self):
        for total, draws_on in TABLEAU.items():
            for third in range(10):
                with self.subTest(banker=total, third=third):
                    self.assertEqual(bacmath.banker_draws(total, third), third in draws_on)

    def test_banker_without_a_player_third_card(self):
        for total in range(8):
            self.assertEqual(bacmath.banker_draws(total, None), total <= 5)

    def test_player(self):
        for total in range(8):
            self.assertEqual(bacmath.player_draws(total), total <= 5)

    def test_naturals_stop_the_coup(self):
        cards = iter([4, 0, 4, 2, 9, 9])
        player, banker = bacmath.deal(lambda: next(cards), lambda v: v)
        self.assertEqual((player, banker), ([4, 4], [0, 2]))

    def test_player_draws_and_banker_reads_the_third_card(self):
        # Player 0+3=3 draws an 8; banker on 3 stands against an 8.
        cards = iter([0, 1, 3, 2, 8, 9])
        player, banker = bacmath.deal(lambda: next(cards), lambda v: v)
        self.assertEqual((player, banker), ([0, 3, 8], [1, 2]))


class FullShoe(unittest.TestCase):
    """The eight-deck figures, as published to six places by every reference
    on the game (Wizard of Odds, among others)."""

    def setUp(self):
        self.p, self.b, self.t = bacmath.outcomes(bacmath.full_comp())

    def test_probabilities(self):
        self.assertAlmostEqual(self.b, 0.458597, places=6)
        self.assertAlmostEqual(self.p, 0.446247, places=6)
        self.assertAlmostEqual(self.t, 0.095156, places=6)
        self.assertAlmostEqual(self.p + self.b + self.t, 1.0, places=9)

    def test_house_edges(self):
        ev = bacmath.evs(bacmath.full_comp(), bacmath.full_ranks())
        self.assertAlmostEqual(ev["banker"], -0.010579, places=6)
        self.assertAlmostEqual(ev["player"], -0.012351, places=6)
        self.assertAlmostEqual(ev["tie"], -0.143596, places=6)
        self.assertAlmostEqual(ev["ppair"], -0.103614, places=6)
        self.assertEqual(ev["ppair"], ev["bpair"])


class DepletedShoe(unittest.TestCase):
    def test_exact_sum_agrees_with_dealing(self):
        """A shoe stripped of most of its small cards, where the odds are far
        from the full-shoe ones, priced exactly and then dealt."""
        comp = (40, 3, 3, 3, 12, 12, 12, 12, 12, 12)
        exact = bacmath.outcomes(comp)
        pool = [v for v, n in enumerate(comp) for _ in range(n)]
        rng = random.Random(7)
        trials = 60_000
        seen = {"player": 0, "banker": 0, "tie": 0}
        for _ in range(trials):
            cards = rng.sample(pool, 6)
            it = iter(cards)
            player, banker = bacmath.deal(lambda: next(it), lambda v: v)
            seen[bacmath.winner(bacmath.point(player), bacmath.point(banker))] += 1
        for name, prob in zip(("player", "banker", "tie"), exact):
            # Four standard errors at 60k trials is under 0.009.
            self.assertAlmostEqual(seen[name] / trials, prob, delta=0.009, msg=name)

    def test_too_few_cards(self):
        with self.assertRaises(ValueError):
            bacmath.outcomes((1, 1, 1, 0, 0, 0, 0, 0, 0, 0))

    def test_pairs_by_rank(self):
        # Two queens and two kings: four zero-value cards, but a pair only
        # within a rank.
        ranks = (0,) * 11 + (2, 2)
        self.assertAlmostEqual(bacmath.pair_chance(ranks), (2 + 2) / 12)


if __name__ == "__main__":
    unittest.main()
