#!/usr/bin/env python3
"""
make_cards.py

Draws the images for both tables (.github/cards/*.svg). Run by hand, never from
an Action; checks.yml fails a pull request whose committed art no longer
matches this file.

The two tables share one felt, one deck of cards, the empty slot, the padding
tile and the chips, so those are drawn once and both renderers name the same
files. What only one game uses is drawn next to it: the face-down card, the
buttons and the dealer/you seats for blackjack; the bet spots, the bead plate
and the player/banker seats for baccarat. The baccarat seats are named seat-*
rather than label-* so they cannot collide with blackjack's label-player.

Every tile paints its own felt background. Nothing else can: GitHub strips style
from README HTML, so a row of cards cannot be given a background, and a
transparent tile would take the colour of GitHub's image placeholder. Painting
the felt into each tile is what makes a row of separate images read as one
table, the same trick the shogi board used to look like a board.

The suits are paths rather than the ♠♥♦♣ characters. An SVG loaded through
<img> resolves fonts on the reader's machine, and those four characters differ
wildly between platforms — some render them as emoji. The ranks are text, since
digits and A/J/Q/K are safe everywhere, but every string is drawn with
textLength so a wider font cannot push it out of its tile.
"""

import pathlib

OUT = pathlib.Path(".github/cards")

# A card tile. The card itself is inset, so the felt shows as a gap between
# neighbours and a hand reads as cards laid on a table.
W, H = 44, 62

FELT = "#1c5c43"
FELT_LINE = "#14472f"

FACE = "#fbf9f4"
FACE_EDGE = "#d8d2c4"
INK = "#1f2328"
RED = "#b3261e"

# Blackjack: the back of a card, and the frame that says which hand is being
# played. Both borrow the shogi board's palette.
BACK = "#8b1f2f"
BACK_LINE = "#6d1724"
MARKER = "#c1121f"

# Baccarat: the frame that marks the side that won.
WON = "#e0b54a"

# Buttons are the shogi piece's wood, for the same reason.
WOOD = "#f0d9a8"
WOOD_EDGE = "#8b6f47"

# What a real table has printed on the cloth: readable, and quieter than a card.
PRINT = "#8fb3a0"
PRINT_DIM = "#6f9784"

# The colours every baccarat scoreboard uses for the three results.
SIDE = {"P": "#2f5fa8", "B": "#c1272d", "T": "#2e7d4f"}
SIDE_INK = "#ffffff"

FONT = "'Helvetica Neue',Helvetica,Arial,'Liberation Sans',sans-serif"

RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K"]
LABEL = {"T": "10"}
SUITS = {"S": "spade", "H": "heart", "D": "diamond", "C": "club"}
RED_SUITS = ("H", "D")

# Each suit drawn inside a 24x24 box, so one scale factor places it anywhere.
SUIT_PATHS = {
    "S": ('<path d="M12 2C12 2 3.6 9.2 3.6 14.4a4.6 4.6 0 0 0 7.5 3.6c-.2 1.4-1.2 3.4-2.7 4.8h7.2'
          'c-1.5-1.4-2.5-3.4-2.7-4.8a4.6 4.6 0 0 0 7.5-3.6C20.4 9.2 12 2 12 2Z" fill="{ink}"/>'),
    "H": ('<path d="M12 21.6S3 14.8 3 9.2A4.9 4.9 0 0 1 12 6.4 4.9 4.9 0 0 1 21 9.2'
          'c0 5.6-9 12.4-9 12.4Z" fill="{ink}"/>'),
    "D": '<path d="M12 1.6 20.4 12 12 22.4 3.6 12Z" fill="{ink}"/>',
    "C": ('<g fill="{ink}"><circle cx="12" cy="7.4" r="4.2"/><circle cx="6.9" cy="14.4" r="4.2"/>'
          '<circle cx="17.1" cy="14.4" r="4.2"/>'
          '<path d="M10.9 13.2h2.2c0 4.2.6 7.2 2.6 9.2h-7.4c2-2 2.6-5 2.6-9.2Z"/></g>'),
}

