#!/usr/bin/env python3
"""
baccarat.py

Called from GitHub Actions. Reads an issue title as one bet, deals the coup,
settles it, and redraws the BACCARAT block in README.md.

Open an issue -> Action -> rewrite between the markers -> close the issue.

Punto banco leaves nothing to decide once the chip is down: the cards come out
and the tableau plays them. So the whole game is the bet, and one click is one
coup. The shoe is eight decks dealt down to a cut card and every card that has
come out of it is listed under the table, which is what makes the bet worth
thinking about: the odds of every spot move with what is left, and now and then
a side bet tips over to the player's side.

Every bet is priced before the deal, exactly, from the cards actually left in
the shoe (scripts/bacmath.py), and the issue comes back with what each spot was
worth and what the one taken gave up against the best of them. Those are added
up per player, which is the only scoreboard here that is not all variance.

Issue titles:
  bac|bet banker 5 217  - five units on the banker, for hand 217
  bac|bet player 1 217
  bac|bet tie 2 217
  bac|bet ppair 1 217   - the player's first two cards pair
  bac|bet bpair 1 217   - the banker's first two cards pair

The number is the hand the link was drawn for. A link drawn before someone else
clicked is refused rather than played against a shoe the clicker never saw.

Environment:
  ISSUE_TITLE / ISSUE_USER

Standard output becomes the comment on the issue.
"""

import json
import math
import os
import pathlib
import re
import secrets
import textwrap
from collections import Counter
from datetime import datetime, timezone

import bacmath

README_PATH = pathlib.Path("README.md")
STATE_PATH = pathlib.Path(".github/baccarat.json")
LOG_PATH = pathlib.Path(".github/baccarat-log.txt")

START_MARKER = "<!-- BACCARAT:START -->"
END_MARKER = "<!-- BACCARAT:END -->"

REPO = "0-draft/casino"
ASSET = f"https://raw.githubusercontent.com/{REPO}/main/.github/cards"
BODY = "Just+click+Submit+new+issue.+The+table+updates+in+about+30+seconds."

RULES = bacmath.PUNTO_BANCO

RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K"]
SUITS = ["S", "H", "D", "C"]
SUIT_NAME = {"S": "spades", "H": "hearts", "D": "diamonds", "C": "clubs"}
RANK_NAME = {"A": "ace", "T": "ten", "J": "jack", "Q": "queen", "K": "king",
             "2": "two", "3": "three", "4": "four", "5": "five", "6": "six",
             "7": "seven", "8": "eight", "9": "nine"}

CHIPS = [1, 2, 5, 10, 25]
SPOTS = bacmath.SPOTS
SPOT_NAME = {"player": "Player", "banker": "Banker", "tie": "Tie",
             "ppair": "Player Pair", "bpair": "Banker Pair"}

MAX_RECENT = 3         # Hands listed under the table. The rest are in the log.
MAX_LOG_SHOES = 40     # The oldest shoes fall off the log first.
MAX_PLAYERS = 200
MAX_NAME = 16          # Characters of one login before the table elides it.
BEAD_ROWS = 6          # A bead plate is six cells deep, filled down then across.
BEAD_COLS = 17         # Columns shown: enough for the longest shoe, 101 coups.
TRAY = 24              # Cards of the discard tray printed under the table.

RNG = secrets.SystemRandom()


# --------------------------------------------------------------------------
# Cards
#
# A card is two characters, rank then suit: "TH", "AS". The coup only reads
# point values; the pair bets read ranks; the table draws the suit.
# --------------------------------------------------------------------------

def rank_of(card: str) -> str:
    return card[0]


def value_of(card: str) -> int:
    rank = rank_of(card)
    if rank == "A":
        return 1
    return 0 if rank in ("T", "J", "Q", "K") else int(rank)


def total(cards) -> int:
    return bacmath.point(value_of(c) for c in cards)


def is_natural(cards) -> bool:
    return len(cards) == 2 and total(cards) >= 8


def is_pair(cards) -> bool:
    return len(cards) >= 2 and rank_of(cards[0]) == rank_of(cards[1])


def ranks_of(cards) -> str:
    """K 9. Suits are left off: nothing in the game depends on them."""
    return " ".join(rank_of(c) for c in cards)


