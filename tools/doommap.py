#!/usr/bin/env python3
"""A Doom map from DOOM1.WAD, compacted for the piano, and a reference renderer with the integer math of the C
engine (firmware/doom.c), so that frames can be looked at before the C code exists and compared with it after.

Map words (all 16-bit, coordinates in map units):
    vertex   x, y
    node     x, y, dx, dy, right child, left child      (child bit 15: a subsector)
    subsec   first seg, seg count, sector
    seg      v1, v2, front sector, back sector (0xffff: one-sided), flags (bit 0: v1 is a corner of the linedef)
    sector   floor, ceiling, light

Screen: 128 x 64, focal length 64 (90 degrees across), the horizon on row 32. Angles 0..255 for a full turn,
counterclockwise from east as in Doom, sin/cos 8.8 from a 65-entry table.

Usage: doommap.py [MAP] [--png OUT.png] [x y angle]
"""
import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wad  # noqa: E402

W, H = 128, 64
NEAR = 17                                       # S = 2^19 / z stays a positive 16-bit number
EYE = 41
SIN = [round(256 * math.sin(i * math.pi / 128)) for i in range(65)]


class Map:
    def __init__(self, name="E1M1", w=None):
        w = w or wad.Wad()
        lump = lambda k: w.lump(k, after=name)
        rec = lambda k, fmt: [struct.unpack(fmt, lump(k)[i:i + struct.calcsize(fmt)])
                              for i in range(0, len(lump(k)), struct.calcsize(fmt))]
        self.vertices = rec("VERTEXES", "<hh")
        self.lines = rec("LINEDEFS", "<HHHHHHH")        # v1 v2 flags special tag right left
        self.sides = rec("SIDEDEFS", "<hh8s8s8sH")      # ... sector
        self.sectors = [(f, c, l) for f, c, _, _, l, _, _ in rec("SECTORS", "<hh8s8sHHH")]
        self.things = rec("THINGS", "<hhHHH")
        self.nodes = [(x, y, dx, dy, r, l) for x, y, dx, dy, *_, r, l in rec("NODES", "<hhhh8h HH".replace(" ", ""))]
        self.segs = []
        for v1, v2, ang, line, side, off in rec("SEGS", "<HHhHHh"):
            ld = self.lines[line]
            front = self.sides[ld[5 + side]][5]
            other = ld[5 + (side ^ 1)]
            back = self.sides[other][5] if other != 0xFFFF and ld[2] & 4 else 0xFFFF
            self.segs.append((v1, v2, front, back, 1 if off == 0 else 0))
        self.subsecs = [(first, n, self.segs[first][2]) for n, first in rec("SSECTORS", "<HH")]
        self.root = len(self.nodes) - 1

    def start(self):
        for x, y, a, t, _ in self.things:
            if t == 1:
                return x, y, a * 256 // 360
        raise ValueError("no player start")

    def words(self):
        """-> {table: [words]} in the layout above."""
        u = lambda v: v & 0xFFFF
        flat = lambda rows: [u(v) for r in rows for v in r]
        return {"vertices": flat(self.vertices), "nodes": flat(self.nodes), "subsecs": flat(self.subsecs),
                "segs": flat(self.segs), "sectors": flat(self.sectors)}


# -- the C engine's integer helpers
def trunc_div(a, b):
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def fmul(a, b):                                 # (a * b) >> 8, toward zero (ray.c's fmul)
    return trunc_div(a * b, 256)


def mulsh(a, b, sh):                            # (a * b) >> sh, 32-bit product, arithmetic shift
    return (a * b) >> sh


def muldiv(a, b, c):                            # a * b / c, 32-bit product, toward zero
    return trunc_div(a * b, c) if c else 0


def isin(a):
    a &= 255
    if a < 64:
        return SIN[a]
    if a < 128:
        return SIN[128 - a]
    if a < 192:
        return -SIN[a - 128]
    return -SIN[256 - a]


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def point_side(m, n, x, y):                     # 0 = front (right child), as R_PointOnSide
    nx, ny, ndx, ndy, _, _ = m.nodes[n]
    return 0 if (y - ny) * ndx < ndy * (x - nx) else 1


def find_sector(m, x, y):
    n = m.root
    while not n & 0x8000:
        n = m.nodes[n][4 + point_side(m, n, x, y)]
    return m.subsecs[n & 0x7FFF][2]


def shade(light, s):
    """-> 0..3: how bright a wall column is drawn (light level and distance)."""
    b = (light - 128 >> 4) + min(s >> 9, 8)
    return 3 if b >= 10 else 2 if b >= 6 else 1 if b >= 3 else 0


PATTERN = [lambda x, y: x % 4 == 0, lambda x, y: x % 2 == 0, lambda x, y: x % 4 != 0,   # vertical stripes:
           lambda x, y: True]                                                           # calmer than dots


