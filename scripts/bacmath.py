#!/usr/bin/env python3
"""
bacmath.py

The arithmetic of punto banco, and nothing else: the drawing rules, and the
exact odds of every bet on the layout from whatever cards are left in the shoe.

Nobody makes a decision once the cards are out, so a coup is a pure function of
the order they come out in. That makes the odds a finite sum rather than an
estimate: every way the next four to six cards can come out, weighted by how
likely the shoe makes it. bacmath.outcomes() is that sum, and on a full
eight-deck shoe it reproduces the published figures to the last digit they are
published to (tests/test_bacmath.py).

Cards are counted in two ways. The coup only cares about point values, so the
main bets are priced from ten buckets (tens and faces are all zero). A pair is
two cards of the same rank, so a queen and a king are not one, and the pair bets
are priced from thirteen.
"""

from dataclasses import dataclass

VALUES = 10


@dataclass(frozen=True)
class Rules:
    decks: int = 8
    # The shoe is shuffled once fewer than this many cards are left. A coup
    # takes six at most, so a hand can never run the shoe dry.
    cut: int = 16
    banker_pays: float = 0.95
    tie_pays: float = 8.0
    pair_pays: float = 11.0

    @property
    def cards(self) -> int:
        return 52 * self.decks


PUNTO_BANCO = Rules()

SPOTS = ("player", "banker", "tie", "ppair", "bpair")


def point(values) -> int:
    return sum(values) % 10


def player_draws(player_total: int) -> bool:
    """The player draws on 0 to 5 and stands on 6 or 7. Naturals are caught
    before this is asked."""
    return player_total <= 5


def banker_draws(banker_total: int, third: int | None) -> bool:
    """The banker's half of the tableau.

    `third` is the point value of the player's third card, or None when the
    player stood. With no third card to read, the banker plays like the player.
    """
    if third is None:
        return banker_total <= 5
    if banker_total <= 2:
        return True
    if banker_total == 3:
        return third != 8
    if banker_total == 4:
        return 2 <= third <= 7
    if banker_total == 5:
        return 4 <= third <= 7
    if banker_total == 6:
        return third in (6, 7)
    return False


def deal(draw, value) -> tuple[list, list]:
    """Deal one coup and return the player's cards and the banker's.

    `draw` returns the next card and `value` maps a card to its point value, so
    the game deals real cards through here and the tests deal bare numbers.
    The cards come out player, banker, player, banker, then whatever third
    cards the tableau calls for.
    """
    p1, b1, p2, b2 = draw(), draw(), draw(), draw()
    player, banker = [p1, p2], [b1, b2]
    pt = point(value(c) for c in player)
    bt = point(value(c) for c in banker)
    if pt >= 8 or bt >= 8:
        return player, banker
    third = None
    if player_draws(pt):
        player.append(draw())
        third = value(player[-1])
    if banker_draws(bt, third):
        banker.append(draw())
    return player, banker


def winner(player_total: int, banker_total: int) -> str:
    if player_total > banker_total:
        return "player"
    if banker_total > player_total:
        return "banker"
    return "tie"


def outcomes(comp: tuple[int, ...]) -> tuple[float, float, float]:
    """P(player wins), P(banker wins), P(tie), exactly, for a shoe holding
    comp[v] cards of point value v.

    The cards come out player, banker, player, banker, then the third cards.
    Drawing without replacement, every branch takes its card out of `c` before
    going deeper and puts it back after, so one list serves the whole sum.
    """
    c = list(comp)
    n = sum(c)
    if n < 6:
        raise ValueError("a coup needs six cards in the shoe")
    pw = bw = tw = 0.0

    def third_cards(pt: int, bt: int, w: float, m: int) -> None:
        nonlocal pw, bw, tw
        if player_draws(pt):
            for p3 in range(VALUES):
                if not c[p3]:
                    continue
                w5 = w * c[p3] / m
                c[p3] -= 1
                pt3 = (pt + p3) % 10
                if banker_draws(bt, p3):
                    m2 = m - 1
                    for b3 in range(VALUES):
                        if c[b3]:
                            add(pt3, (bt + b3) % 10, w5 * c[b3] / m2)
                else:
                    add(pt3, bt, w5)
                c[p3] += 1
        elif banker_draws(bt, None):
            for b3 in range(VALUES):
                if c[b3]:
                    add(pt, (bt + b3) % 10, w * c[b3] / m)
        else:
            add(pt, bt, w)

    def add(pt: int, bt: int, w: float) -> None:
        nonlocal pw, bw, tw
        if pt > bt:
            pw += w
        elif bt > pt:
            bw += w
        else:
            tw += w

    for p1 in range(VALUES):
        if not c[p1]:
            continue
        w1 = c[p1] / n
        c[p1] -= 1
        for b1 in range(VALUES):
            if not c[b1]:
                continue
            w2 = w1 * c[b1] / (n - 1)
            c[b1] -= 1
            for p2 in range(VALUES):
                if not c[p2]:
                    continue
                w3 = w2 * c[p2] / (n - 2)
                c[p2] -= 1
                pt = (p1 + p2) % 10
                for b2 in range(VALUES):
                    if not c[b2]:
                        continue
                    w4 = w3 * c[b2] / (n - 3)
                    c[b2] -= 1
                    bt = (b1 + b2) % 10
                    if pt >= 8 or bt >= 8:
                        add(pt, bt, w4)
                    else:
                        third_cards(pt, bt, w4, n - 4)
                    c[b2] += 1
                c[p2] += 1
            c[b1] += 1
        c[p1] += 1
    return pw, bw, tw


def pair_chance(ranks: tuple[int, ...]) -> float:
    """The chance a side's first two cards share a rank.

    The player's two cards are the first and third out, but every card is as
    likely as any other to be in any position, so this is the chance that any
    two cards drawn from the shoe pair up. Same for the banker.
    """
    n = sum(ranks)
    if n < 2:
        return 0.0
    return sum(r * (r - 1) for r in ranks) / (n * (n - 1))


def evs(comp: tuple[int, ...], ranks: tuple[int, ...],
        rules: Rules = PUNTO_BANCO) -> dict[str, float]:
    """What one unit on each spot is worth, before the coup."""
    pw, bw, tw = outcomes(comp)
    pair = pair_chance(ranks)
    return {
        # A tie pushes the player and banker bets: their stakes come back.
        "player": pw - bw,
        "banker": bw * rules.banker_pays - pw,
        "tie": tw * rules.tie_pays - (1 - tw),
        "ppair": pair * rules.pair_pays - (1 - pair),
        "bpair": pair * rules.pair_pays - (1 - pair),
    }


def full_comp(rules: Rules = PUNTO_BANCO) -> tuple[int, ...]:
    """A fresh shoe by point value: sixteen zeros a deck (the ten and three
    faces of four suits), four of everything else."""
    return tuple(16 * rules.decks if v == 0 else 4 * rules.decks for v in range(VALUES))


def full_ranks(rules: Rules = PUNTO_BANCO) -> tuple[int, ...]:
    return (4 * rules.decks,) * 13
