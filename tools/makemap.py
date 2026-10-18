#!/usr/bin/env python3
"""The demo's own map, "Hangar": written here as sector outlines, built into maps/hangar.wad (a PWAD with E1M1).

Our map, not id's: it is shared with the repo like the code (Freedoom supplies textures, sprites and music). Its
features stay within what the demo plays: doors (special 1), a lift (88), a floor that lowers into a gate (36),
the exit switch (11); zombies, imps and shotgun guys; at most 6 moving sectors.

Route: start room -> door -> corridor and stairs -> hangar -> door in the west recess -> computer room -> gate
(walk into it) -> corridor -> door -> exit room, switch on its west wall. The lift in the hangar's north-east corner
leads to the balcony with the shotgun (optional).

Sectors are loops of vertices, clockwise (the sector on the right of each edge); holes go counterclockwise. Shared
edges become two-sided lines; an edge that passes through another loop's vertex is split there. The nodes come
from zdbsp (Debian/Ubuntu package zdbsp; `apt-get download zdbsp` and dpkg-deb -x work without root):

    python3 tools/makemap.py [--zdbsp PATH]      writes maps/hangar.wad
    PIANODOOM_MAP=path.wad picks another map WAD for the build (e.g. wad/DOOM1.WAD for id's E1M1).
"""
import os
import shutil
import struct
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "maps", "hangar.wad")


def rect(x1, y1, x2, y2):
    return [(x1, y1), (x1, y2), (x2, y2), (x2, y1)]


def hole(x1, y1, x2, y2):
    return list(reversed(rect(x1, y1, x2, y2)))


# name: floor, ceiling, light, floor flat, ceiling flat, wall, then optional: lower (its step faces), door (its face),
# tag, loops (default: the rect)
S = {}


def sector(name, loops, floor, ceil, light, flats, wall, lower=None, door=None, tag=0):
    S[name] = dict(loops=loops, floor=floor, ceil=ceil, light=light, flats=flats, wall=wall,
                   lower=lower or wall, door=door, tag=tag)


TECH = ("FLOOR4_8", "CEIL3_5")
sector("start", [rect(0, 0, 384, 320)], 0, 128, 176, TECH, "STARTAN3")
sector("door1", [rect(128, 320, 256, 336)], 0, 0, 160, TECH, "DOORTRAK", door="BIGDOOR2")
sector("corridor", [rect(96, 336, 288, 656)], 0, 112, 144, ("FLOOR5_1", "TLITE6_4"), "STARG3")
sector("step1", [rect(96, 656, 288, 688)], -16, 112, 144, ("STEP2", "TLITE6_4"), "STARG3", lower="STEP6")
sector("step2", [rect(96, 688, 288, 720)], -32, 112, 144, ("STEP2", "TLITE6_4"), "STARG3", lower="STEP6")
sector("hangar", [[(-384, 720), (-384, 1360), (512, 1360), (512, 1232), (640, 1232), (640, 720)],
                  hole(64, 912, 320, 1168), hole(-256, 1104, -128, 1232), hole(448, 784, 512, 848)],
       -48, 208, 160, ("FLOOR7_1", "CEIL5_1"), "TEKWALL4")
sector("skylight", [rect(64, 912, 320, 1168), hole(128, 976, 256, 1104)], -48, 256, 224, ("FLOOR7_1", "F_SKY1"),
       "TEKWALL4", lower="NUKE24")
sector("pool", [rect(128, 976, 256, 1104)], -56, 256, 224, ("NUKAGE3", "F_SKY1"), "TEKWALL4")
sector("crate", [rect(-256, 1104, -128, 1232)], 16, 208, 160, ("CRATOP1", "CEIL5_1"), "CRATE1")
sector("box", [rect(448, 784, 512, 848)], -16, 208, 160, ("CRATOP1", "CEIL5_1"), "CRATE2")
sector("lift", [rect(512, 1232, 640, 1360)], 80, 208, 176, ("STEP2", "CEIL5_1"), "SUPPORT3", tag=1)
sector("balcony", [rect(192, 1360, 640, 1488)], 80, 208, 176, ("FLOOR5_1", "CEIL5_1"), "TEKWALL4", lower="SUPPORT2")
sector("recess", [rect(-448, 1040, -384, 1168)], -48, 80, 144, TECH, "STARG3")
sector("door2", [rect(-464, 1040, -448, 1168)], -48, -48, 144, TECH, "DOORTRAK", door="BIGDOOR2")
sector("computers", [rect(-976, 912, -464, 1296), hole(-848, 1040, -720, 1104)], -48, 80, 192,
       ("FLOOR0_1", "TLITE6_5"), "COMPTALL")
