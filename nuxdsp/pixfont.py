"""Our own pixel fonts for redrawing the text in UI images (buttons, headers, dialogs).

`small`: capitals 5 rows high, mostly 4 px wide, with a 3 px `narrow` form of each letter for long
words. Polish accents go in the row above the letter (acute, dot) and the row below (ogonek), so a
line of text is 7 rows: accent row, 5 letter rows, ogonek row. `bold`: 7 rows, 2 px strokes, no
accents (only the letters the translations need). Lowercase input is drawn as capitals.
"""

SMALL = {
    "A": ".##. #..# #### #..# #..#", "B": "###. #..# ###. #..# ###.", "C": ".### #... #... #... .###",
    "D": "###. #..# #..# #..# ###.", "E": "#### #... ###. #... ####", "F": "#### #... ###. #... #...",
    "G": ".### #... #.## #..# .###", "H": "#..# #..# #### #..# #..#", "I": "### .#. .#. .#. ###",
    "J": "...# ...# ...# #..# .##.", "K": "#..# #.#. ##.. #.#. #..#", "L": "#... #... #... #... ####",
    "Ł": "#... #.#. ##.. #... ####", "M": "#...# ##.## #.#.# #...# #...#", "N": "#..# ##.# #.## #..# #..#",
    "O": ".##. #..# #..# #..# .##.", "P": "###. #..# ###. #... #...", "Q": ".##. #..# #..# #.#. .#.#",
    "R": "###. #..# ###. #.#. #..#", "S": ".### #... .##. ...# ###.", "T": "### .#. .#. .#. .#.",
    "U": "#..# #..# #..# #..# .##.", "V": "#...# #...# .#.#. .#.#. ..#..", "W": "#...# #...# #.#.# ##.## #...#",
    "X": "#..# #..# .##. #..# #..#", "Y": "#.# #.# .#. .#. .#.", "Z": "#### ...# .##. #... ####",
    "0": ".##. #..# #..# #..# .##.", "1": ".#. ##. .#. .#. ###", "2": "###. ...# .##. #... ####",
    "3": "###. ...# .##. ...# ###.", "4": "#..# #..# #### ...# ...#", "5": "#### #... ###. ...# ###.",
    "6": ".##. #... ###. #..# .##.", "7": "#### ...# ..#. .#.. .#..", "8": ".##. #..# .##. #..# .##.",
    "9": ".##. #..# .### ...# .##.",
    " ": ".. .. .. .. ..", ".": ". . . . #", ",": ". . . # #", "!": "# # # . #", ":": ". # . # .",
    "?": ".##. #..# ..#. .... ..#.", "/": "..# ..# .#. #.. #..", "-": "... ... ### ... ...",
    "+": "... .#. ### .#. ...", "<": "..# .#. #.. .#. ..#", ">": "#.. .#. ..# .#. #..",
    "&": ".#.. #.#. .#.. #.#. .#.#", "'": "# # . . .", "(": ".# #. #. #. .#", ")": "#. .# .# .# #.",
}
NARROW = {
    "A": ".#. #.# ### #.# #.#", "B": "##. #.# ##. #.# ##.", "C": ".## #.. #.. #.. .##", "D": "##. #.# #.# #.# ##.",
    "E": "### #.. ##. #.. ###", "F": "### #.. ##. #.. #..", "G": ".## #.. #.# #.# .##", "H": "#.# #.# ### #.# #.#",
    "J": "..# ..# ..# #.# .#.", "K": "#.# #.# ##. #.# #.#", "L": "#.. #.. #.. #.. ###", "Ł": "#.. #.. ##. #.. ###",
    "M": "#.# ### ### #.# #.#", "N": "##. #.# #.# #.# #.#", "O": ".#. #.# #.# #.# .#.", "P": "##. #.# ##. #.. #..",
    "Q": ".#. #.# #.# #.# .##", "R": "##. #.# ##. #.# #.#", "S": ".## #.. .#. ..# ##.", "U": "#.# #.# #.# #.# ###",
    "V": "#.# #.# #.# #.# .#.", "W": "#.# #.# ### ### #.#", "X": "#.# #.# .#. #.# #.#", "Z": "### ..# .#. #.. ###",
    "0": "### #.# #.# #.# ###", "2": "##. ..# .#. #.. ###", "3": "##. ..# .#. ..# ##.", "4": "#.# #.# ### ..# ..#",
    "5": "### #.. ##. ..# ##.", "6": ".## #.. ### #.# ###", "7": "### ..# .#. .#. .#.", "8": "### #.# ### #.# ###",
    "9": "### #.# ### ..# ##.", "?": "##. ..# .#. ... .#.", " ": ". . . . .",
}
BOLD = {
    "W": "##...## ##...## ##.#.## ##.#.## ####### ###.### ##...##", "I": "## ## ## ## ## ## ##",
    "T": "###### ###### ..##.. ..##.. ..##.. ..##.. ..##..",
    "A": "..##.. .####. ##..## ##..## ###### ##..## ##..##",
    "J": "....## ....## ....## ....## ##..## ##..## .####.", "!": "## ## ## ## ## .. ##", " ": "... ... ... ... ... ... ...",
}
ACCENTS = {  # letter: (base, mark): acute and dot above, ogonek below
    "Ą": ("A", "ogonek"), "Ć": ("C", "acute"), "Ę": ("E", "ogonek"), "Ń": ("N", "acute"), "Ó": ("O", "acute"),
    "Ś": ("S", "acute"), "Ź": ("Z", "acute"), "Ż": ("Z", "dot"),
}


