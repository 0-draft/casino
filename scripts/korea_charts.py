#!/usr/bin/env python3
"""
korea_charts.py

Strategy cards for the tables at Korea's foreigner casinos, drawn as SVG into
guide/korea/. Nothing here is recited from a published chart: every blackjack
cell is priced by bjmath for the venue's rules, and every baccarat edge by
bacmath (plus one enumeration below for the no-commission banker).

The one thing bjmath does not model is the European no-hole-card game (ENHC),
which is what Asian tables usually deal. It does not need to: bjmath already
prices every action conditioned on the dealer not having a natural, which is
exactly the peek game. Without a peek the natural is still possible, so each
action against an ace or a ten is

    (1 - p) * EV(action | no natural) + p * (-stake lost to the natural)

where p is the chance the hole card completes the natural and the stake is one
unit for standing or hitting and two for doubling or splitting (one for both
under OBO, "original bets only"). Decisions after the first card need no such
treatment: once the hand is hit, a dealer natural takes the same stake whatever
the player does next. Resplit stakes are counted as two units, which slightly
flatters resplitting against a ten or an ace; no cell on the chart turns on it.

Run it from the repository root:

    python scripts/korea_charts.py
"""

from __future__ import annotations

import sys
import textwrap
from math import exp, lgamma, log
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import bacmath  # noqa: E402
import bjmath as m  # noqa: E402

OUT = ROOT / "guide" / "korea"
UPS = (2, 3, 4, 5, 6, 7, 8, 9, 10, 1)


# --------------------------------------------------------------------------
# Blackjack
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Table:
    """A blackjack table as the felt and the rule card describe it."""

    slug: str
    title: str
    rules: m.Rules
    hole_card: bool          # False: European no hole card
    obo: bool = False        # ENHC only: a natural takes the original bet only
    # None, "early" (half the bet back whatever the dealer turns up) or "late"
    # (a dealer natural still takes the whole bet).
    surrender: str | None = None
    surrender_vs_ace: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)


ROWS = (
    [("hard", t) for t in range(8, 18)]
    + [("soft", t) for t in range(13, 21)]
    + [("pair", v) for v in (2, 3, 4, 5, 6, 7, 8, 9, 10, 1)]
)


def row_label(kind: str, what: int) -> str:
    if kind == "hard":
        return {8: "≤8", 17: "17+"}.get(what, str(what))
    if kind == "soft":
        return f"A,{what - 11}"
    face = "A" if what == 1 else ("T" if what == 10 else str(what))
    return f"{face},{face}"


def hand_of(kind: str, what: int) -> tuple[int, ...]:
    """Built without a ten wherever it can be, as the repository's chart is."""
    if kind == "pair":
        return (what, what)
    if kind == "soft":
        return (1, what - 11)
    first = min(9, what - 2)
    return (first, what - first)


def shoe_without(cards, up, decks):
    comp = m.fresh(decks)
    for value in list(cards) + [up]:
        comp = m.remove(comp, m.index_of(value))
    return comp


def action_values(table: Table, cards, up) -> dict[str, float]:
    rules = table.rules
    comp = shoe_without(cards, up, rules.decks)
    allowed = table.surrender is not None and (up != 1 or table.surrender_vs_ace)
    # bjmath's surrender is the peek game's: the dealer has already checked.
    rules = rules._replace(late_surrender=True)
    ev = m.action_evs(comp, cards, up, rules, can_surrender=allowed)
    options = ev.options()
    if table.hole_card or up not in (1, 10):
        return options
    partner = m.TEN if up == 1 else m.ACE
    p = comp[partner] / sum(comp)
    big = 1.0 if table.obo else 2.0
    stake = {"stand": 1.0, "hit": 1.0, "double": big, "split": big,
             # Early surrender is half the bet back before the natural can
             # show, so it does not move. Late surrender is lost to it.
             "surrender": None if table.surrender == "early" else 1.0}
    out = {}
    for name, value in options.items():
        if stake[name] is None:
            out[name] = value
        else:
            out[name] = (1 - p) * value + p * -stake[name]
    return out


