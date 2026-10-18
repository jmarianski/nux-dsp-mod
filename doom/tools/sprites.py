"""Monster and pickup sprites from the WAD, as the walls are drawn: 4-bit grays dithered in screen space.

A texel is 2x2 Doom pixels, opaque when at least two of them are. Each frame's luminance is stretched over its own
range (10th..95th percentile, then a power STRETCH > 1): the body comes out dark, so a monster reads as an inked
silhouette with its highlights, not as one more gray among the walls. Each column holds 32 rows of nibbles (8 words, row
4k + j in bits 4j..4j+3 of word k): 0..13 a gray (lit and compared with the Bayer threshold, inked below it),
14 the sprite's edge (never inked: a light outline that separates it from a dark background), 15 transparent.

sprites table: one offset per frame (FRAMES order), then per frame: columns, rows, left offset, top offset (map units,
as Doom places the patch), then the columns.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import walltex  # noqa: E402

STRETCH = 1.4

# Rotation 1 (facing the player) of each monster; pickups have one view.
ZOMBIE = ["POSSA1", "POSSB1", "POSSC1", "POSSD1", "POSSF1", "POSSG1", "POSSH0", "POSSI0", "POSSJ0", "POSSK0", "POSSL0"]
SERGEANT = ["SPOS" + f[4:] for f in ZOMBIE]   # the shotgun guy: the zombie's poses, darker (see frame's ref)
IMP = ["TROOA1", "TROOB1", "TROOC1", "TROOD1", "TROOF1", "TROOH1", "TROOI0", "TROOJ0", "TROOK0", "TROOL0", "TROOM0"]
PICKUPS = ["STIMA0", "MEDIA0", "BON1A0", "BON2A0", "CLIPA0", "AMMOA0", "SHOTA0"]   # pickup kinds 3..9
BALL = ["BAL1A0", "BAL1B0", "BAL1C0", "BAL1D0", "BAL1E0"]   # the imp's fireball: flight, then the burst
FRAMES = ZOMBIE + IMP + SERGEANT + PICKUPS + BALL
# Frame numbers in doom.c: a monster's base (0 zombie, IMP_BASE imp, SERGEANT_BASE) + walk 0..3, ATTACK, PAIN,
# DEATH..DEATH+4.
IMP_BASE, ATTACK, PAIN, DEATH = len(ZOMBIE), 4, 5, 6
SERGEANT_BASE = IMP_BASE + len(IMP)
PICKUP_BASE = SERGEANT_BASE + len(SERGEANT)
BALL_BASE = PICKUP_BASE + len(PICKUPS)


def patch(w, lum, name):
    """-> (width, height, left offset, top offset, rows of luminance or None where transparent)."""
    d = w.lump(name)
    width, height, left, top = struct.unpack("<HHhh", d[:8])
    img = [[None] * width for _ in range(height)]
    for x in range(width):
        p = struct.unpack("<I", d[8 + 4 * x:12 + 4 * x])[0]
        while d[p] != 255:
            y0, n = d[p], d[p + 1]
            for i in range(n):
                if y0 + i < height:
                    img[y0 + i][x] = lum[d[p + 3 + i]]
            p += n + 4
    return width, height, left, top, img


def stretch_range(img):
    every = sorted(v for row in img for v in row if v is not None)
    return every[len(every) // 10], every[len(every) * 19 // 20]


def frame(w, lum, name, glow=False, ref=None):
    """glow: a light source (the fireball), bright grays that full light never inks. ref: stretch over that frame's
    range instead (the shotgun guy over the zombie's: his darker uniform stays darker)."""
    width, height, left, top, img = patch(w, lum, name)
    if height > 62:                             # Freedoom's imp reaches 63 pixels: its top row goes
        img, top, height = img[height - 62:], top - (height - 62), 62
    cols, rows = (width + 1) // 2, (height + 1) // 2
    lo, hi = stretch_range(patch(w, lum, ref)[4] if ref else img)
    tex = [[None] * cols for _ in range(rows)]
    for r in range(rows):
        for c in range(cols):
            px = [img[y][x] for y in (2 * r, 2 * r + 1) for x in (2 * c, 2 * c + 1) if y < height and x < width]
            seen = [v for v in px if v is not None]
            if len(seen) >= 2:
                t = max(0.0, min(1.0, (sum(seen) / len(seen) - lo) / max(1, hi - lo)))
                tex[r][c] = min(13, 9 + int(5 * t)) if glow else min(13, int(14 * t ** STRETCH))
    opaque = lambda r, c: 0 <= r < rows and 0 <= c < cols and tex[r][c] is not None
    words = [cols, rows, left & 0xffff, top & 0xffff]
    for c in range(cols):
        nib = []
        for r in range(32):
            if not opaque(r, c):
                nib.append(15)
            elif not all(opaque(r + dr, c + dc) for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))):
                nib.append(0 if glow else 14)   # a light source gets a dark rim instead
            else:
                nib.append(tex[r][c])
        words += [sum(nib[4 * k + j] << 4 * j for j in range(4)) for k in range(8)]
    return words


def words(w):
    pal = w.lump("PLAYPAL")[:768]
    lum = [(30 * pal[3 * i] + 59 * pal[3 * i + 1] + 11 * pal[3 * i + 2]) // 100 for i in range(256)]
    out = [0] * len(FRAMES)
    for k, name in enumerate(FRAMES):
        out[k] = len(out)
        out += frame(w, lum, name, name in BALL, "POSS" + name[4:] if name in SERGEANT else None)
    return out
