#!/usr/bin/env python3
"""
Tests for the table.

Nobody deals a hand here on purpose: the first sign of a broken renderer is a
broken image on the page or an Action that fails on someone else's click. These
stack the shoe and cover the settlement of every spot, the refusal of stale
links, what reaches the page from a login, and that every image the renderer
can name exists.
"""

import contextlib
import io
import json
import pathlib
import random
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import baccarat as bac  # noqa: E402

CARDS = ROOT / ".github" / "cards"


@contextlib.contextmanager
def stacked(*cards: str):
    """Deal these cards, in this order, instead of whatever the shoe would."""
    queue = list(cards)

    def deal(state):
        card = queue.pop(0)
        state["shoe"]["seen"].append(card)
        return card

    with mock.patch.object(bac, "draw", deal):
        yield


@contextlib.contextmanager
def scratch():
    """Point the log and state files somewhere disposable."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        with mock.patch.object(bac, "LOG_PATH", tmp / "log.txt"), \
                mock.patch.object(bac, "STATE_PATH", tmp / "state.json"):
            yield tmp


def play(state, spot, bet, *cards, user="someone"):
    with stacked(*cards), scratch():
        return bac.play(state, spot, bet, state["hand"], user)


# Player 9 (4 5) against banker 7 (K 7): a natural, no third cards.
PLAYER_WINS = ("4S", "KH", "5D", "7C")
# Player 6 (Q 6) against banker natural 8 (3 5).
BANKER_WINS = ("QS", "3H", "6D", "5C")
# Player 7 (7 K) against banker 7 (2 5): both stand, a tie.
TIE = ("7S", "2H", "KD", "5C")
# Player pair of eights (6, stands) against banker pair of kings (0), who
# draws the nine: banker 9 wins.
PAIRS = ("8S", "KH", "8D", "KC", "9S")


class Settlement(unittest.TestCase):
    def test_every_spot_on_every_result(self):
        cases = [
            ("player", PLAYER_WINS, 5), ("player", BANKER_WINS, -5), ("player", TIE, 0),
            ("banker", BANKER_WINS, 4.75), ("banker", PLAYER_WINS, -5), ("banker", TIE, 0),
            ("tie", TIE, 40), ("tie", PLAYER_WINS, -5),
            ("ppair", PAIRS, 55), ("ppair", TIE, -5),
            ("bpair", PAIRS, 55), ("bpair", PLAYER_WINS, -5),
        ]
        for spot, cards, net in cases:
            with self.subTest(spot=spot, cards=cards):
                state = bac.blank_state()
                play(state, spot, 5, *cards)
                self.assertAlmostEqual(state["recent"][0]["net"], net)
                self.assertAlmostEqual(state["result"], net)

    def test_third_cards_come_out_by_the_tableau(self):
        # Player 0+2=2 draws; banker on 4 draws against a 5.
        state = bac.blank_state()
        play(state, "banker", 1, "TS", "AH", "2D", "3C", "5S", "4H")
        entry = state["recent"][0]
        self.assertEqual(entry["player"], ["TS", "2D", "5S"])
        self.assertEqual(entry["banker"], ["AH", "3C", "4H"])
        self.assertEqual(entry["outcome"], "banker")  # 7 against 8

    def test_road_and_hand_number(self):
        state = bac.blank_state()
        play(state, "tie", 1, *PAIRS)
        self.assertEqual(state["shoe"]["road"], ["Bpb"])
        self.assertEqual(state["hand"], 2)

    def test_a_stale_link_is_refused(self):
        state = bac.blank_state()
        state["hand"] = 9
        with scratch():
            message = bac.play(state, "banker", 5, 8, "someone")
        self.assertIn("Someone got there first", message)
        self.assertEqual(state["shoe"]["seen"], [])
        self.assertEqual(state["hand"], 9)

    def test_cut_card(self):
        state = bac.blank_state()
        shoe = bac.full_shoe(bac.RULES.decks)
        random.Random(1).shuffle(shoe)
        # Eighteen left: the coup can start, and takes the shoe past the cut.
        state["shoe"]["seen"] = shoe[:bac.RULES.cards - 18]
        message = play(state, "banker", 1, *BANKER_WINS)
        self.assertIn("fresh shoe", message)
        self.assertEqual(state["shoe"]["seen"], [])
        self.assertEqual(state["shoe"]["number"], 2)

    def test_coach_charges_only_for_worse_bets(self):
        state = bac.blank_state()
        play(state, "banker", 5, *BANKER_WINS, user="a")
        self.assertAlmostEqual(state["coach"]["cost"], 0.0)
        play(state, "tie", 5, *TIE, user="b")
        self.assertGreater(state["players"]["b"]["cost"], 0.6)


class Parsing(unittest.TestCase):
    def test_titles(self):
        self.assertEqual(bac.parse("bac|bet banker 5 12"), ("banker", 5.0, 12))
        self.assertEqual(bac.parse("bac|bet ppair 25 123456789"), ("ppair", 25.0, 123456789))
        # Exactly what the gate job in the workflow lets through, nothing more.
        for bad in ("bac|bet banker 3 12", "bac|bet house 5 12", "bj|bet banker 5 1",
                    "bac|bet banker 5", "", "bac | bet ppair 25 1", "BAC|bet banker 5 1",
                    "bac|bet banker 5 1;id", "bac|bet banker 5 1234567890",
                    "x bac|bet banker 5 1"):
            self.assertIsNone(bac.parse(bad), bad)

    def test_logins(self):
        self.assertEqual(bac.handle("kanywst"), "kanywst")
        for bad in ("<script>", "a--b", "-a", "a" * 40, None, 3):
            self.assertEqual(bac.handle(bad), "", bad)


class Page(unittest.TestCase):
    def rendered(self):
        state = bac.blank_state()
        for cards in (PLAYER_WINS, BANKER_WINS, TIE, PAIRS):
            play(state, "banker", 5, *cards, user="kanywst")
        return state, bac.render(state)

    def test_every_image_exists(self):
        _, page = self.rendered()
        for page_ in (page, bac.render(bac.blank_state())):
            for name in re.findall(r"/cards/([^\"]+)\.svg", page_):
                self.assertTrue((CARDS / f"{name}.svg").exists(), name)

    def test_chips_link_to_this_hand(self):
        state, page = self.rendered()
        links = re.findall(r"title=bac%7Cbet\+(\w+)\+(\d+)\+(\d+)", page)
        self.assertEqual(len(links), len(bac.SPOTS) * len(bac.CHIPS))
        for spot, chip, number in links:
            self.assertEqual(bac.parse(f"bac|bet {spot} {chip} {number}"),
                             (spot, float(chip), state["hand"]))

    def test_an_edited_login_never_reaches_the_page(self):
        state, _ = self.rendered()
        state["recent"][0]["by"] = '"><script>'
        self.assertNotIn("<script>", bac.render(state))

    def test_bead_plate_shape(self):
        state, page = self.rendered()
        plate = page.split("<pre>")[3].split("</pre>")[0]
        rows = plate.split("\n")
        self.assertEqual(len(rows), bac.BEAD_ROWS)
        for row in rows:
            self.assertEqual(row.count("<img"), bac.BEAD_COLS)

    def test_state_round_trips(self):
        state, _ = self.rendered()
        with scratch():
            bac.save_state(state)
            self.assertEqual(bac.load_state(), json.loads(json.dumps(state)))

    def test_broken_state_falls_back(self):
        with scratch() as tmp:
            (tmp / "state.json").write_text('{"shoe": {"seen": ["ZZ"]}, "hand": -1}')
            self.assertEqual(bac.load_state(), bac.blank_state())


def shoe_with(left: int) -> list[str]:
    """A shuffled shoe with `left` cards still in it."""
    shoe = bac.full_shoe(bac.RULES.decks)
    random.Random(left).shuffle(shoe)
    return shoe[:bac.RULES.cards - left]


class CutCard(unittest.TestCase):
    def test_sixteen_left_after_the_coup_keeps_the_shoe(self):
        state = bac.blank_state()
        state["shoe"]["seen"] = shoe_with(20)
        play(state, "banker", 1, *BANKER_WINS)
        self.assertEqual(state["shoe"]["number"], 1)
        self.assertEqual(bac.cards_left(state), 16)

    def test_fifteen_left_after_the_coup_shuffles(self):
        state = bac.blank_state()
        state["shoe"]["seen"] = shoe_with(19)
        message = play(state, "banker", 1, *BANKER_WINS)
        self.assertEqual(state["shoe"]["number"], 2)
        self.assertEqual((state["shoe"]["seen"], state["shoe"]["road"]), ([], []))
        self.assertIn("fresh shoe", message)


class Coach(unittest.TestCase):
    def pair_heavy(self):
        """A shoe so thick with one rank that a pair is the best bet there is."""
        state = bac.blank_state()
        left = ["7S"] * 8 + ["7H"] * 8 + ["7D"] * 8 + ["7C"] * 8 + ["2S", "3H", "4D", "9C"]
        everything = bac.full_shoe(bac.RULES.decks)
        for card in left:
            everything.remove(card)
        state["shoe"]["seen"] = everything
        return state

    def test_both_pairs_are_named_when_they_lead(self):
        for spot in ("ppair", "bpair"):
            with self.subTest(spot):
                table, cost = bac.coach(self.pair_heavy(), spot, 5)
                self.assertEqual(cost, 0.0)
                self.assertIn("That was the best bet", table)
                self.assertIn("Player Pair and Banker Pair had the edge", table)
                self.assertEqual(table.count("  best"), 2)

    def test_a_worse_bet_names_what_was_better(self):
        table, cost = bac.coach(self.pair_heavy(), "player", 5)
        self.assertGreater(cost, 0)
        self.assertIn("Player Pair and Banker Pair were worth more", table)

    def test_the_numbers_line_up(self):
        table, _ = bac.coach(bac.blank_state(), "banker", 5)
        rows = [r for r in table.split("\n") if r.endswith(("%", "best", "you"))]
        self.assertEqual(len({r.index("%") for r in rows}), 1, rows)


class Log(unittest.TestCase):
    def test_old_shoes_go_whole(self):
        with scratch(), mock.patch.object(bac, "MAX_LOG_SHOES", 2):
            state = bac.blank_state()
            for shoe in range(1, 5):
                for hand in range(3):
                    with stacked(*BANKER_WINS):
                        bac.play(state, "banker", 1, state["hand"], f"p{shoe}")
                state["shoe"]["seen"] += shoe_with(10)[len(state["shoe"]["seen"]):]
                bac.reshuffle(state)
            text = bac.LOG_PATH.read_text()
        self.assertTrue(text.startswith(bac.header()))
        self.assertNotIn("@p1", text)
        self.assertNotIn("@p2", text)
        self.assertNotIn("shoe 2", text)
        # Each kept shoe is its hands, then its summary, then its marker.
        for shoe in (3, 4):
            hands = text.index(f"@p{shoe}")
            summary = text.index(f"  shoe {shoe} closed")
            marker = text.index(f"  end of shoe {shoe}")
            self.assertLess(hands, summary)
            self.assertLess(summary, marker)
        self.assertLess(text.index("end of shoe 3"), text.index("@p4"))

    def test_the_road_wraps_between_codes(self):
        with scratch():
            state = bac.blank_state()
            state["shoe"]["road"] = ["P"] * 47 + ["Bpb", "T"] * 30
            state["shoe"]["seen"] = shoe_with(15)
            bac.reshuffle(state)
            text = bac.LOG_PATH.read_text()
        road = text.split("  road\n")[1].split("  end of shoe")[0]
        for line in road.splitlines():
            self.assertLessEqual(len(line), 100)
            self.assertFalse(line.endswith(" "))
            for code in line.split():
                self.assertRegex(code, r"^[PBT]p?b?$")


class BadState(unittest.TestCase):
    """Whatever the state file holds, a click still deals and the page still
    draws. A table that throws stays broken until somebody edits JSON."""

    def good(self):
        state = bac.blank_state()
        for cards in (PLAYER_WINS, PAIRS):
            play(state, "banker", 5, *cards, user="kanywst")
        return state

    def damaged(self):
        def recent(**kw):
            def hit(s):
                s["recent"][0].update(kw)
            return hit

        def without(key):
            def hit(s):
                del s["recent"][0][key]
            return hit

        def seen(cards):
            def hit(s):
                s["shoe"]["seen"] = cards
            return hit

        yield "outcome missing", without("outcome")
        yield "outcome unknown", recent(outcome="draw")
        yield "pairs a list", recent(pairs=[True, False])
        yield "pairs not bool", recent(pairs={"player": 1, "banker": 0})
        yield "bet not a chip", recent(bet=7)
        yield "four cards", recent(player=["2S", "3S", "4S", "5S"])
        yield "by not a string", recent(by=["x"])
        yield "coach cost a string", lambda s: s["coach"].update(cost="x")
        yield "coach bets a bool", lambda s: s["coach"].update(bets=True)
        yield "player record an int", lambda s: s["players"].update(kanywst=1)
        yield "player record short", lambda s: s["players"].update(kanywst={"hands": 1})
        yield "player name not a login", lambda s: s["players"].update({"<b>": s["players"]["kanywst"]})
        yield "shoe past the cut", seen(shoe_with(10))
        yield "nine of one card", seen(["AS"] * 9)
        yield "hand a bool", lambda s: s.update(hand=True)
        yield "hand too long to parse", lambda s: s.update(hand=10 ** 9)
        yield "result NaN", lambda s: s.update(result=float("nan"))

    def test_every_damage_still_plays_and_draws(self):
        for label, hit in self.damaged():
            with self.subTest(label), scratch():
                state = self.good()
                hit(state)
                bac.STATE_PATH.write_text(json.dumps(state))
                loaded = bac.load_state()
                bac.render(loaded)
                with stacked(*BANKER_WINS):
                    bac.play(loaded, "banker", 1, loaded["hand"], "kanywst")
                bac.render(loaded)
                self.assertTrue(all(bac.handle(n) for n in loaded["players"]))

    def test_one_bad_player_keeps_the_rest(self):
        with scratch():
            state = self.good()
            state["players"]["other"] = "broken"
            bac.STATE_PATH.write_text(json.dumps(state))
            self.assertEqual(set(bac.load_state()["players"]), {"kanywst"})

    def test_huge_number_literal(self):
        with scratch():
            bac.STATE_PATH.write_text('{"result": ' + "9" * 5000 + "}")
            self.assertEqual(bac.load_state(), bac.blank_state())


class Main(unittest.TestCase):
    def test_a_refused_bet_writes_nothing(self):
        with scratch() as tmp, mock.patch.object(bac, "README_PATH", tmp / "README.md"), \
                mock.patch.dict("os.environ", {"ISSUE_TITLE": "bac|bet banker 5 99",
                                               "ISSUE_USER": "kanywst"}), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            bac.main()
            self.assertFalse((tmp / "state.json").exists())
            self.assertFalse((tmp / "README.md").exists())
        self.assertIn("Someone got there first", out.getvalue())


class Table(unittest.TestCase):
    def test_a_tie_frames_neither_side(self):
        state = bac.blank_state()
        play(state, "tie", 1, *TIE)
        page = bac.render(state)
        self.assertNotIn("-won.svg", page)

    def test_the_winner_is_framed(self):
        state = bac.blank_state()
        play(state, "banker", 1, *BANKER_WINS)
        page = bac.render(state)
        self.assertIn("seat-banker-won.svg", page)
        self.assertNotIn("seat-player-won.svg", page)

    def test_three_card_eight_is_not_a_natural(self):
        state = bac.blank_state()
        # Player 0+2 draws a 6 for 8; banker 3+3=6 draws on a 6, takes a K.
        play(state, "player", 1, "TS", "3H", "2D", "3C", "6S", "KH")
        sentence = bac.describe(state["recent"][0])
        self.assertIn("Player 8 (T 2 6)", sentence)
        self.assertNotIn("natural", sentence)

    def test_bead_plate_fills_down_then_across(self):
        state = bac.blank_state()
        state["shoe"]["road"] = ["P", "B", "B", "T", "P", "B", "Tpb"]
        plate = bac.bead_plate(state)
        first = plate.split("<pre>")[1].split("\n")[0]
        cells = re.findall(r"bead-(\w+)\.svg", first)
        self.assertEqual(cells[:3], ["P", "Tpb", "empty"])

    def test_the_longest_shoe_fits(self):
        state = bac.blank_state()
        state["shoe"]["road"] = ["B"] * 101
        plate = bac.bead_plate(state)
        self.assertEqual(plate.count("bead-B.svg"), 101)


if __name__ == "__main__":
    unittest.main()