def decide(table: Table, kind: str, what: int, up: int) -> str:
    options = action_values(table, hand_of(kind, what), up)
    best = max(options.items(), key=lambda kv: kv[1])[0]
    if best == "double":
        return "D" if options["hit"] > options["stand"] else "Ds"
    if best == "surrender":
        return "Rh" if options["hit"] > options["stand"] else "Rs"
    if best == "split" and kind == "pair" and what == 5:
        return "D"
    return {"stand": "S", "hit": "H", "split": "P"}[best]


def bj_chart(table: Table) -> dict[tuple[str, int], list[str]]:
    m.clear_caches()
    return {row: [decide(table, *row, up) for up in UPS] for row in ROWS}


# --------------------------------------------------------------------------
# Baccarat
# --------------------------------------------------------------------------

def banker_six_win(comp: tuple[int, ...]) -> float:
    """P(banker wins with a total of six), for the no-commission banker that
    pays half on it. The same enumeration as bacmath.outcomes, kept to the one
    number it does not return."""
    c = list(comp)
    n = sum(c)
    hit = 0.0

    def add(pt: int, bt: int, w: float) -> None:
        nonlocal hit
        if bt == 6 and bt > pt:
            hit += w

    def thirds(pt: int, bt: int, w: float, left: int) -> None:
        if bacmath.player_draws(pt):
            for p3 in range(10):
                if not c[p3]:
                    continue
                w5 = w * c[p3] / left
                c[p3] -= 1
                pt3 = (pt + p3) % 10
                if bacmath.banker_draws(bt, p3):
                    for b3 in range(10):
                        if c[b3]:
                            add(pt3, (bt + b3) % 10, w5 * c[b3] / (left - 1))
                else:
                    add(pt3, bt, w5)
                c[p3] += 1
        elif bacmath.banker_draws(bt, None):
            for b3 in range(10):
                if c[b3]:
                    add(pt, (bt + b3) % 10, w * c[b3] / left)
        else:
            add(pt, bt, w)

    order = []

    def deal(depth: int, w: float, cards: list[int]) -> None:
        if depth == 4:
            pt = (cards[0] + cards[2]) % 10
            bt = (cards[1] + cards[3]) % 10
            if pt >= 8 or bt >= 8:
                add(pt, bt, w)
            else:
                thirds(pt, bt, w, n - 4)
            return
        for v in range(10):
            if not c[v]:
                continue
            w2 = w * c[v] / (n - depth)
            c[v] -= 1
            cards.append(v)
            deal(depth + 1, w2, cards)
            cards.pop()
            c[v] += 1

    deal(0, 1.0, order)
    return hit


def baccarat_edges(decks: int = 8) -> list[tuple[str, str, float]]:
    rules = bacmath.Rules(decks=decks)
    comp = bacmath.full_comp(rules)
    pw, bw, tw = bacmath.outcomes(comp)
    pair = bacmath.pair_chance(bacmath.full_ranks(rules))
    six = banker_six_win(comp)
    rows = [
        ("Banker", "0.95 : 1", bw * 0.95 - pw),
        ("Player", "1 : 1", pw - bw),
        ("Banker (no commission)", "1 : 1, 6 pays 1 : 2", bw - six * 0.5 - pw),
        ("Tie", "8 : 1", tw * 8 - (1 - tw)),
        ("Player / Banker Pair", "11 : 1", pair * 11 - (1 - pair)),
    ]
    return [(name, pays, -ev) for name, pays, ev in rows]


def ahead_chance(spot: str, hands: int, decks: int = 8) -> float:
    """P(strictly ahead) after `hands` flat bets of one unit on Banker (paying
    0.95) or Player, summed exactly over how many coups were won, lost and
    tied. The coups are taken as independent draws from a full shoe, which is
    what a flat bettor who ignores the shoe is facing on average."""
    pw, bw, tw = bacmath.outcomes(bacmath.full_comp(bacmath.Rules(decks=decks)))
    win, lose, pay = (bw, pw, 0.95) if spot == "banker" else (pw, bw, 1.0)
    total = 0.0
    for w in range(hands + 1):
        for lost in range(hands - w + 1):
            if pay * w - lost <= 1e-9:
                continue
            t = hands - w - lost
            log_p = (lgamma(hands + 1) - lgamma(w + 1) - lgamma(lost + 1) - lgamma(t + 1)
                     + w * log(win) + lost * log(lose) + t * log(tw))
            total += exp(log_p)
    return total