def name_of(card: str) -> str:
    return f"{RANK_NAME[rank_of(card)]} of {SUIT_NAME[card[1]]}"


def full_shoe(decks: int) -> list[str]:
    return [rank + suit for rank in RANKS for suit in SUITS for _ in range(decks)]


# --------------------------------------------------------------------------
# The shoe
#
# Stored as the cards that have come out of it, in order, and nothing else.
# What is left is the difference, so the state file cannot disagree with the
# discard tray printed under the table. Nothing in a coup is face down, so
# unlike a blackjack hole card there is nothing here to keep out of a public
# file.
# --------------------------------------------------------------------------

def remaining(state: dict) -> dict[str, int]:
    left: dict[str, int] = {}
    for card in full_shoe(RULES.decks):
        left[card] = left.get(card, 0) + 1
    for card in state["shoe"]["seen"]:
        if left.get(card, 0):
            left[card] -= 1
    return left


def composition(state: dict) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """What is left, by point value and by rank."""
    comp = [0] * bacmath.VALUES
    ranks = [0] * len(RANKS)
    for card, count in remaining(state).items():
        comp[value_of(card)] += count
        ranks[RANKS.index(rank_of(card))] += count
    return tuple(comp), tuple(ranks)


def cards_left(state: dict) -> int:
    return RULES.cards - len(state["shoe"]["seen"])


def draw(state: dict) -> str:
    """Take a card, every one left in the shoe equally likely."""
    pool = [card for card, count in sorted(remaining(state).items()) for _ in range(count)]
    card = RNG.choice(pool)
    state["shoe"]["seen"].append(card)
    return card


def reshuffle(state: dict) -> None:
    """The cut card. The shoe is only shuffled between coups."""
    if cards_left(state) >= RULES.cut:
        return
    log_shoe(state)
    state["shoe"] = {"seen": [], "number": state["shoe"]["number"] + 1, "road": []}


# --------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------

def blank_state() -> dict:
    return {
        "shoe": {"seen": [], "number": 1, "road": []},
        "hand": 1,
        "result": 0.0,
        "hands_played": 0,
        "coach": {"cost": 0.0, "bets": 0},
        "players": {},
        "recent": [],
    }


ROAD = re.compile(r"[PBT]p?b?")


def load_state() -> dict:
    """Fill whatever cannot be read with defaults, so a broken state file does
    not stop the table for good."""
    fresh = blank_state()
    if not STATE_PATH.exists():
        return fresh
    try:
        stored = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError):  # JSONDecodeError is a ValueError
        return fresh
    if not isinstance(stored, dict):
        return fresh

    known = set(full_shoe(1))

    def shoe_ok(value) -> bool:
        if not (isinstance(value, dict) and isinstance(value.get("seen"), list)):
            return False
        seen = value["seen"]
        if not all(isinstance(c, str) and c in known for c in seen):
            return False
        # A saved shoe always has a coup left in it, and no card can have come
        # out more times than there are decks: past either, remaining() and
        # cards_left() would disagree and the pricing would have no shoe.
        return (len(seen) <= RULES.cards - RULES.cut
                and max(Counter(seen).values(), default=0) <= RULES.decks
                and whole(value.get("number")) and value["number"] > 0
                and isinstance(value.get("road"), list)
                and all(isinstance(r, str) and ROAD.fullmatch(r) for r in value["road"]))

    def cards_ok(value) -> bool:
        return (isinstance(value, list) and 2 <= len(value) <= 3
                and all(isinstance(c, str) and c in known for c in value))

    def entry_ok(value) -> bool:
        pairs = value.get("pairs") if isinstance(value, dict) else None
        return (isinstance(value, dict)
                and cards_ok(value.get("player")) and cards_ok(value.get("banker"))
                and value.get("spot") in SPOTS
                and value.get("outcome") in ("player", "banker", "tie")
                and isinstance(pairs, dict)
                and all(isinstance(pairs.get(k), bool) for k in ("player", "banker"))
                and whole(value.get("number"))
                and value.get("bet") in CHIPS
                and number(value.get("net"))
                and isinstance(value.get("by", ""), str))

    def player_ok(value) -> bool:
        return (isinstance(value, dict) and whole(value.get("hands"))
                and all(number(value.get(k)) for k in ("wagered", "net", "cost")))

    checks = {
        "shoe": shoe_ok,
        # Nine digits is all parse() reads off a title.
        "hand": lambda v: whole(v) and 0 < v < 10 ** 9,
        "result": number,
        "hands_played": lambda v: whole(v) and v >= 0,
        "coach": lambda v: (isinstance(v, dict) and number(v.get("cost"))
                            and whole(v.get("bets"))),
        "recent": lambda v: isinstance(v, list) and all(entry_ok(e) for e in v),
    }
    for key, ok in checks.items():
        if key in stored:
            try:
                if ok(stored[key]):
                    fresh[key] = stored[key]
            except (TypeError, AttributeError, ValueError):
                pass
    # One bad record is dropped rather than the whole scoreboard with it.
    if isinstance(stored.get("players"), dict):
        fresh["players"] = {name: stat for name, stat in stored["players"].items()
                            if handle(name) and player_ok(stat)}
    return fresh


