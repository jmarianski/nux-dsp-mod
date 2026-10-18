"""Full-screen pictures for the title and the skill menu, as framebuffer images (1024 words: page * 128 + x, bit
y & 7, a set bit inked, dark on the LCD).

TITLE   the DOOM logo (art/doom_logo.txt), "UNOFFICIAL PORT" and "PRESS ANY KEY": Freedoom's TITLEPIC is too busy
        for 128 x 56 one-bit pixels. Another WAD's TITLEPIC, averaged down and Floyd-Steinberg dithered, "PRESS ANY
        KEY" below
MENU    "NEW GAME", "CHOOSE SKILL LEVEL:" and Doom's five skills; the firmware draws the cursor (MENU_X, MENU_Y)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import walltex  # noqa: E402

W, H = 128, 64
SKILLS = ["I'M TOO YOUNG TO DIE", "HEY, NOT TOO ROUGH", "HURT ME PLENTY", "ULTRA-VIOLENCE", "NIGHTMARE!"]
CONTRAST = 0.7                                 # < 1 lifts the dark TITLEPIC
MENU_X, MENU_Y, MENU_STEP = 22, 25, 8          # first skill's text, the next one MENU_STEP rows lower

GLYPHS = {
    'A': ['.#.', '#.#', '###', '#.#', '#.#'],
    'B': ['##.', '#.#', '##.', '#.#', '##.'],
    'C': ['.##', '#..', '#..', '#..', '.##'],
    'D': ['##.', '#.#', '#.#', '#.#', '##.'],
    'E': ['###', '#..', '##.', '#..', '###'],
    'F': ['###', '#..', '##.', '#..', '#..'],
    'G': ['.##', '#..', '#.#', '#.#', '.##'],
    'H': ['#.#', '#.#', '###', '#.#', '#.#'],
    'I': ['###', '.#.', '.#.', '.#.', '###'],
    'J': ['..#', '..#', '..#', '#.#', '.#.'],
    'K': ['#.#', '#.#', '##.', '#.#', '#.#'],
    'L': ['#..', '#..', '#..', '#..', '###'],
    'M': ['#.#', '###', '###', '#.#', '#.#'],
    'N': ['##.', '#.#', '#.#', '#.#', '#.#'],
    'O': ['.#.', '#.#', '#.#', '#.#', '.#.'],
    'P': ['##.', '#.#', '##.', '#..', '#..'],
    'Q': ['.#.', '#.#', '#.#', '##.', '.##'],
    'R': ['##.', '#.#', '##.', '#.#', '#.#'],
    'S': ['.##', '#..', '.#.', '..#', '##.'],
    'T': ['###', '.#.', '.#.', '.#.', '.#.'],
    'U': ['#.#', '#.#', '#.#', '#.#', '###'],
    'V': ['#.#', '#.#', '#.#', '#.#', '.#.'],
    'W': ['#.#', '#.#', '###', '###', '#.#'],
    'X': ['#.#', '#.#', '.#.', '#.#', '#.#'],
    'Y': ['#.#', '#.#', '.#.', '.#.', '.#.'],
    'Z': ['###', '..#', '.#.', '#..', '###'],
    "'": ['.#.', '.#.', '...', '...', '...'],
    ',': ['...', '...', '...', '.#.', '#..'],
    '-': ['...', '...', '###', '...', '...'],
    '!': ['.#.', '.#.', '.#.', '...', '.#.'],
    ':': ['...', '.#.', '...', '.#.', '...'],
    '.': ['...', '...', '...', '...', '.#.'],
    ' ': ['...', '...', '...', '...', '...'],
}


def text(img, x, y, s, scale=1):
    for ch in s:
        for r, row in enumerate(GLYPHS[ch]):
            for c, v in enumerate(row):
                if v == "#":
                    for dy in range(scale):
                        for dx in range(scale):
                            if 0 <= x + c * scale + dx < W and 0 <= y + r * scale + dy < H:
                                img[y + r * scale + dy][x + c * scale + dx] = 1
        x += 4 * scale


def text_width(s, scale=1):
    return (4 * len(s) - 1) * scale


def pack(img):
    return [sum(img[8 * p + b][x] << b for b in range(8)) for p in range(8) for x in range(W)]


def centered(img, y, s, scale=1):
    text(img, (W - text_width(s, scale)) // 2, y, s, scale)


LOGO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "art", "doom_logo.txt")


def title_logo():
    rows = [r.strip() for r in open(LOGO) if r.strip() and not r.startswith("#")]
    img = [[0] * W for _ in range(H)]
    left = (W - len(rows[0])) // 2
    for y, row in enumerate(rows):
        for x, v in enumerate(row):
            img[1 + y][left + x] = v == "#"
    centered(img, 1 + len(rows) + 3, "UNOFFICIAL PORT")
    centered(img, 58, "PRESS ANY KEY")
    return pack(img)


def title(w):
    if any(name == "FREEDOOM" for name, _, _ in w.lumps):
        return title_logo()
    gfx = walltex.Graphics(w)
    d = w.lump("TITLEPIC")
    import struct
    width, height = struct.unpack("<HH", d[:4])
    lum = [[0] * width for _ in range(height)]
    gfx.patch("TITLEPIC", lum, 0, 0)
    rows = 56
    g = [[0.0] * W for _ in range(rows)]
    for y in range(rows):
        y0, y1 = y * height // rows, (y + 1) * height // rows
        for x in range(W):
            x0, x1 = x * width // W, (x + 1) * width // W
            px = [lum[j][i] for j in range(y0, y1) for i in range(x0, x1)]
            g[y][x] = sum(px) / len(px)
    every = sorted(v for row in g for v in row)
    lo, hi = every[len(every) * 5 // 100], every[len(every) * 97 // 100]
    for y in range(rows):
        for x in range(W):
            g[y][x] = max(0.0, min(1.0, (g[y][x] - lo) / (hi - lo))) ** CONTRAST
    img = [[0] * W for _ in range(H)]
    for y in range(rows):
        for x in range(W):
            v = g[y][x]
            bright = v >= 0.5
            img[y][x] = 0 if bright else 1
            e = v - bright
            for dy, dx, k in ((0, 1, 7), (1, -1, 3), (1, 0, 5), (1, 1, 1)):
                if y + dy < rows and 0 <= x + dx < W:
                    g[y + dy][x + dx] += e * k / 16
    s = "PRESS ANY KEY"
    text(img, (W - text_width(s)) // 2, 58, s)
    return pack(img)


def menu():
    img = [[0] * W for _ in range(H)]
    s = "NEW GAME"
    text(img, (W - text_width(s, 2)) // 2, 2, s, 2)
    s = "CHOOSE SKILL LEVEL:"
    text(img, (W - text_width(s)) // 2, 15, s)
    for k, s in enumerate(SKILLS):
        text(img, MENU_X, MENU_Y + MENU_STEP * k, s)
    return pack(img)


def words(w):
    """TITLE then MENU."""
    return title(w) + menu()