# value -> (face, edge, ink). The colours a real rack uses, as far as the
# denominations here overlap with one. Both tables take the same five.
CHIPS = {
    1: ("#f7f4ee", "#cfc9bb", INK),
    2: ("#d98ca6", "#b26c84", INK),
    5: ("#c1272d", "#8e1c21", "#fdf7f7"),
    10: ("#2f5fa8", "#22467c", "#f4f7fd"),
    25: ("#2e7d4f", "#1f5a38", "#f4faf6"),
}
CHIP = 44

# Blackjack's decisions.
BUTTONS = ["hit", "stand", "double", "split", "surrender", "insure", "no"]
BUTTON_H = 30

# Baccarat's bet spots, as printed on the layout: name, then what it pays.
SPOTS = {
    "player": ("PLAYER", "1 TO 1"),
    "banker": ("BANKER", "0.95 TO 1"),
    "tie": ("TIE", "8 TO 1"),
    "ppair": ("P PAIR", "11 TO 1"),
    "bpair": ("B PAIR", "11 TO 1"),
}
SPOT_W = 84

# One cell of the baccarat bead plate.
BEAD = 22
OUTCOMES = ("P", "B", "T")
PAIRS = ("", "p", "b", "pb")


# --------------------------------------------------------------------------
# Shared by both tables
# --------------------------------------------------------------------------

def head(w: int, h: int, label: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}"'
            f' width="{w}" height="{h}" role="img" aria-label="{label}">')


def felt(w: int, h: int) -> str:
    return f'\n  <rect width="{w}" height="{h}" fill="{FELT}"/>'


def pip(suit: str, cx: float, cy: float, size: float, ink: str) -> str:
    """A suit centred on (cx, cy), size being the width of its 24-unit box."""
    k = size / 24
    return (f'\n  <g transform="translate({cx - size / 2:.2f} {cy - size / 2:.2f})'
            f' scale({k:.4f})">{SUIT_PATHS[suit].format(ink=ink)}</g>')


def text(body: str, x: float, y: float, size: float, ink: str, width: float,
         weight: int = 700, spacing: float = 0) -> str:
    """Text pinned to an exact width, because the reader's fonts are unknown."""
    extra = f' letter-spacing="{spacing}"' if spacing else ""
    return (f'\n  <text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}"'
            f' font-weight="{weight}"{extra} fill="{ink}" text-anchor="middle"'
            f' textLength="{width}" lengthAdjust="spacingAndGlyphs">{body}</text>')


def card(rank: str, suit: str) -> str:
    ink = RED if suit in RED_SUITS else INK
    label = LABEL.get(rank, rank)
    name = f"{'ten' if rank == 'T' else label} of {SUITS[suit]}s"
    # The corner index is narrower for the ten, so a two-character rank does not
    # crowd the pip under it.
    index_width = 13 if rank == "T" else 9
    return (
        head(W, H, name)
        + felt(W, H)
        + f'\n  <rect x="2.5" y="2.5" width="{W - 5}" height="{H - 5}" rx="4"'
          f' fill="{FACE}" stroke="{FACE_EDGE}"/>'
        + text(label, 11, 18, 14, ink, index_width)
        + pip(suit, 11, 26, 9, ink)
        + pip(suit, 26, 42, 25, ink)
        + "\n</svg>\n"
    )


def blank() -> str:
    """Felt and nothing else, to pad a short row out to the width of the
    longest one. Rows are centred, so without it a split hand staggers."""
    return head(W, H, "") + felt(W, H) + "\n</svg>\n"


def slot() -> str:
    """Where a card will be dealt. Without it the table collapses to nothing
    between hands, and the section jumps by two card-heights on every deal."""
    return (
        head(W, H, "empty card slot")
        + felt(W, H)
        + f'\n  <rect x="3" y="3" width="{W - 6}" height="{H - 6}" rx="4" fill="none"'
          f' stroke="{FELT_LINE}" stroke-width="1.5" stroke-dasharray="4 4"/>'
        + "\n</svg>\n"
    )