def whole(value) -> bool:
    """An int, and not a bool, which JSON would otherwise let through as one."""
    return isinstance(value, int) and not isinstance(value, bool)


def number(value) -> bool:
    """A finite int or float. Python's json reads NaN and Infinity happily."""
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def save_state(state: dict) -> None:
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, STATE_PATH)


# --------------------------------------------------------------------------
# Players
# --------------------------------------------------------------------------

def handle(user) -> str:
    """A GitHub login, or nothing at all.

    The name goes onto the page as a link, so only what a login can actually be
    gets written there: letters, digits and single hyphens, 39 characters at
    most. Anything else is a name the table declines to print.
    """
    if not isinstance(user, str) or len(user) > 39:
        return ""
    if re.fullmatch(r"[A-Za-z0-9](?:-?[A-Za-z0-9])*", user):
        return user
    return ""


def player(state: dict, user: str) -> dict:
    """The record kept for one player, made if it is not there. The state file
    is public and the table is played by whoever turns up, so it is capped; the
    player in front of the table is never the one dropped."""
    who = state["players"].setdefault(
        user, {"hands": 0, "wagered": 0.0, "net": 0.0, "cost": 0.0})
    if len(state["players"]) > MAX_PLAYERS:
        ranked = sorted(((name, stat) for name, stat in state["players"].items()
                         if name != user), key=lambda kv: -kv[1].get("hands", 0))
        state["players"] = dict(ranked[:MAX_PLAYERS - 1] + [(user, who)])
    return who


# --------------------------------------------------------------------------
# Money
# --------------------------------------------------------------------------

def bare(amount: float, signed: bool = False) -> str:
    amount = round(amount, 2)
    sign = "+" if signed and amount > 0 else ("-" if amount < 0 else "")
    body = f"{abs(amount):,.2f}".rstrip("0").rstrip(".")
    return f"{sign}{body}"


def money(amount: float, signed: bool = False) -> str:
    return f"{bare(amount, signed)}u"


def payout(spot: str, bet: float, outcome: str, pairs: dict) -> float:
    """What the bet won or lost, net of the stake."""
    if spot == "player":
        return 0.0 if outcome == "tie" else (bet if outcome == "player" else -bet)
    if spot == "banker":
        if outcome == "tie":
            return 0.0
        return bet * RULES.banker_pays if outcome == "banker" else -bet
    if spot == "tie":
        return bet * RULES.tie_pays if outcome == "tie" else -bet
    side = "player" if spot == "ppair" else "banker"
    return bet * RULES.pair_pays if pairs[side] else -bet


# --------------------------------------------------------------------------
# Pricing
# --------------------------------------------------------------------------

def price(state: dict) -> dict[str, float]:
    comp, ranks = composition(state)
    return bacmath.evs(comp, ranks, RULES)