# --------------------------------------------------------------------------
# SVG
# --------------------------------------------------------------------------

COLOURS = {
    "H": ("#f4f1ea", "#2b2b2b"),
    "S": ("#f2c94c", "#2b2b2b"),
    "D": ("#2f9e5b", "#ffffff"),
    "Ds": ("#7cc79a", "#1b3a28"),
    "P": ("#2d6cdf", "#ffffff"),
    "Rh": ("#d64545", "#ffffff"),
    "Rs": ("#e88a8a", "#3a1414"),
}
LEGEND = (
    ("H", "Hit"),
    ("S", "Stand"),
    ("D", "Double (else hit)"),
    ("Ds", "Double (else stand)"),
    ("P", "Split"),
    ("Rh", "Surrender (else hit)"),
    ("Rs", "Surrender (else stand)"),
)
FONT = "font-family=\"Helvetica, Arial, sans-serif\""


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def bj_svg(table: Table, chart) -> str:
    cell, gap, left, top = 34, 2, 64, 96
    width = left + len(UPS) * (cell + gap) + 16
    sections = (("HARD", "hard"), ("SOFT", "soft"), ("PAIRS", "pair"))
    rows_h = sum(len([r for r in ROWS if r[0] == k]) for _, k in sections)
    height = top + rows_h * (cell + gap) + len(sections) * 22 + 40 + 24 * len(table.notes) + 120
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" rx="12" fill="#0f3d2e"/>',
    ]
    y = 32
    for line in textwrap.wrap(table.title, 34, break_on_hyphens=False):
        out.append(f'<text x="16" y="{y}" {FONT} font-size="18" font-weight="700" '
                   f'fill="#ffffff">{esc(line)}</text>')
        y += 24
    y -= 2
    for line in textwrap.wrap(rule_line(table), 62):
        out.append(f'<text x="16" y="{y}" {FONT} font-size="12" fill="#cfe3d8">{esc(line)}</text>')
        y += 17
    top = y + 34
    y = top - 18
    for i, up in enumerate(UPS):
        x = left + i * (cell + gap)
        label = "A" if up == 1 else ("T" if up == 10 else str(up))
        out.append(f'<text x="{x + cell / 2}" y="{y}" {FONT} font-size="14" font-weight="700" '
                   f'fill="#ffffff" text-anchor="middle">{label}</text>')
    out.append(f'<text x="16" y="{y}" {FONT} font-size="11" fill="#cfe3d8">dealer →</text>')
    y = top - 6
    for heading, kind in sections:
        y += 16
        out.append(f'<text x="16" y="{y}" {FONT} font-size="11" font-weight="700" '
                   f'fill="#9fd1b5" letter-spacing="1">{heading}</text>')
        y += 6
        for row in [r for r in ROWS if r[0] == kind]:
            out.append(f'<text x="{left - 10}" y="{y + cell / 2 + 5}" {FONT} font-size="13" '
                       f'font-weight="700" fill="#ffffff" text-anchor="end">'
                       f'{esc(row_label(*row))}</text>')
            for i, code in enumerate(chart[row]):
                x = left + i * (cell + gap)
                bg, fg = COLOURS[code]
                out.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="4" fill="{bg}"/>')
                out.append(f'<text x="{x + cell / 2}" y="{y + cell / 2 + 5}" {FONT} font-size="13" '
                           f'font-weight="700" fill="{fg}" text-anchor="middle">{code}</text>')
            y += cell + gap
    y += 18
    used = {code for codes in chart.values() for code in codes}
    lx = 16
    for code, meaning in LEGEND:
        if code not in used:
            continue
        bg, fg = COLOURS[code]
        w = 26 + 7 * len(meaning)
        if lx + w > width - 8:
            lx, y = 16, y + 24
        out.append(f'<rect x="{lx}" y="{y}" width="20" height="18" rx="3" fill="{bg}"/>')
        out.append(f'<text x="{lx + 10}" y="{y + 13}" {FONT} font-size="10" font-weight="700" '
                   f'fill="{fg}" text-anchor="middle">{code}</text>')
        out.append(f'<text x="{lx + 24}" y="{y + 13}" {FONT} font-size="11" fill="#ffffff">'
                   f'{esc(meaning)}</text>')
        lx += w
    y += 36
    for note in table.notes:
        for line in textwrap.wrap(note, 62):
            out.append(f'<text x="16" y="{y}" {FONT} font-size="11" fill="#cfe3d8">{esc(line)}</text>')
            y += 16
        y += 2
    out.append(f'<text x="16" y="{y + 4}" {FONT} font-size="10" fill="#7fae95">'
               f'Every cell computed by scripts/korea_charts.py (bjmath, exact EV from a full shoe)</text>')
    final = y + 20
    out[0] = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{final}" '
              f'viewBox="0 0 {width} {final}">')
    out[1] = f'<rect width="{width}" height="{final}" rx="12" fill="#0f3d2e"/>'
    out.append("</svg>")
    return "\n".join(out) + "\n"