class FontError(Exception):
    pass


def glyph(ch, font):
    """-> list of rows ('#'/'.'), 7 rows for every font (small: accent row + 5 + ogonek row)."""
    ch = ch.upper()
    if font == "bold":
        if ch not in BOLD:
            raise FontError("bold font has no %r" % ch)
        return BOLD[ch].split()
    base, mark = ACCENTS.get(ch, (ch, None))
    table = NARROW if font == "narrow" and base in NARROW else SMALL
    if base not in table:
        raise FontError("no glyph for %r" % ch)
    rows = table[base].split()
    w = len(rows[0])
    top, bottom = ["." * w], ["." * w]
    if mark in ("acute", "dot"):
        x = (w + 1) // 2 if mark == "acute" else w // 2
        top = ["." * x + "#" + "." * (w - x - 1)]
    elif mark == "ogonek":
        bottom = ["." * (w - 1) + "#"]
    return top + rows + bottom


def render(text, font="small", gap=1):
    """-> rows of the whole line (7 rows), width."""
    gs = [glyph(c, font) for c in text]
    rows = ["" for _ in range(7)]
    for i, g in enumerate(gs):
        for y in range(7):
            rows[y] += ("." * gap if i else "") + g[y]
    return rows, len(rows[0])


def fit(text, width, bold=False):
    """The widest form of text that fits: normal, then narrow letters. -> rows."""
    for font in (("bold",) if bold else ("small", "narrow")):
        rows, w = render(text, font)
        if w <= width:
            return rows
    raise FontError("%r is %d px wide, only %d px fit" % (text, w, width))


def draw(width, height, lines, inverse=False, bold=False):
    """Rows of a width x height rectangle: background, each (top, text) centred horizontally.

    top is the row of the letters' top (the accent goes in the row above it)."""
    bg, fg = ("#", ".") if inverse else (".", "#")
    canvas = [[bg] * width for _ in range(height)]
    for top, text in lines:
        rows = fit(text, width, bold)
        x0 = (width - len(rows[0]) + 1) // 2
        for y, row in enumerate(rows):
            yy = top + y - (0 if bold else 1)
            for x, c in enumerate(row):
                if c == "#":
                    if not 0 <= yy < height:
                        raise FontError("%r does not fit in %d rows at row %d" % (text, height, top))
                    canvas[yy][x0 + x] = fg
    return ["".join(r) for r in canvas]