def coach(state: dict, spot: str, bet: float) -> tuple[str, float]:
    """What every spot was worth a unit, and what this bet gave up.

    Priced before a card comes out, from the shoe as it stood when the chip
    went down. Fenced, because the comment this lands in is markdown and the
    numbers only line up in a code block.
    """
    priced = price(state)
    # The two pair bets are priced by the same formula, so whenever one is the
    # best the other is too, to the last bit. Every spot at the top is named.
    top = max(priced.values())
    bests = [name for name in SPOTS if priced[name] == top]
    named = " and ".join(SPOT_NAME[name] for name in bests)
    cost = (top - priced[spot]) * bet
    lines = ["```text"]
    for name, value in sorted(priced.items(), key=lambda kv: -kv[1]):
        mark = ("  best" if name in bests else "") + ("  <- you" if name == spot else "")
        lines.append(f"{SPOT_NAME[name]:<12}{value * 100:+8.3f}%{mark}")
    lines += ["```", ""]
    left = cards_left(state)
    if top > 0:
        # The moment the discard tray is there for: the shoe has turned a
        # spot in the player's favour.
        lines.append(f"With {left} cards left, {named} had the edge over the"
                     f" house: {top * 100:+.2f}% a unit.")
    if spot in bests:
        lines.append(f"That was the best bet on the layout, priced against the {left}"
                     " cards in the shoe before the deal.")
    else:
        lines.append(f"{named} {'was' if len(bests) == 1 else 'were'} worth more."
                     f" That chip gave up {(top - priced[spot]) * 100:.2f}% of"
                     f" {money(bet)}, about {cost:.3f} units, priced against the"
                     f" {left} cards in the shoe before the deal.")
    return "\n".join(lines), cost


# --------------------------------------------------------------------------
# A coup
# --------------------------------------------------------------------------

def deal(state: dict) -> tuple[list[str], list[str]]:
    return bacmath.deal(lambda: draw(state), value_of)


def bead_code(outcome: str, pairs: dict) -> str:
    return (outcome[0].upper() + ("p" if pairs["player"] else "")
            + ("b" if pairs["banker"] else ""))


def play(state: dict, spot: str, bet: float, number: int, user: str) -> str:
    if number != state["hand"]:
        return (f"That link was drawn for hand {number} and the table is on"
                f" {state['hand']}. Someone got there first, and the shoe has moved"
                " since — click again.")
    if spot not in SPOTS:
        return "That is not a spot on the layout."
    if bet not in CHIPS:
        return "That is not one of the chips."

    table, cost = coach(state, spot, bet)
    shoe_number = state["shoe"]["number"]

    player_cards, banker_cards = deal(state)
    pt, bt = total(player_cards), total(banker_cards)
    outcome = bacmath.winner(pt, bt)
    pairs = {"player": is_pair(player_cards), "banker": is_pair(banker_cards)}
    net = payout(spot, bet, outcome, pairs)

    name = handle(user)
    entry = {
        "number": number,
        "spot": spot,
        "bet": bet,
        "player": player_cards,
        "banker": banker_cards,
        "outcome": outcome,
        "pairs": pairs,
        "net": net,
        "cost": round(cost, 6),
        "by": name,
    }

    state["result"] += net
    state["hands_played"] += 1
    state["coach"]["cost"] += cost
    state["coach"]["bets"] += 1
    if name:
        who = player(state, name)
        who["hands"] += 1
        who["wagered"] += bet
        who["net"] += net
        who["cost"] += cost
    state["shoe"]["road"].append(bead_code(outcome, pairs))
    state["recent"].insert(0, entry)
    del state["recent"][MAX_RECENT:]
    state["hand"] = number + 1
    append_log(entry)
    reshuffle(state)

    played = state["hands_played"]
    lines = [
        describe(entry),
        "",
        f"The table is {money(state['result'], signed=True)} over {played}"
        f" hand{'' if played == 1 else 's'}.",
        "",
        table,
    ]
    if state["shoe"]["number"] != shoe_number:
        lines += ["", "That was the last coup before the cut card. The next hand"
                  " comes out of a fresh shoe."]
    return "\n".join(lines)