sector("desk", [rect(-848, 1040, -720, 1104)], -16, 80, 192, ("FLAT14", "TLITE6_5"), "COMPUTE2")
sector("gate", [rect(-784, 1296, -656, 1312)], 80, 80, 160, TECH, "DOORTRAK", lower="BIGDOOR1", tag=2)
sector("hall", [rect(-784, 1312, -656, 1568)], -48, 80, 128, ("FLOOR5_1", "TLITE6_4"), "STARG3")
sector("door3", [rect(-784, 1568, -656, 1584)], -48, -48, 160, TECH, "DOORTRAK", door="EXITDOOR")
sector("exit", [[(-912, 1584), (-912, 1696), (-912, 1728), (-912, 1840), (-528, 1840), (-528, 1584)]],
       -48, 104, 208, ("FLOOR0_1", "TLITE6_5"), "STARTAN3")

# (two sectors) -> special, tag; (edge) -> special, texture
TRIGGERS = {("lift", "hangar"): (88, 1), ("gate", "computers"): (36, 2)}
EDGES = {((-912, 1696), (-912, 1728)): (11, "SW1EXIT")}

PLAYER = (192, 64, 90)
ALL, MEDIUM, HARD = 7, 6, 4
ZOMBIE, IMP, SERGEANT = 3004, 3001, 9
MONSTERS = [
    (192, 560, ZOMBIE, ALL, 270),
    (-128, 880, ZOMBIE, ALL, 0), (448, 1104, ZOMBIE, ALL, 180), (-288, 1296, IMP, ALL, 270),
    (0, 1296, ZOMBIE, MEDIUM, 270), (160, 800, SERGEANT, HARD, 90), (576, 1008, IMP, HARD, 180),
    (416, 1440, SERGEANT, MEDIUM, 270), (576, 1424, IMP, HARD, 270),
    (-912, 1232, IMP, ALL, 0), (-560, 960, ZOMBIE, MEDIUM, 180), (-912, 960, ZOMBIE, MEDIUM, 0),
    (-560, 1232, SERGEANT, HARD, 180),
    (-592, 1776, SERGEANT, ALL, 180), (-848, 1632, IMP, MEDIUM, 0), (-592, 1632, ZOMBIE, HARD, 180),
]
CLIP, AMMO, SHELLS, SHELLBOX, SHOTGUN = 2007, 2048, 2008, 2049, 2001
STIM, MEDIKIT, HEALTH, ARMOR = 2011, 2012, 2014, 2015
PICKUPS = [
    (96, 224, CLIP), (288, 224, ARMOR), (144, 160, CLIP), (144, 256, CLIP),
    (128, 448, HEALTH), (256, 448, HEALTH), (192, 608, HEALTH),
    (-320, 784, STIM), (576, 880, CLIP), (-256, 784, AMMO), (-320, 1296, MEDIKIT), (-192, 1296, SHELLS),
    (288, 1424, SHOTGUN), (608, 1456, SHELLBOX), (256, 1424, ARMOR), (320, 1424, ARMOR),
    (-912, 1104, AMMO), (-560, 1104, STIM), (-592, 1056, CLIP),
    (-592, 1712, MEDIKIT), (-800, 1792, CLIP),
]


def on_segment(p, a, b):
    (px, py), (ax, ay), (bx, by) = p, a, b
    if p in (a, b) or (px - ax) * (by - ay) != (py - ay) * (bx - ax):
        return False
    return min(ax, bx) <= px <= max(ax, bx) and min(ay, by) <= py <= max(ay, by)