def chip(value: int) -> str:
    """A chip. The alt text each table gives it says what clicking it does, so
    the file itself only says what it is worth."""
    face, edge, ink = CHIPS[value]
    c = CHIP / 2
    # The spots on the rim, which is what says chip rather than coin.
    spots = "".join(
        f'\n    <rect x="{c - 2.6}" y="1.6" width="5.2" height="6" rx="1.6"'
        f' transform="rotate({angle} {c} {c})"/>'
        for angle in range(0, 360, 45)
    )
    return (
        head(CHIP, CHIP, f"{value} unit{'' if value == 1 else 's'}")
        + felt(CHIP, CHIP)
        + f'\n  <circle cx="{c}" cy="{c}" r="{c - 3}" fill="{face}" stroke="{edge}"'
          f' stroke-width="1.5"/>'
        + f'\n  <g fill="{edge}">{spots}\n  </g>'
        + f'\n  <circle cx="{c}" cy="{c}" r="{c - 9}" fill="{face}" stroke="{edge}"/>'
        + text(str(value), c, c + 5, 15, ink, 9 if value < 10 else 17)
        + "\n</svg>\n"
    )


def seat(word: str, w: int, frame: str = "", aria: str = "", ink: str = PRINT) -> str:
    """Whose row this is, printed on the felt at the head of it.

    A real table has its layout printed on the cloth, and these need it more
    than most: the only other thing saying whose row is whose is a sentence
    underneath, and a reader should not have to find a sentence to read a
    table. A frame, in the given colour, marks the row that matters: the split
    hand in play at blackjack, the side that won at baccarat.
    """
    border = (f'\n  <rect x="2.25" y="2.25" width="{w - 4.5}" height="{H - 4.5}" fill="none"'
              f' stroke="{frame}" stroke-width="3"/>' if frame else "")
    body = word.upper()
    return (head(w, H, aria or word)
            + felt(w, H)
            + text(body, w / 2, H / 2 + 4, 9, ink, round(len(body) * 6.4), spacing=1)
            + border
            + "\n</svg>\n")


# --------------------------------------------------------------------------
# Blackjack only
# --------------------------------------------------------------------------

BJ_SEAT_W = 52


def back() -> str:
    """The hole card. A pattern, not a flat colour, so it reads as face down."""
    lines = "".join(
        f'\n    <path d="M{x} 6 L{x + 14} {H - 6}" />' for x in range(-8, W + 8, 7)
    )
    return (
        head(W, H, "face down card")
        + felt(W, H)
        + '\n  <clipPath id="card">'
          f'<rect x="2.5" y="2.5" width="{W - 5}" height="{H - 5}" rx="4"/></clipPath>'
        + f'\n  <rect x="2.5" y="2.5" width="{W - 5}" height="{H - 5}" rx="4" fill="{BACK}"/>'
        + f'\n  <g clip-path="url(#card)" stroke="{BACK_LINE}" stroke-width="2.5">{lines}\n  </g>'
        + f'\n  <rect x="2.5" y="2.5" width="{W - 5}" height="{H - 5}" rx="4"'
          f' fill="none" stroke="{FACE}" stroke-width="2"/>'
        + "\n</svg>\n"
    )


def button(label: str) -> str:
    body = label.upper()
    # Wide enough for the label at 8.4 units a character, which is what the
    # textLength below then holds it to.
    inner = round(len(body) * 8.4)
    w = inner + 24
    return (
        head(w, BUTTON_H, label)
        + felt(w, BUTTON_H)
        + f'\n  <rect x="2" y="3" width="{w - 4}" height="{BUTTON_H - 6}" rx="4"'
          f' fill="{WOOD}" stroke="{WOOD_EDGE}" stroke-width="1.5"/>'
        + text(body, w / 2, BUTTON_H / 2 + 4, 12, INK, inner)
        + "\n</svg>\n"
    )


# --------------------------------------------------------------------------
# Baccarat only
# --------------------------------------------------------------------------

BAC_SEAT_W = 60