def describe(entry: dict) -> str:
    """One sentence for a coup that is over, player first because the player's
    cards come out first, then who won, then what the chip did."""
    p, b = entry["player"], entry["banker"]
    pt, bt = total(p), total(b)

    def side(name: str, cards: list, points: int) -> str:
        natural = " natural" if is_natural(cards) else ""
        return f"{name}{natural} {points} ({ranks_of(cards)})"

    outcome = entry.get("outcome") or bacmath.winner(pt, bt)
    verdict = {"player": "Player wins", "banker": "Banker wins",
               "tie": "A tie"}[outcome]
    pairs = [SPOT_NAME[k + "pair"].lower() for k in ("p", "b")
             if entry.get("pairs", {}).get("player" if k == "p" else "banker")]
    pair_note = f", with a {' and a '.join(pairs)}" if pairs else ""

    net = entry["net"]
    if net > 0:
        did = f"paid {money(net)}"
    elif net < 0:
        did = f"lost {money(-net)}"
    else:
        did = "came back as a push"
    who = f"@{entry['by']}'s" if handle(entry.get("by")) else "The"
    return (f"Hand {entry['number']}: {side('Player', p, pt)} against"
            f" {side('Banker', b, bt)}. {verdict}{pair_note}."
            f" {who} {money(entry['bet'])} on {SPOT_NAME[entry['spot']]} {did}.")


# --------------------------------------------------------------------------
# The log
# --------------------------------------------------------------------------

def header() -> str:
    return ("Baccarat played on github.com/0-draft/casino. Newest last.\n"
            "Hand, the bet, the player's cards and point, the banker's, the result"
            " (p and b mark a player or banker pair), what the bet paid, and who"
            " placed it.\n")


def append_log(entry: dict) -> None:
    p, b = entry["player"], entry["banker"]
    result = entry["outcome"] + "".join(
        f" {k}" for k in ("p", "b")
        if entry["pairs"]["player" if k == "p" else "banker"])
    bet = f"{money(entry['bet'])} {entry['spot']}"
    line = (f"  {entry['number']:>5}  {bet:<12}"
            f"  |  P {ranks_of(p)} {total(p)}  |  B {ranks_of(b)} {total(b)}"
            f"  |  {result}  |  {money(entry['net'], signed=True)}")
    if entry["by"]:
        line += f"  |  @{entry['by']}"
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = LOG_PATH.read_text(encoding="utf-8") if LOG_PATH.exists() else header()
    if not existing.endswith("\n"):
        existing += "\n"
    LOG_PATH.write_text(existing + line + "\n", encoding="utf-8")


def wrapped(tokens) -> str:
    """Indented lines of at most 100 characters, broken between tokens so a
    bead code or a rank is never split across two lines."""
    return textwrap.fill(" ".join(tokens), 100, initial_indent="    ",
                         subsequent_indent="    ") or "    (none)"


END_OF_SHOE = re.compile(r"(?m)^  end of shoe \d+\n\n?")


def log_shoe(state: dict) -> None:
    """Close the shoe with every card it dealt, in order, and its bead road, so
    anyone tracking it can check their numbers afterwards."""
    seen = state["shoe"]["seen"]
    road = state["shoe"]["road"]
    number = state["shoe"]["number"]
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # The summary follows the shoe's hands and the marker closes it, so every
    # shoe in the file is its hands, then its cards, then its road, then the
    # marker. Trimming at markers removes whole shoes and nothing else.
    entry = (f"  shoe {number} closed {stamp}, {len(seen)} cards, {len(road)} coups\n"
             f"{wrapped(rank_of(c) for c in seen)}\n  road\n{wrapped(road)}\n"
             f"  end of shoe {number}\n\n")
    existing = LOG_PATH.read_text(encoding="utf-8") if LOG_PATH.exists() else header()
    if not existing.endswith("\n"):
        existing += "\n"
    text = existing + entry
    body = text[len(header()):] if text.startswith(header()) else text
    ends = [m.end() for m in END_OF_SHOE.finditer(body)]
    if len(ends) > MAX_LOG_SHOES:
        text = header() + body[ends[-MAX_LOG_SHOES - 1]:]
    LOG_PATH.write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------
# Drawing the table
#
# Images inside a pre, because GitHub pads and borders every cell of a table and
# a row of cards would read as a spreadsheet. No width or height on the img,
# because a sized image is given a rounded border and a background of GitHub's
# choosing. Every image inside a link of our own, because without one GitHub
# wraps it in a link to the raw SVG.
# --------------------------------------------------------------------------

def issue_url(command: str) -> str:
    quoted = command.replace(" ", "+")
    return f"https://github.com/{REPO}/issues/new?title=bac%7C{quoted}&body={BODY}"


