"""Wall textures, flat tones and the sky from the WAD, reduced for a 1-bit LCD that dithers in screen space.

A wall texel is 4x4 Doom pixels (four map units), its brightness a 4-bit gray: the mean luminance through
PLAYPAL, stretched over the levels the map's textures use, with local contrast raised so that panel seams and
edges survive. Every column has 32 rows (128 units: vanilla wraps a column at 128 whatever the texture's
height; shorter textures repeat here instead of reading garbage). The renderer lights a gray with the sector
and the distance and compares it with a 4x4 Bayer threshold at the screen pixel, so the pattern stays put on the
screen as the view moves. Flats are one gray each (their mean), the sky is pre-dithered at 2 Doom pixels per
LCD pixel, as it moves rigidly with the view angle.

walltex table layout (16-bit words, offsets from its start):
    THR_AT     thresholds: [light 0..31][x & 3][y & 3] -> the smallest gray drawn there
    SKYANG_AT  per screen column: the sky's column offset (atan of the column, 1024 per turn)
    SKY_AT     sky: 128 columns x 4 words, 64 rows of bits (row 16 + y on screen row y)
    FLATS_AT   per sector: floor gray | ceiling gray << 4 | 256 for a sky ceiling
    then per seg three descriptor offsets (middle, upper, lower), then texture columns (8 words: 4 rows of
    4 bits each, row 4k + j in bits 4j..4j+3 of word k), then six-word descriptors:
    column base, u1, u2, top offset (map units, bottom-pegged heights folded in), width mask, anchor
"""
import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROWS = 32                                       # texel rows a column: 128 map units
BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]
THR_AT, SKYANG_AT, SKY_AT = 0, 512, 640
FLATS_AT = SKY_AT + 512
CONTRAST = 1.5                                  # local contrast boost over the 3x3 texel mean
GAMMA = 0.8                                     # gray = 16 * (luminance / 255) ** GAMMA, before the contrast
GAIN = 20                                       # light factor at full brightness: a 1-bit LCD looks darker


def threshold(light, x, y):
    """Gray g is drawn at (x, y) under light L (16 = as stored) when g * L > 16 * bayer + 8."""
    t = BAYER[y & 3][x & 3] * 16 + 8
    return t // light + 1 if light else 16


def light_factor(light, s):
    """Sector light 0..255 and wall scale s (2^19 / z) -> 0..31, 16 drawing the gray as stored. Vanilla's colormap
    choice: 4 maps darker for each light step below 15, half a map brighter for each scale unit (s / 256 here)."""
    level = min(s >> 8, 47)
    dark = (15 - (light >> 4)) * 8 - level      # in half colormaps
    dark = 0 if dark < 0 else 63 if dark > 63 else dark
    return GAIN * (64 - dark) >> 6