class Renderer:
    def __init__(self, m):
        self.m = m

    def frame(self, px, py, pa):
        m = self.m
        self.fb = [[0] * W for _ in range(H)]
        self.top, self.bot, self.open = [0] * W, [H] * W, W
        self.eye = m.sectors[find_sector(m, px, py)][0] + EYE
        self.px, self.py, self.c, self.s = px, py, isin(pa + 64), isin(pa)
        stack = [m.root]
        self.visited = 0
        while stack and self.open:
            n = stack.pop()
            if n & 0x8000:
                first, cnt, _ = m.subsecs[n & 0x7FFF]
                for k in range(first, first + cnt):
                    self.seg(k)
                continue
            side = point_side(m, n, px, py)
            stack.append(m.nodes[n][4 + (side ^ 1)])
            stack.append(m.nodes[n][4 + side])
            self.visited += 1
        return self.fb

    def view(self, v):
        dx, dy = self.m.vertices[v][0] - self.px, self.m.vertices[v][1] - self.py
        return fmul(dx, self.s) - fmul(dy, self.c), fmul(dx, self.c) + fmul(dy, self.s)   # x right, z ahead

    def seg(self, k):
        m = self.m
        v1, v2, front, back, corner = m.segs[k]
        x1, z1 = self.view(v1)
        x2, z2 = self.view(v2)
        if z1 < NEAR and z2 < NEAR:
            return
        if z1 < NEAR:
            x1 += muldiv(x2 - x1, NEAR - z1, z2 - z1); z1 = NEAR
        elif z2 < NEAR:
            x2 += muldiv(x1 - x2, NEAR - z2, z1 - z2); z2 = NEAR
        sx1 = 64 + clamp(muldiv(x1, 64, z1), -16000, 16000)
        sx2 = 64 + clamp(muldiv(x2, 64, z2), -16000, 16000)
        if sx1 >= sx2 or sx2 <= 0 or sx1 >= W:
            return
        s1, s2 = muldiv(8192, 64, z1), muldiv(8192, 64, z2)
        ff, fc, fl = m.sectors[front]
        bf, bc = (m.sectors[back][:2] if back != 0xFFFF else (0, 0))
        y = lambda h, s: 32 - clamp(mulsh(h - self.eye, s, 13), -1000, 1000)
        for x in range(max(sx1, 0), min(sx2, W)):
            top, bot = self.top[x], self.bot[x]
            if top >= bot:
                continue
            s = s1 + muldiv(s2 - s1, x - sx1, sx2 - sx1)
            yc, yf = y(fc, s), y(ff, s)
            sh = shade(fl, s)
            edge = corner and x == sx1
            if back == 0xFFFF:
                self.wall(x, yc, yf, top, bot, sh, edge)
                self.top[x], self.bot[x] = H, 0
                self.open -= 1
                continue
            ybc, ybf = y(bc, s), y(bf, s)
            if bc < fc:
                self.wall(x, yc, ybc, top, bot, sh, edge)
            if bf > ff:
                self.wall(x, ybf, yf, top, bot, sh, edge)
            nt, nb = max(top, yc, ybc), min(bot, yf, ybf)
            if bc <= bf or nt >= nb:
                nt, nb = H, 0
                self.open -= 1
            self.top[x], self.bot[x] = nt, nb

    def wall(self, x, a, b, top, bot, sh, edge):
        """Rows a..b-1 of column x, within the window top..bot-1: edges solid, inside the pattern."""
        lo, hi = max(a, top), min(b, bot)
        if edge:
            return                              # a black line where walls meet
        for y in range(lo, hi):
            if y == a or y == b - 1 or PATTERN[sh](x, y):
                self.fb[y][x] = 1


def png(fb, path, scale=4):
    from PIL import Image
    img = Image.new("1", (W * scale, H * scale))
    px = img.load()
    for y in range(H):
        for x in range(W):
            if fb[y][x]:
                for dy in range(scale):
                    for dx in range(scale):
                        px[x * scale + dx, y * scale + dy] = 1
    img.save(path)


if __name__ == "__main__":
    args = sys.argv[1:]
    out = None
    if "--png" in args:
        i = args.index("--png")
        out = args[i + 1]
        del args[i:i + 2]
    name = args.pop(0) if args and args[0].startswith("E") else "E1M1"
    m = Map(name)
    pos = tuple(int(a) for a in args) if len(args) == 3 else m.start()
    r = Renderer(m)
    fb = r.frame(*pos)
    sizes = {k: len(v) for k, v in m.words().items()}
    print(name, "start", m.start(), "words", sizes, "total", sum(sizes.values()), "nodes visited", r.visited)
    if out:
        png(fb, out)
    else:
        print("\n".join("".join("#" if c else "." for c in row) for row in fb))