def here() -> str:
    return f"https://github.com/{REPO}#baccarat"


def img(name: str, alt: str) -> str:
    return f'<img src="{ASSET}/{name}.svg" align="top" alt="{alt}">'


def linked(inner: str, href: str) -> str:
    return f'<a href="{href}">{inner}</a>'


def felt(rows: list[str]) -> str:
    """Every row on its own line inside one pre. A pre per row would band the
    felt with GitHub's grey between them."""
    return '<div align="center"><pre>' + "\n".join(rows) + "</pre></div>"


def centre(text: str) -> str:
    return f'<p align="center">{text}</p>'


def card_row(label: str, cards: list[str], width: int = 3) -> str:
    images = [label] + [img(c, name_of(c)) for c in cards]
    images += [img("slot" if not cards else "blank", "")] * (width + 1 - len(images))
    return "".join(linked(i, here()) for i in images)


def coup_rows(state: dict) -> list[str]:
    if not state["recent"]:
        return [card_row(img("seat-player", "player"), []),
                card_row(img("seat-banker", "banker"), [])]
    entry = state["recent"][0]
    outcome = entry["outcome"]
    rows = []
    for side in ("player", "banker"):
        # A tie has no winner, so neither side is framed.
        won = outcome == side
        label = img(f"seat-{side}-won" if won else f"seat-{side}",
                    f"{side}, won" if won else side)
        rows.append(card_row(label, entry[side]))
    return rows


def layout(state: dict) -> str:
    """The bet spots, each followed by its chips. A chip is a link to an issue
    with the bet already written into the title."""
    number = state["hand"]
    rows = []
    for spot in SPOTS:
        images = [linked(img(f"spot-{spot}", SPOT_NAME[spot].lower()), here())]
        images += [
            linked(img(f"chip{v}", f"{v} on {SPOT_NAME[spot].lower()}"),
                   issue_url(f"bet {spot} {v} {number}"))
            for v in CHIPS
        ]
        rows.append("".join(images))
    return felt(rows)


def bead_plate(state: dict) -> str:
    """The scoreboard every baccarat table keeps: one cell per coup of this
    shoe, filled down six and then across. Only the last columns fit."""
    road = state["shoe"]["road"]
    columns = [road[i:i + BEAD_ROWS] for i in range(0, len(road), BEAD_ROWS)]
    columns = columns[-BEAD_COLS:]
    columns += [[]] * (BEAD_COLS - len(columns))
    names = {"P": "player", "B": "banker", "T": "tie"}
    rows = []
    for r in range(BEAD_ROWS):
        cells = []
        for col in columns:
            if r < len(col):
                code = col[r]
                alt = names[code[0]] + "".join(
                    f" {names[p.upper()]} pair" for p in code[1:])
                cells.append(linked(img(f"bead-{code}", alt), here()))
            else:
                cells.append(linked(img("bead-empty", ""), here()))
        rows.append("".join(cells))
    return felt(rows)


def headline(state: dict) -> str:
    deal_next = f"Pick a spot and a chip to deal hand {state['hand']}."
    if state["recent"]:
        return f"{describe(state['recent'][0])} {deal_next}"
    return deal_next


def how() -> str:
    return centre(
        "Bet on the hand that comes closest to 9. A chip opens a prefilled issue:"
        " submit it and the cards come out in about 30 seconds."
    )


def shoe_line(state: dict) -> str:
    left = cards_left(state)
    seen = state["shoe"]["seen"]
    road = state["shoe"]["road"]
    counts = {k: sum(1 for r in road if r[0] == k) for k in "PBT"}
    tally = (f" · P {counts['P']} B {counts['B']} T {counts['T']}" if road else "")
    if not seen:
        return centre(f"Shoe {state['shoe']['number']} · freshly shuffled"
                      f" · {left / 52:.1f} decks left")
    tray = " ".join(rank_of(c) for c in seen[-TRAY:])
    where = f"https://github.com/{REPO}/blob/main/.github/baccarat.json"
    rest = f' · <a href="{where}">all {len(seen)}</a>' if len(seen) > TRAY else ""
    return centre(f"Shoe {state['shoe']['number']}{tally} · {left / 52:.1f} decks left"
                  f" · out of it: {tray}{rest}")


