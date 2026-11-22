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
        # 14 v T surrenders only when the half bet is safe from the natural,
        # as Wizard of Odds' ENHC 6D H17 EV table has it.
        self.assertEqual(k.decide(ENHC_EARLY, "hard", 14, 10), "Rh")
        self.assertEqual(k.decide(ENHC_LATE, "hard", 14, 10), "H")

    def test_seven_seven_against_a_ten_turns_on_it_too(self):
        early = k.Table("early", "early", H17._replace(max_splits=2), hole_card=False,
                        surrender="early")
        late = k.Table("late", "late", H17._replace(max_splits=2), hole_card=False,
                       surrender="late")
        self.assertEqual(k.decide(early, "pair", 7, 10), "Rh")
        self.assertEqual(k.decide(late, "pair", 7, 10), "H")

    def test_the_cells_the_guide_says_change_at_s17(self):
        s17 = k.Table("s17", "s17", H17._replace(hit_soft_17=False), hole_card=True,
                      surrender="late")
        for kind, what, up, h17, stand17 in (("soft", 18, 2, "Ds", "S"),
                                            ("soft", 19, 6, "Ds", "S"),
                                            ("hard", 11, 1, "D", "H")):
            with self.subTest(hand=(kind, what), up=up):
                self.assertEqual(k.decide(PEEK, kind, what, up), h17)
                self.assertEqual(k.decide(s17, kind, what, up), stand17)



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

    def test_the_guide_table_of_finishing_ahead(self):
        # guide/korea/README.md quotes these.
        self.assertAlmostEqual(k.ahead_chance("player", 1), 0.4462, places=4)
        self.assertAlmostEqual(k.ahead_chance("banker", 1), 0.4586, places=4)
        self.assertAlmostEqual(k.ahead_chance("player", 10), 0.412, places=3)
        self.assertAlmostEqual(k.ahead_chance("banker", 100), 0.447, places=3)


if __name__ == "__main__":
    unittest.main()