def lumps():
    names = list(S)
    points = sorted({p for s in S.values() for loop in s["loops"] for p in loop})
    edges = {}                                  # (a, b) -> sector on its right
    for k, name in enumerate(names):
        for loop in S[name]["loops"]:
            for i, a in enumerate(loop):
                b = loop[(i + 1) % len(loop)]
                inner = sorted((p for p in points if on_segment(p, a, b)),
                               key=lambda p: (p[0] - a[0]) ** 2 + (p[1] - a[1]) ** 2)
                chain = [a] + inner + [b]
                for u, v in zip(chain, chain[1:]):
                    assert (u, v) not in edges, ("edge twice", name, u, v)
                    edges[u, v] = k
    vertex = {p: i for i, p in enumerate(points)}
    sides, lines = [], []

    def side(me, other, texture=None):
        a, b = S[names[me]], other is not None and S[names[other]]
        if b is False:
            sides.append((0, 0, b"-", b"-", (texture or a["wall"]).encode(), me))
        else:
            upper = b["door"] or a["wall"]
            sides.append((0, 0, upper.encode(), b["lower"].encode(), texture.encode() if texture else b"-", me))
        return len(sides) - 1

    done = set()
    for (a, b), right in edges.items():
        if (a, b) in done:
            continue
        left = edges.get((b, a))
        done |= {(a, b), (b, a)}
        special, tag, texture = 0, 0, None
        if (a, b) in EDGES or (b, a) in EDGES:
            special, texture = EDGES.get((a, b)) or EDGES[b, a]
        if left is None:
            door = S[names[right]]["door"]
            flags = 1 | (16 if door else 0)     # door tracks stay with the frame
            lines.append((vertex[a], vertex[b], flags, special, tag, side(right, None, texture), 0xffff))
            continue
        if S[names[right]]["door"] and not S[names[left]]["door"]:
            a, b, right, left = b, a, left, right    # the door on the left: the demo opens the back sector
        pair = names[right], names[left]
        if S[names[left]]["door"]:
            special = 1
        for (p, q), (sp, tg) in TRIGGERS.items():
            if {p, q} == set(pair):
                special, tag = sp, tg
        lines.append((vertex[a], vertex[b], 4, special, tag, side(right, left, texture), side(left, right, texture)))
    things = [(*PLAYER[:2], PLAYER[2], 1, 7)]
    things += [(x, y, angle, kind, flags) for x, y, kind, flags, angle in MONSTERS]
    things += [(x, y, 0, kind, 7) for x, y, kind in PICKUPS]
    pack = lambda fmt, rows: b"".join(struct.pack(fmt, *r) for r in rows)
    text8 = lambda s: s.encode() if isinstance(s, str) else s
    return [("E1M1", b""),
            ("THINGS", pack("<hhHHH", things)),
            ("LINEDEFS", pack("<HHHHHHH", lines)),
            ("SIDEDEFS", b"".join(struct.pack("<hh8s8s8sH", x, y, text8(u), text8(lo), text8(m), sec)
                                  for x, y, u, lo, m, sec in sides)),
            ("VERTEXES", pack("<hh", points)),
            ("SECTORS", b"".join(struct.pack("<hh8s8sHHH", s["floor"], s["ceil"], s["flats"][0].encode(),
                                             s["flats"][1].encode(), s["light"], 0, s["tag"]) for s in S.values()))]


def write_wad(path, entries):
    data, directory = b"", []
    for name, body in entries:
        directory.append((12 + len(data), len(body), name))
        data += body
    with open(path, "wb") as f:
        f.write(struct.pack("<4sII", b"PWAD", len(entries), 12 + len(data)) + data)
        for off, size, name in directory:
            f.write(struct.pack("<II8s", off, size, name.encode()))


def main(argv):
    zdbsp = argv[argv.index("--zdbsp") + 1] if "--zdbsp" in argv else shutil.which("zdbsp")
    if not zdbsp:
        sys.exit("zdbsp not found: install it or pass --zdbsp PATH")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        raw = os.path.join(tmp, "raw.wad")
        write_wad(raw, lumps())
        subprocess.run([zdbsp, "-t", "-q", "-o", OUT, raw], check=True, stdout=subprocess.DEVNULL)
    print("wrote", os.path.relpath(OUT))


if __name__ == "__main__":
    main(sys.argv[1:])
