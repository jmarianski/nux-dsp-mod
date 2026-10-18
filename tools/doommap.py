#!/usr/bin/env python3
"""A Doom map from DOOM1.WAD, compacted for the piano, and a reference renderer with the integer math of the C
engine (firmware/doom.c), so that frames can be looked at before the C code exists and compared with it after.

Map words (all 16-bit, coordinates in map units):
    vertex   x, y
    node     x, y, dx, dy, right child, left child, right bbox[4], left bbox[4]
             child bit 15: a subsector; bbox order: top, bottom, left, right (14 words total)
    subsec   first seg, seg count, sector
    seg      v1, v2, front sector, back sector (0xffff: one-sided), flags (corner bit 0, surface offset in bits 1..15)
    sector   floor, ceiling, light
    collision x1, y1, x2, y2, front sector, back sector (0xffff: blocking)
    blockmap  cell offsets, then lists of collision-line indices terminated by 0xffff
    walltex   per-seg surface references, 32x32 tiles compressed to column ink intervals, six-word surface descriptors

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
import walltex  # noqa: E402

W, H = 128, 64
FAR = 1536                                      # far plane (view z): segs wholly beyond it are not drawn
NEAR = 17                                       # S = 2^19 / z stays a positive 16-bit number
EYE = 41
SIN = [round(256 * math.sin(i * math.pi / 128)) for i in range(65)]


def collision_grid(lines):
    """Conservative 128-unit cells. A line belongs to every cell in its bounding box.

    Extra candidates at diagonals are rejected by the runtime box/line test. Build
    our own index so collision coverage does not depend on an IWAD's BLOCKMAP quirks.
    All offsets address 16-bit words in far memory; nothing is kept in target RAM.
    """
    ox = min(min(l[0], l[2]) for l in lines) // 128 * 128
    oy = min(min(l[1], l[3]) for l in lines) // 128 * 128
    width = (max(max(l[0], l[2]) for l in lines) - ox) // 128 + 1
    height = (max(max(l[1], l[3]) for l in lines) - oy) // 128 + 1
    cells = [[] for _ in range(width * height)]
    for i, (x1, y1, x2, y2, *_rest) in enumerate(lines):
        for y in range((min(y1, y2) - oy) // 128, (max(y1, y2) - oy) // 128 + 1):
            for x in range((min(x1, x2) - ox) // 128, (max(x1, x2) - ox) // 128 + 1):
                cells[y * width + x].append(i)
    words, lists = [0] * len(cells), {}
    for k, cell in enumerate(cells):
        key = tuple(cell)
        if key not in lists:
            lists[key] = len(words)
            words.extend([*cell, 0xffff])
        words[k] = lists[key]
    if len(words) > 65535:
        raise ValueError("collision blockmap exceeds 16-bit offsets")
    return (ox, oy, width, height), words


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
        self.sector_flats = [(fp.rstrip(b"\0").decode("ascii").upper(), cp.rstrip(b"\0").decode("ascii").upper())
                             for _, _, fp, cp, _, _, _ in rec("SECTORS", "<hh8s8sHHH")]
        self.things = rec("THINGS", "<hhHHH")
        raw_nodes = rec("NODES", "<hhhh8hHH")
        self.nodes = [(x, y, dx, dy, r, l) for x, y, dx, dy, *_, r, l in raw_nodes]
        self.bounds = [tuple(n[4:12]) for n in raw_nodes]  # right then left: top, bottom, left, right
        self.segs = []
        self.wall_surfaces = {}
        for v1, v2, ang, line, side, off in rec("SEGS", "<HHhHHh"):
            ld = self.lines[line]
            front = self.sides[ld[5 + side]][5]
            other = ld[5 + (side ^ 1)]
            back = self.sides[other][5] if other != 0xFFFF and ld[2] & 4 else 0xFFFF
            sd = self.sides[ld[5 + side]]
            a, b = self.vertices[v1], self.vertices[v2]
            length = math.isqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2)
            surfaces = {}
            for slot, field, anchor in (("middle", 4, 2 if ld[2] & 16 else 0),
                                        ("upper", 2, 0 if ld[2] & 8 else 1),
                                        ("lower", 3, 0 if ld[2] & 16 else 3)):
                texture_name = sd[field].rstrip(b"\0").decode("ascii").upper()
                if texture_name != "-" and (slot != "middle" or back == 0xffff):
                    surfaces[slot] = (texture_name, sd[0] + off, sd[0] + off + length, sd[1], anchor)
            if surfaces:
                self.wall_surfaces[len(self.segs)] = surfaces
            self.segs.append((v1, v2, front, back, 1 if off == 0 else 0))
        walltex.load(self, w)
        self.subsecs = [(first, n, self.segs[first][2]) for n, first in rec("SSECTORS", "<HH")]
        self.root = len(self.nodes) - 1
        self.collision = []
        for v1, v2, flags, _special, _tag, right, left in self.lines:
            front = self.sides[right][5] if right != 0xffff else self.sides[left][5]
            back = self.sides[left][5] if left != 0xffff and flags & 4 and not flags & 1 else 0xffff
            self.collision.append((*self.vertices[v1], *self.vertices[v2], front, back))
        self.block_info, self.blockmap = collision_grid(self.collision)
        self.prepare_game(rec("SECTORS", "<hh8s8sHHH"))

    def prepare_game(self, raw_sectors):
        """Easy E1M1 demo: four monsters, persistent pickups, doors and two floor specials."""
        neighbors = [set() for _ in self.sectors]
        for line in self.lines:
            if line[5] != 0xffff and line[6] != 0xffff:
                a, b = self.sides[line[5]][5], self.sides[line[6]][5]
                neighbors[a].add(b); neighbors[b].add(a)
        dynamic = {}
        for line in self.lines:
            if line[3] == 1:
                sec = self.sides[line[6]][5]
                dynamic[sec] = (sec, self.sectors[sec][1], min(self.sectors[n][1] for n in neighbors[sec]) - 4, 0)
        for line in self.lines:
            if line[3] in (36, 88):
                for sec, raw in enumerate(raw_sectors):
                    if raw[6] == line[4]:
                        floors = [self.sectors[n][0] for n in neighbors[sec]]
                        target = max(floors) + 8 if line[3] == 36 else min(floors)
                        dynamic[sec] = (sec, self.sectors[sec][0], target, 1 if line[3] == 36 else 2)
        self.dynamics = list(dynamic.values())
        self.sector_slots = {d[0]: (i, d[3]) for i, d in enumerate(self.dynamics)}
        self.actions = []
        for i, line in enumerate(self.lines):
            action = 0
            if line[3] == 1:
                action = self.sector_slots[self.sides[line[6]][5]][0] + 1
            elif line[3] in (36, 88):
                sec = next(s for s, raw in enumerate(raw_sectors) if raw[6] == line[4])
                action = self.sector_slots[sec][0] + 1
            elif line[3] == 11:
                action = 255
            self.actions.append(action)
        # kind 1 zombie, 2 imp. State stays in RAM; original spawn records stay far.
        self.enemies = [(x, y, 2 if kind == 3001 else 1) for x, y, _a, kind, flags in self.things
                        if kind in (3001, 3004) and flags & 1 and not flags & 16]
        kinds = {2011: 3, 2012: 4, 2014: 5, 2015: 6, 2007: 7, 2048: 8, 2008: 7, 2049: 8, 2001: 9}
        self.pickups = [(x, y, kinds[kind]) for x, y, _a, kind, flags in self.things
                        if kind in kinds and flags & 1 and not flags & 16]
        if len(self.enemies) > 4 or len(self.pickups) > 64 or len(self.dynamics) > 8:
            raise ValueError("demo limits exceeded (4 enemies, 64 pickups, 8 moving sectors)")

    def start(self):
        for x, y, a, t, _ in self.things:
            if t == 1:
                return x, y, a * 256 // 360
        raise ValueError("no player start")

    def words(self):
        """-> {table: [words]} in the layout above."""
        u = lambda v: v & 0xFFFF
        flat = lambda rows: [u(v) for r in rows for v in r]
        sectors = [list(s) for s in self.sectors]
        for sec, (slot, kind) in getattr(self, "sector_slots", {}).items():
            sectors[sec][2] |= ((slot + 1) << 8) | (0x1000 if kind else 0)
        lines = [list(l) for l in self.collision]
        for i, action in enumerate(getattr(self, "actions", [])):
            lines[i][4] |= action << 8
        textures, offsets = walltex.pack(self)
        segs = [(*seg[:4], seg[4] | offsets.get(i, 0) << 1) for i, seg in enumerate(self.segs)]
        nodes = [(*node, *self.bounds[i]) for i, node in enumerate(self.nodes)]
        return {"vertices": flat(self.vertices), "nodes": flat(nodes), "subsecs": flat(self.subsecs),
                "segs": flat(segs), "sectors": flat(sectors), "collision": flat(lines), "walltex": [u(v) for v in textures],
                "blockmap": self.blockmap, "sine": SIN,
                "entities": flat(getattr(self, "enemies", []) + getattr(self, "pickups", [])),
                "dynamics": flat(getattr(self, "dynamics", []))}


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


def position_floor(m, x, y, z):
    """Player radius 16, height 56, maximum step 24; None if the position is blocked.

    Reference deliberately scans every linedef, independently of the C broad phase.
    Bounding-box crossings use exact integer cross products, including slanted walls.
    """
    ox, oy, width, height = m.block_info
    if x - 16 < ox or y - 16 < oy or x + 16 >= ox + width * 128 or y + 16 >= oy + height * 128:
        return None
    floor, ceiling, _ = m.sectors[find_sector(m, x, y)]
    for x1, y1, x2, y2, front, back in m.collision:
        if x + 16 <= min(x1, x2) or x - 16 >= max(x1, x2) or y + 16 <= min(y1, y2) or y - 16 >= max(y1, y2):
            continue
        sides = {(cy - y1) * (x2 - x1) >= (y2 - y1) * (cx - x1)
                 for cx in (x - 16, x + 16) for cy in (y - 16, y + 16)}
        if len(sides) < 2:
            continue
        if back == 0xffff:
            return None
        floor = max(floor, m.sectors[front][0], m.sectors[back][0])
        ceiling = min(ceiling, m.sectors[front][1], m.sectors[back][1])
    return floor if floor - z <= 24 and ceiling - floor >= 56 and ceiling - z >= 56 else None


class Renderer:
    """Front-to-back columns. Within a column's window: the front sector's ceiling (a gray, or the sky), its floor,
    and the wall textures, every pixel a lit 4-bit gray against a Bayer threshold (walltex)."""
    def __init__(self, m, far=FAR):
        self.m = m
        self.far = far                          # segs wholly beyond it are not drawn
        self.sky_angles = walltex.sky_angles()

    def frame(self, px, py, pa):
        m = self.m
        self.fb = [[0] * W for _ in range(H)]
        self.top, self.bot, self.open = [0] * W, [H] * W, W
        self.eye = m.sectors[find_sector(m, px, py)][0] + EYE
        self.px, self.py, self.pa, self.c, self.s = px, py, pa, isin(pa + 64), isin(pa)
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
        surfaces = m.wall_surfaces.get(k, {})
        clip1, clip2 = 0, 16384
        x1, z1 = self.view(v1)
        x2, z2 = self.view(v2)
        if z1 < NEAR and z2 < NEAR or z1 > self.far and z2 > self.far:
            return
        if z1 < NEAR:
            clip1 = muldiv(NEAR - z1, 16384, z2 - z1)
            x1 += muldiv(x2 - x1, NEAR - z1, z2 - z1); z1 = NEAR
        elif z2 < NEAR:
            clip2 -= muldiv(NEAR - z2, 16384, z1 - z2)
            x2 += muldiv(x1 - x2, NEAR - z2, z1 - z2); z2 = NEAR
        sx1 = 64 + clamp(muldiv(x1, 64, z1), -16000, 16000)
        sx2 = 64 + clamp(muldiv(x2, 64, z2), -16000, 16000)
        if sx1 >= sx2 or sx2 <= 0 or sx1 >= W:
            return
        s1, s2 = muldiv(8192, 64, z1), muldiv(8192, 64, z2)
        ff, fc, fl = m.sectors[front]
        flats = m.flat_grays[front]
        bf, bc = (m.sectors[back][:2] if back != 0xFFFF else (0, 0))
        if back != 0xFFFF and flats & m.flat_grays[back] & 256:
            fc = bc                             # sky to sky: no upper wall, the sky reaches down (vanilla)
        y = lambda h, s: 32 - clamp(mulsh(h - self.eye, s, 13), -1000, 1000)

        def texture(slot, x, s, a, b, thr):
            lo, hi = max(a, self.top[x]), min(b, self.bot[x])
            if lo >= hi:
                return
            if corner and x == sx1:
                return                          # a dark line where walls meet
            if lo == a:
                self.fb[a][x] = 1               # lit top and bottom rows: the geometry reads on 1 bit
            if hi == b:
                self.fb[b - 1][x] = 1
            surface = surfaces.get(slot)
            if not surface:
                self.tone(x, lo, hi, 8, thr)
                return
            name, u1, u2, _yo, anchor = surface
            image = m.wall_textures[name]
            du = u2 - u1
            cu1, cu2 = u1 + muldiv(du, clip1, 16384), u1 + muldiv(du, clip2, 16384)
            u = cu1 + muldiv(cu2 - cu1, muldiv(x - sx1, s2, sx2 - sx1), s)
            c = (u >> 2) & (len(image[0]) - 1)
            tex_top = (fc, bc, ff, bf)[anchor] + walltex.top_offset(m, surface)
            z = min(muldiv(8192, 64, s), 32767)  # map units per pixel * 64: 1/256 texel per pixel
            v = ((tex_top - self.eye) * 64 + (lo - 32) * z) & 0xffff
            for yy in range(lo, hi):
                if image[(v >> 8) & 31][c] >= thr[yy & 3]:
                    self.fb[yy][x] = 1
                v = (v + z) & 0xffff

        for x in range(max(sx1, 0), min(sx2, W)):
            top, bot = self.top[x], self.bot[x]
            if top >= bot:
                continue
            s = s1 + muldiv(s2 - s1, x - sx1, sx2 - sx1)
            yc, yf = y(fc, s), y(ff, s)
            light = walltex.light_factor(fl, s)
            thr = [walltex.threshold(light, x, j) for j in range(4)]
            if flats & 256:
                self.sky(x, top, min(yc, bot))
            else:
                self.tone(x, top, min(yc, bot), flats >> 4 & 15, thr)
            self.tone(x, max(yf, top), bot, flats & 15, thr)
            if back == 0xFFFF:
                texture("middle", x, s, yc, yf, thr)
                self.top[x], self.bot[x] = H, 0
                self.open -= 1
                continue
            ybc, ybf = y(bc, s), y(bf, s)
            if bc < fc:
                texture("upper", x, s, yc, ybc, thr)
            if bf > ff:
                texture("lower", x, s, ybf, yf, thr)
            nt, nb = max(top, yc, ybc), min(bot, yf, ybf)
            if bc <= bf or nt >= nb:
                nt, nb = H, 0
                self.open -= 1
            self.top[x], self.bot[x] = nt, nb

    def tone(self, x, lo, hi, g, thr):
        for yy in range(lo, hi):
            if g >= thr[yy & 3]:
                self.fb[yy][x] = 1

    def sky(self, x, lo, hi):
        u = ((self.pa * 4 + self.sky_angles[x]) & 255) >> 1
        for yy in range(lo, hi):
            if self.m.sky[(yy + 16) & 63][u]:
                self.fb[yy][x] = 1


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