def stats_line(state: dict) -> str:
    played = state["hands_played"]
    people = len(state["players"])
    parts = [
        f"{money(state['result'], signed=True)} over {played}"
        f" hand{'' if played == 1 else 's'}",
        f"{people} player{'' if people == 1 else 's'}",
    ]
    if state["coach"]["bets"]:
        parts.append(f"{money(state['coach']['cost'])} given up to worse bets")
    return centre(" · ".join(parts))


def elide(name: str) -> str:
    return name if len(name) <= MAX_NAME else name[:MAX_NAME - 1] + "…"


def recent_table(state: dict) -> list[str]:
    if not state["recent"]:
        return []
    rows = []
    for entry in state["recent"]:
        name = handle(entry.get("by"))
        who = (f' <a href="https://github.com/{name}" title="@{name}">@{elide(name)}</a>'
               if name else "")
        p, b = entry["player"], entry["banker"]
        mark = {"player": ("<em>", "</em>", "", ""), "banker": ("", "", "<em>", "</em>"),
                "tie": ("", "", "", "")}[entry["outcome"]]
        rows.append(
            f"    <tr><td><code>{entry['number']}</code>{who}</td>"
            f"<td>{money(entry['bet'])} {SPOT_NAME[entry['spot']]}</td>"
            f"<td>{mark[0]}{total(p)} ({ranks_of(p)}){mark[1]}</td>"
            f"<td>{mark[2]}{total(b)} ({ranks_of(b)}){mark[3]}</td>"
            f"<td><code>{money(entry['net'], signed=True)}</code></td></tr>"
        )
    return [
        '<table align="center">',
        "  <thead>",
        "    <tr><th>Hand</th><th>Bet</th><th>Player</th><th>Banker</th><th></th></tr>",
        "  </thead>",
        "  <tbody>",
        *rows,
        "  </tbody>",
        "</table>",
    ]


def sign() -> str:
    return centre(
        f"Punto banco · {RULES.decks} decks · banker pays {RULES.banker_pays:g} to 1 · tie pays"
        f" {RULES.tie_pays:g} to 1 and pushes the player and banker bets · pairs pay"
        f" {RULES.pair_pays:g} to 1 · shuffled at the cut card, {RULES.cut} cards"
        " from the end"
    )


def render(state: dict) -> str:
    lines = [felt(coup_rows(state)), "", centre(headline(state)), "",
             layout(state), "", how(), "", bead_plate(state), "",
             shoe_line(state), "", stats_line(state), ""]
    table = recent_table(state)
    if table:
        lines += table + [""]
    lines.append(sign())
    return "\n".join(lines)


def write_readme(state: dict) -> None:
    content = README_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"{re.escape(START_MARKER)}.*?{re.escape(END_MARKER)}", re.DOTALL
    )
    if not pattern.search(content):
        raise SystemExit("BACCARAT markers not found in README.md")
    block = f"{START_MARKER}\n{render(state)}\n{END_MARKER}"
    README_PATH.write_text(pattern.sub(lambda _: block, content), encoding="utf-8")


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def parse(title: str) -> tuple[str, float, int] | None:
    # The same pattern the gate job in .github/workflows/baccarat.yml checks,
    # so nothing it lets through is refused here and nothing else gets this far.
    match = re.fullmatch(
        r"bac\|bet (player|banker|tie|ppair|bpair) (1|2|5|10|25) (\d{1,9})",
        title.strip(),
    )
    if not match:
        return None
    return match.group(1), float(match.group(2)), int(match.group(3))


def main() -> None:
    title = os.environ.get("ISSUE_TITLE", "")
    user = os.environ.get("ISSUE_USER", "")

    command = parse(title)
    if command is None:
        print("That is not a bet I can read. Click a chip on the table instead.")
        return

    state = load_state()
    spot, bet, number = command
    before = state["hand"]
    message = play(state, spot, bet, number, user)
    # A refused bet leaves the table as it was, and writes nothing: rewriting
    # an unchanged hand would still commit whatever load_state() tidied up.
    if state["hand"] != before:
        # The state file first: it is what the next click plays against, and
        # the table is drawn from it.
        save_state(state)
        write_readme(state)
    print(message)


if __name__ == "__main__":
    main()
