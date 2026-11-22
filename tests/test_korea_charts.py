"""
The Korea strategy cards in guide/korea/ are drawn by scripts/korea_charts.py.

The full charts take minutes, so this checks the parts that make them more than
bjmath with a different title: the no-hole-card adjustment, the surrender
modes, and the baccarat edges, each on cells that are quick to price.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import bjmath as m  # noqa: E402
import korea_charts as k  # noqa: E402

H17 = m.Rules(decks=6, hit_soft_17=True)
PEEK = k.Table("peek", "peek", H17, hole_card=True, surrender="late")
ENHC = k.Table("enhc", "enhc", H17, hole_card=False)
ENHC_EARLY = k.Table("early", "early", H17, hole_card=False, surrender="early")
ENHC_LATE = k.Table("late", "late", H17, hole_card=False, surrender="late")


class NoHoleCard(unittest.TestCase):

    def test_eleven_against_a_ten_is_a_hit_without_the_peek(self):
        # Doubling puts two units in front of a natural nobody has ruled out.
        self.assertEqual(k.decide(PEEK, "hard", 11, 10), "D")
        self.assertEqual(k.decide(ENHC, "hard", 11, 10), "H")

    def test_obo_puts_the_double_back(self):
        obo = k.Table("obo", "obo", H17, hole_card=False, obo=True)
        self.assertEqual(k.decide(obo, "hard", 11, 10), "D")

    def test_small_upcards_do_not_care(self):
        for up in (2, 6, 9):
            with self.subTest(up=up):
                self.assertEqual(k.decide(PEEK, "hard", 11, up), k.decide(ENHC, "hard", 11, up))

    def test_the_adjustment_is_the_natural_weighted_in(self):
        cards, up = (9, 7), 10
        comp = k.shoe_without(cards, up, 6)
        peek = m.action_evs(comp, cards, up, H17, can_surrender=False).options()
        enhc = k.action_values(ENHC, cards, up)
        p = comp[m.ACE] / sum(comp)
        self.assertAlmostEqual(enhc["stand"], (1 - p) * peek["stand"] - p, places=12)

    def test_no_surrender_against_an_ace(self):
        self.assertNotIn("surrender", k.action_values(PEEK, (9, 7), 1))
        self.assertNotIn("surrender", k.action_values(ENHC_EARLY, (9, 7), 1))

    def test_early_surrender_keeps_half_and_late_does_not(self):
        early = k.action_values(ENHC_EARLY, (9, 7), 10)["surrender"]
        late = k.action_values(ENHC_LATE, (9, 7), 10)["surrender"]
        self.assertEqual(early, -0.5)
        self.assertLess(late, -0.5)

    def test_fourteen_against_a_ten_turns_on_the_surrender_kind(self):
        # The research's Wizard-derived chart: 14 v T surrenders only when the
        # half bet is safe from the natural.
        self.assertEqual(k.decide(ENHC_EARLY, "hard", 14, 10), "Rh")
        self.assertEqual(k.decide(ENHC_LATE, "hard", 14, 10), "H")


class Baccarat(unittest.TestCase):

    def test_the_edges_are_the_published_ones(self):
        edges = {(name, pays): edge for name, pays, edge in k.baccarat_edges(8)}
        want = {
            ("Banker", "0.95 : 1"): 0.010579,
            ("Player", "1 : 1"): 0.012351,
            ("Banker (no commission)", "1 : 1, 6 pays 1 : 2"): 0.014581,
            ("Tie", "8 : 1"): 0.143596,
            ("Player / Banker Pair", "11 : 1"): 0.103614,
        }
        for key, value in want.items():
            with self.subTest(bet=key):
                self.assertAlmostEqual(edges[key], value, places=6)


if __name__ == "__main__":
    unittest.main()