class Graphics:
    """Textures, flats and the sky of a WAD, as luminance."""
    def __init__(self, w):
        self.w = w
        pal = w.lump("PLAYPAL")[:768]
        self.lum = [(30 * pal[3 * i] + 59 * pal[3 * i + 1] + 11 * pal[3 * i + 2]) // 100 for i in range(256)]
        pn = w.lump("PNAMES")
        self.pnames = [pn[4 + 8 * i:12 + 8 * i].rstrip(b"\0").decode("ascii").upper()
                       for i in range(struct.unpack("<I", pn[:4])[0])]
        self.defs = {}
        for lump in ("TEXTURE1", "TEXTURE2"):
            try:
                t = w.lump(lump)
            except KeyError:
                continue
            for k in range(struct.unpack("<I", t[:4])[0]):
                o = struct.unpack("<I", t[4 + 4 * k:8 + 4 * k])[0]
                name = t[o:o + 8].rstrip(b"\0").decode("ascii").upper()
                width, height, n = struct.unpack("<HH4xH", t[o + 12:o + 22])
                patches = [struct.unpack("<hhH", t[o + 22 + 10 * i:o + 28 + 10 * i]) for i in range(n)]
                self.defs[name] = (width, height, patches)

    def patch(self, name, img, ox, oy):
        d = self.w.lump(name)
        pw, ph = struct.unpack("<HH", d[:4])
        height, width = len(img), len(img[0])
        for x in range(pw):
            p = struct.unpack("<I", d[8 + 4 * x:12 + 4 * x])[0]
            while d[p] != 255:
                top, n = d[p], d[p + 1]
                for i in range(n):
                    tx, ty = ox + x, oy + top + i
                    if 0 <= tx < width and 0 <= ty < height:
                        img[ty][tx] = self.lum[d[p + 3 + i]]
                p += n + 4

    def texture(self, name):
        """-> rows of luminance (0 where no patch covers)."""
        width, height, patches = self.defs[name]
        img = [[0] * width for _ in range(height)]
        for ox, oy, k in patches:
            self.patch(self.pnames[k], img, ox, oy)
        return img

    def flat(self, name):
        d = self.w.lump(name)
        return sum(self.lum[b] for b in d) / len(d)

    def sky(self):
        return self.texture("SKY1")


def texels(img):
    """4x4 box means: ROWS x width/4, rows wrapping at the texture's height."""
    height, width = len(img), len(img[0])
    return [[sum(img[(4 * r + j) % height][4 * c + i] for j in range(4) for i in range(4)) / 16
             for c in range(width // 4)] for r in range(ROWS)]


def grays(t, lo, hi):
    """Luminance texels -> 4-bit grays: a stretch from lo..hi, then local contrast."""
    rows, cols = len(t), len(t[0])
    g = [[16 * (v / 255) ** GAMMA for v in row] for row in t]
    out = []
    for r in range(rows):
        row = []
        for c in range(cols):
            mean = sum(g[(r + j) % rows][(c + i) % cols] for j in (-1, 0, 1) for i in (-1, 0, 1)) / 9
            v = g[r][c] + CONTRAST * (g[r][c] - mean)
            row.append(max(0, min(15, int(v))))
        out.append(row)
    return out


def flat_gray(lum, lo, hi):
    return max(0, min(15, int(16 * (lum / 255) ** GAMMA)))


def load(m, w):
    """Fill m.wall_textures {name: ROWS x cols grays}, m.flat_grays [per sector], m.sky (64 rows x 128 bits)."""
    gfx = Graphics(w)
    names = sorted({s[0] for surfaces in m.wall_surfaces.values() for s in surfaces.values()})
    raw = {name: texels(gfx.texture(name)) for name in names}
    every = sorted(v for t in raw.values() for row in t for v in row)
    lo, hi = every[len(every) // 50], every[len(every) * 49 // 50]
    m.wall_textures = {name: grays(t, lo, hi) for name, t in raw.items()}
    m.texture_heights = {name: gfx.defs[name][1] for name in names}
    flats = {}
    m.flat_grays = []
    for floor, ceiling in m.sector_flats:
        for f in (floor, ceiling):
            if f not in flats and f != "F_SKY1":
                flats[f] = flat_gray(gfx.flat(f), lo, hi)
        m.flat_grays.append(flats.get(floor, 0) | flats.get(ceiling, 0) << 4 | (256 if ceiling == "F_SKY1" else 0))
    m.sky = sky_bits(gfx.sky())


def sky_bits(img):
    """SKY1 at half resolution (128 x 64), Floyd-Steinberg dithered, stretched to its own range."""
    height, width = len(img), len(img[0])
    g = [[sum(img[(2 * r + j) % height][2 * c + i] for j in (0, 1) for i in (0, 1)) / 4 for c in range(width // 2)]
         for r in range(64)]
    flat = sorted(v for row in g for v in row)
    lo, hi = flat[len(flat) // 50], flat[len(flat) * 49 // 50]
    g = [[(v - lo) / (hi - lo) for v in row] for row in g]
    out = [[0] * (width // 2) for _ in range(64)]
    for r in range(64):
        for c in range(width // 2):
            v = g[r][c]
            out[r][c] = int(v >= 0.5)
            e = v - out[r][c]
            for dr, dc, k in ((0, 1, 7), (1, -1, 3), (1, 0, 5), (1, 1, 1)):
                if r + dr < 64 and 0 <= c + dc < width // 2:
                    g[r + dr][c + dc] += e * k / 16
    return out


def sky_angles():
    """Column x of the screen looks atan((64 - x - 0.5) / 64) left of the view: in 1024ths of a turn."""
    return [round(math.atan((63.5 - x) / 64) * 512 / math.pi) for x in range(128)]


def pack(m):
    """-> (words, {seg: offset of its three descriptor offsets}) in the layout above."""
    words = [threshold(light, x, y) for light in range(32) for x in range(4) for y in range(4)]
    words += [a & 0xffff for a in sky_angles()]
    for c in range(128):
        col = [m.sky[r][c] for r in range(64)]
        words += [sum(col[16 * k + j] << j for j in range(16)) for k in range(4)]
    assert len(words) == FLATS_AT
    words += m.flat_grays
    seg_at = len(words)
    words += [0] * (len(m.wall_surfaces) * 3)
    images = {}
    for name, t in m.wall_textures.items():
        cols = len(t[0])
        if cols & (cols - 1) or cols > 128:
            raise ValueError("texture %s: width must be a power of two up to 512" % name)
        images[name] = len(words), cols
        for c in range(cols):
            words += [sum(t[4 * k + j][c] << 4 * j for j in range(4)) for k in range(ROWS // 4)]
    offsets, descriptors = {}, {}
    for i, (k, surfaces) in enumerate(m.wall_surfaces.items()):
        at = seg_at + i * 3
        offsets[k] = at
        for n, slot in enumerate(("middle", "upper", "lower")):
            surface = surfaces.get(slot)
            if surface is None:
                continue
            if surface not in descriptors:
                name, u1, u2, yo, anchor = surface
                base, cols = images[name]
                descriptors[surface] = len(words)
                words += [base, u1 & 0xffff, u2 & 0xffff, top_offset(m, surface) & 0xffff, cols - 1, anchor]
            words[at + n] = descriptors[surface]
    if len(words) > 65535:
        raise ValueError("walltex exceeds 16-bit offsets")
    return words, offsets


def top_offset(m, surface):
    """The texture top above the anchor's height: anchors 1 and 2 are bottom-pegged (texture height added)."""
    name, _u1, _u2, yo, anchor = surface
    return yo + (m.texture_heights[name] if anchor in (1, 2) else 0)