def spot(key: str) -> str:
    """A bet spot printed on the cloth, at the head of its row of chips."""
    word, pays = SPOTS[key]
    h = CHIP
    return (
        head(SPOT_W, h, f"{word.lower()}, pays {pays.lower()}")
        + felt(SPOT_W, h)
        + f'\n  <rect x="3" y="4" width="{SPOT_W - 6}" height="{h - 8}" rx="6" fill="none"'
          f' stroke="{PRINT_DIM}" stroke-width="1.2"/>'
        + text(word, SPOT_W / 2, 21, 11, PRINT, round(len(word) * 7.6), spacing=1)
        + text(pays, SPOT_W / 2, 33, 8, PRINT_DIM, round(len(pays) * 5.2), weight=600)
        + "\n</svg>\n"
    )


def bead(outcome: str, pairs: str) -> str:
    """One cell of the bead plate: a disc for who won, and a dot in the corner
    for each side whose first two cards paired, as a real scoreboard marks
    them."""
    c = BEAD / 2
    names = {"P": "player", "B": "banker", "T": "tie"}
    label = names[outcome] + "".join(
        f", {names[p.upper()]} pair" for p in pairs)
    dots = ""
    if "p" in pairs:
        dots += (f'\n  <circle cx="4.5" cy="4.5" r="2.8" fill="{SIDE["P"]}"'
                 f' stroke="{SIDE_INK}" stroke-width="1"/>')
    if "b" in pairs:
        dots += (f'\n  <circle cx="{BEAD - 4.5}" cy="{BEAD - 4.5}" r="2.8"'
                 f' fill="{SIDE["B"]}" stroke="{SIDE_INK}" stroke-width="1"/>')
    return (
        head(BEAD, BEAD, label)
        + felt(BEAD, BEAD)
        + f'\n  <rect x="0.5" y="0.5" width="{BEAD - 1}" height="{BEAD - 1}" fill="none"'
          f' stroke="{FELT_LINE}"/>'
        + f'\n  <circle cx="{c}" cy="{c}" r="8" fill="{SIDE[outcome]}"/>'
        + text(outcome, c, c + 3.6, 10, SIDE_INK, 6.5)
        + dots
        + "\n</svg>\n"
    )


def bead_empty() -> str:
    return (
        head(BEAD, BEAD, "")
        + felt(BEAD, BEAD)
        + f'\n  <rect x="0.5" y="0.5" width="{BEAD - 1}" height="{BEAD - 1}" fill="none"'
          f' stroke="{FELT_LINE}"/>'
        + "\n</svg>\n"
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    written = 0

    def write(name: str, body: str) -> None:
        nonlocal written
        (OUT / f"{name}.svg").write_text(body, encoding="utf-8")
        written += 1

    # Both tables.
    for rank in RANKS:
        for suit in SUITS:
            write(f"{rank}{suit}", card(rank, suit))
    write("slot", slot())
    write("blank", blank())
    for value in CHIPS:
        write(f"chip{value}", chip(value))

    # Blackjack.
    write("back", back())
    for label in BUTTONS:
        write(f"btn-{label}", button(label))
    write("label-dealer", seat("dealer", BJ_SEAT_W))
    write("label-you", seat("you", BJ_SEAT_W))
    write("label-you-sel", seat("you", BJ_SEAT_W, frame=MARKER, aria="you in play"))
    # The hand on the felt between deals belongs to whoever played it, and the
    # sentence under it says which account that was. "You" on that row would be
    # addressing a reader who was not there.
    write("label-player", seat("player", BJ_SEAT_W))

    # Baccarat.
    for key in SPOTS:
        write(f"spot-{key}", spot(key))
    for side in ("player", "banker"):
        write(f"seat-{side}", seat(side, BAC_SEAT_W))
        write(f"seat-{side}-won", seat(side, BAC_SEAT_W, frame=WON,
                                        aria=f"{side}, won", ink=WON))
    for outcome in OUTCOMES:
        for pairs in PAIRS:
            write(f"bead-{outcome}{pairs}", bead(outcome, pairs))
    write("bead-empty", bead_empty())

    print(f"wrote {written} files to {OUT}")


if __name__ == "__main__":
    main()
