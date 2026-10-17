"""Original low-detail 32x32 material tiles selected by the map's texture names.

One texel covers four world units. Large seams and panels survive the LCD's
128x64 resolution; no full-color IWAD image is copied into these patterns.
"""


def material(name, door=False):
    if door or name.startswith(("BIGDOOR", "DOOR3", "EXITDOOR")):
        return "door"
    if name.startswith("SW"):
        return "switch"
    if name == "EXITSIGN":
        return "exit"
    if name.startswith(("COMP", "PLANET", "TEK")):
        return "computer"
    if name.startswith(("SUPPORT", "DOORTRAK", "DOORSTOP", "LITE")):
        return "ribbed"
    if name.startswith(("BROWN", "BRN", "SLAD", "NUKE")):
        return "masonry"
    if name.startswith("STEP"):
        return "step"
    return "panel"


def image(kind):
    def ink(x, y):
        if kind == "door":
            # Heavy jambs, two inset leaves, center seam and a pair of handles.
            frame = x < 2 or x >= 30 or y < 2 or y >= 30
            panels = (x in (4, 13, 18, 27) and 5 <= y <= 26) or (y in (5, 26) and (4 <= x <= 13 or 18 <= x <= 27))
            seam = 15 <= x <= 16
            handles = 21 <= y <= 23 and (11 <= x <= 13 or 18 <= x <= 20)
            return frame or panels or seam or handles
        if kind == "masonry":
            # Large staggered blocks, with a shadow below each mortar joint.
            return y % 16 in (0, 1) or (x + (16 if y >= 16 else 0)) % 32 in (0, 1)
        if kind == "ribbed":
            return x % 8 < 3 or y in (0, 31)
        if kind == "step":
            return y % 8 < 2
        if kind == "computer":
            frame = x < 2 or x > 29 or y < 3 or y > 28
            monitor = 5 <= x <= 26 and 6 <= y <= 20 and (x in (5, 6, 25, 26) or y in (6, 7, 19, 20))
            lights = y in (24, 25) and x % 6 < 3
            return frame or monitor or lights
        if kind == "switch":
            return x < 2 or x > 29 or y < 2 or y > 29 or (9 <= x <= 22 and 8 <= y <= 24 and (x in (9, 10, 21, 22) or y in (8, 9, 23, 24) or 14 <= y <= 18))
        if kind == "exit":
            # Three broad bars make the sign distinct from a door or plain wall.
            return y < 3 or y > 28 or x < 2 or x > 29 or (8 <= y <= 23 and x % 9 < 3)
        # Metal wall panels: large inset faces and a horizontal rail.
        return x in (0, 1, 30, 31) or y in (0, 1, 22, 23) or (x in (4, 27) and y in (5, 18))
    return [[int(ink(x, y)) for x in range(32)] for y in range(32)]


def pack(m):
    """Surface descriptors and vertical runs, avoiding per-pixel target loops.

    Seg flags store an offset to three descriptor offsets (middle, upper, lower).
    Descriptor: bitmap offset, u1, u2, y offset, width mask | fill<<7 | height<<8, anchor.
    Anchor: 0 front ceiling, 1 back ceiling + tile height, 2 front floor + tile
    height, 3 back floor. Coordinates are in world units, with four units/texel.
    """
    words = [0] * (1 + len(m.wall_surfaces) * 3)
    images = {}
    for name, bitmap in m.wall_textures.items():
        h, w = len(bitmap), len(bitmap[0])
        if w & (w - 1) or h > 64:
            raise ValueError("door texture exceeds column buffer or needs a non-power-of-two width")
        images[name] = len(words), w, h
        for x in range(w):
            runs = []
            y = 0
            while y < h:
                if not bitmap[y][x]:
                    y += 1; continue
                start = y
                while y < h and bitmap[y][x]:
                    y += 1
                runs.append(start | y << 8)
            if len(runs) > 8:
                raise ValueError("material column exceeds eight vertical runs")
            words.extend([len(runs), *runs, *([0] * (8 - len(runs)))])
    offsets = {}
    descriptors = {}
    for i, (k, surfaces) in enumerate(m.wall_surfaces.items()):
        at = 1 + i * 3
        offsets[k] = at
        for n, slot in enumerate(("middle", "upper", "lower")):
            surface = surfaces.get(slot)
            if surface is None:
                continue
            if surface not in descriptors:
                name, u1, u2, yo, anchor = surface
                base, w, h = images[name]
                descriptors[surface] = len(words)
                # Bit 7 enables a calm screen-space base tone; doors/signs keep a clear face.
                words.extend([base, u1, u2, yo, (w - 1) | (128 if name not in ("door", "switch", "exit") else 0) | h << 8, anchor])
            words[at + n] = descriptors[surface]
    return words, offsets