def rule_line(table: Table) -> str:
    r = table.rules
    parts = [f"{r.decks} decks",
             "dealer hits soft 17" if r.hit_soft_17 else "dealer stands on soft 17",
             "DAS" if r.double_after_split else "no DAS",
             "no hole card" + (" (OBO)" if table.obo else " (all bets lost)") if not table.hole_card
             else "hole card / peek",
             (f"{table.surrender} surrender" + ("" if table.surrender_vs_ace else " (not v A)"))
             if table.surrender else "no surrender",
             "BJ 3:2" if r.blackjack_pays == 1.5 else f"BJ {r.blackjack_pays}:1"]
    return " · ".join(parts)


def bac_svg(decks: int = 8) -> str:
    edges = baccarat_edges(decks)
    width, row_h, top = 520, 40, 96
    height = top + row_h * len(edges) + 170
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" rx="12" fill="#3b0f17"/>',
        f'<text x="16" y="32" {FONT} font-size="20" font-weight="700" fill="#ffffff">'
        f'Baccarat: which spot to bet</text>',
        f'<text x="16" y="54" {FONT} font-size="12" fill="#e8cdd2">'
        f'{decks} decks, punto banco · house edge per unit bet, lower is better</text>',
        f'<text x="16" y="{top - 12}" {FONT} font-size="11" fill="#e8cdd2">BET</text>',
        f'<text x="250" y="{top - 12}" {FONT} font-size="11" fill="#e8cdd2">PAYS</text>',
        f'<text x="{width - 16}" y="{top - 12}" {FONT} font-size="11" fill="#e8cdd2" '
        f'text-anchor="end">HOUSE EDGE</text>',
    ]
    worst = max(e for *_, e in edges)
    for i, (name, pays, edge) in enumerate(edges):
        y = top + i * row_h
        good = edge < 0.0125
        ok = edge < 0.016
        colour = "#3fb871" if good else ("#e0b13c" if ok else "#e05a5a")
        out.append(f'<rect x="8" y="{y}" width="{width - 16}" height="{row_h - 4}" rx="6" '
                   f'fill="#ffffff" fill-opacity="0.06"/>')
        bar = max(4, (width - 250 - 24) * edge / worst)
        out.append(f'<rect x="250" y="{y + row_h - 10}" width="{bar:.1f}" height="4" rx="2" '
                   f'fill="{colour}"/>')
        out.append(f'<text x="18" y="{y + 23}" {FONT} font-size="14" font-weight="700" '
                   f'fill="#ffffff">{esc(name)}</text>')
        out.append(f'<text x="250" y="{y + 20}" {FONT} font-size="12" fill="#e8cdd2">{esc(pays)}</text>')
        out.append(f'<text x="{width - 18}" y="{y + 23}" {FONT} font-size="14" font-weight="700" '
                   f'fill="{colour}" text-anchor="end">{edge * 100:.2f}%</text>')
    y = top + row_h * len(edges) + 22
    lines = (
        "Commission table (banker pays 0.95): bet Banker.",
        "No-commission table (banker 6 pays half): bet Player.",
        "Tie and pairs are 10% to 15%. Lucky 6 / Super 6 are worse.",
        "Roadmaps and streaks predict nothing: every coup is a fresh draw.",
        "A tie pushes Banker and Player bets: the stake comes back.",
    )
    for line in lines:
        out.append(f'<text x="16" y="{y}" {FONT} font-size="12" fill="#ffffff">{esc(line)}</text>')
        y += 22
    out.append(f'<text x="16" y="{y + 6}" {FONT} font-size="10" fill="#b98a93">'
               f'Every edge computed by scripts/korea_charts.py (bacmath, exact from a full shoe)</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------
# The venues
# --------------------------------------------------------------------------

H17_6D = m.Rules(decks=6, hit_soft_17=True, double_after_split=True)

TABLES = (
    Table(
        slug="paradise-city",
        title="Blackjack: Paradise City (Incheon)",
        # Re-split up to two times, so three hands (the official game guide).
        rules=H17_6D._replace(max_splits=2),
        hole_card=False,
        surrender="early",
        notes=(
            "No hole card and no OBO: a dealer blackjack takes doubles and splits too.",
            "Never take insurance or even money.",
        ),
    ),
    Table(
        slug="inspire-no-hole-card",
        title="Blackjack: INSPIRE (Incheon), no-hole-card tables",
        rules=H17_6D,
        hole_card=False,
        surrender="late",
        notes=(
            "Assumes a dealer blackjack takes doubles and splits too (OBO unconfirmed).",
            "Never take insurance or even money.",
        ),
    ),
    Table(
        slug="inspire-hole-card",
        title="Blackjack: INSPIRE (Incheon), hole-card tables",
        rules=H17_6D,
        hole_card=True,
        surrender="late",
        notes=(
            "The dealer peeks: a blackjack is turned over before you act.",
            "Never take insurance or even money.",
        ),
    ),
)


def without_surrender(table: Table, chart) -> list[str]:
    """What the surrender cells become where the table will not take one."""
    plain = Table(table.slug, table.title, table.rules, table.hole_card, table.obo)
    out = []
    for row, codes in chart.items():
        for up, code in zip(UPS, codes):
            if code.startswith("R"):
                fallback = decide(plain, *row, up)
                face = "A" if up == 1 else ("T" if up == 10 else str(up))
                out.append(f"{row_label(*row)} v {face}: {fallback}")
    return out


def write(slugs=None) -> list[Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    written = []
    for table in TABLES:
        if slugs and table.slug not in slugs:
            continue
        chart = bj_chart(table)
        fallback = without_surrender(table, chart)
        if fallback:
            table = Table(table.slug, table.title, table.rules, table.hole_card, table.obo,
                          table.surrender, table.surrender_vs_ace,
                          table.notes + ("No surrender at your table? " + ", ".join(fallback) + ".",))
        path = OUT / f"bj-{table.slug}.svg"
        path.write_text(bj_svg(table, chart), encoding="utf-8")
        written.append(path)
        print(path.relative_to(ROOT), flush=True)
    if not slugs or "baccarat" in slugs:
        path = OUT / "baccarat.svg"
        path.write_text(bac_svg(8), encoding="utf-8")
        written.append(path)
        print(path.relative_to(ROOT), flush=True)
    return written


def print_ahead_table() -> None:
    """The table in guide/korea/README.md: python scripts/korea_charts.py ahead"""
    for n in (1, 10, 100, 300, 1000):
        print(f"| {n} | {ahead_chance('player', n) * 100:.1f}% | {ahead_chance('banker', n) * 100:.1f}% |")


if __name__ == "__main__":
    args = set(sys.argv[1:])
    if args == {"ahead"}:
        print_ahead_table()
    else:
        write(args or None)
