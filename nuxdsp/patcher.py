"""Patch files (.patch) and the builder that applies them to an official firmware image.

Patch file syntax (see docs/PATCHING.md):
    .patch NAME
    .title "One line description"
    .requires NAME ...                             patches that must be applied too
    .param NAME DEFAULT MIN MAX "description"     user-tunable constant, usable in expressions
    .hook ADDR expect W [W...]                     replace exactly these original words at ADDR ...
        instructions                               ... with the same number of words
    .end
    .code                                          new code, placed automatically in a free pool
        label:
        instructions                               labels starting with '.' are local to the patch
    .end
    .string "OLD" "NEW"                            replace a UI string (1 char per word); NEW may be
                                                   shorter, any Unicode character is one word
    .bitmap GLYPH                                  redraw a glyph/image of the glyph table:
        rows of '#' (pixel on) and '.'             exactly its width x height
    .end
    .bitmap GLYPH at X Y                           ... or only a rectangle of it, top left at X, Y
    .end                                           (the rest of the image is left as it is)
    .draw GLYPH at X Y W H [inverse] [bold]        clear a W x H rectangle of a glyph/image and write
        TOP "TEXT"                                 text centred in it with our pixel font (pixfont.py),
    .end                                           letters' top at row TOP of the rectangle
    .table ADDR COUNT                              strings of a pointer table (RAM word address, COUNT
        "OLD" "NEW"  or  INDEX "NEW"               pointers) laid out anew in the space they occupy:
    .end                                           NEW may be longer if others get shorter
Inside .code, an .art block becomes column data for program memory (ldc):
    .art                                           rows of '#'/'.', top row first
    .endart                                        -> one word per column, bit 0 = top row, then 0xf000
"""
import os
import re
import shlex
from dataclasses import dataclass, field

from . import asm, container, fwmap as fwmap_mod, pixfont

class PatchError(Exception):
    pass


@dataclass
class Param:
    name: str
    default: int
    lo: int
    hi: int
    desc: str


@dataclass
class Hook:
    addr: int
    expect: list
    lines: list
    line_no: int


@dataclass
class Patch:
    name: str
    title: str = ""
    params: list = field(default_factory=list)
    hooks: list = field(default_factory=list)
    code: list = field(default_factory=list)
    strings: list = field(default_factory=list)
    bitmaps: list = field(default_factory=list)
    tables: list = field(default_factory=list)
    draws: list = field(default_factory=list)
    requires: list = field(default_factory=list)
    path: str = ""


def art_words(rows, where):
    if not rows or len({len(r) for r in rows}) != 1 or len(rows) > 12:
        raise PatchError("%s: .art rows must have equal length, at most 12 rows" % where)
    return [sum(1 << y for y, r in enumerate(rows) if r[x] == "#") for x in range(len(rows[0]))] + [0xF000]


def parse(text, path="<patch>"):
    p, block, cur, art = None, None, None, None
    for n, raw in enumerate(text.splitlines(), 1):
        stripped = raw.split(";", 1)[0].strip()
        where = "%s:%d" % (path, n)
        if art is not None:
            if stripped == ".endart":
                p.code.append("    .dw " + ", ".join("%#06x" % v for v in art_words(art, where)))
                art = None
            elif stripped:
                if set(stripped) - set("#."):
                    raise PatchError("%s: .art rows use only '#' and '.'" % where)
                art.append(stripped)
            continue
        if block:
            if stripped == ".end":
                block = cur = None
                continue
            if block == "code" and stripped == ".art":
                art = []
                continue
            if block in ("table", "draw"):
                if stripped:
                    t = split_directive(raw)
                    if len(t) != 2:
                        raise PatchError('%s: entries are "OLD" "NEW", INDEX "NEW" or TOP "TEXT"' % where)
                    cur[2].append((t[0], t[1]))
                continue
            if block == "bitmap":
                if stripped:
                    if set(stripped) - set("#."):
                        raise PatchError("%s: bitmap rows use only '#' and '.'" % where)
                    cur[1].append(stripped)
                continue
            (cur.lines if block == "hook" else p.code).append(raw)
            continue
        if not stripped:
            continue
        t = split_directive(raw)
        d = t[0]
        if d == ".patch":
            p = Patch(t[1], path=path)
            continue
        if p is None:
            raise PatchError("%s: file must start with .patch NAME" % where)
        if d == ".title":
            p.title = t[1]
        elif d == ".requires":
            p.requires += t[1:]
        elif d == ".param":
            p.params.append(Param(t[1], int(t[2], 0), int(t[3], 0), int(t[4], 0), t[5] if len(t) > 5 else ""))
        elif d == ".hook":
            if len(t) < 4 or t[2] != "expect":
                raise PatchError("%s: .hook ADDR expect W [W...]" % where)
            cur = Hook(int(t[1], 0), [int(x, 0) for x in t[3:]], [], n)
            p.hooks.append(cur)
            block = "hook"
        elif d == ".code":
            block = "code"
        elif d == ".string":
            if len(t[2]) > len(t[1]):
                raise PatchError("%s: .string NEW must not be longer than OLD" % where)
            p.strings.append((t[1], t[2]))
        elif d == ".bitmap":
            at = None
            if len(t) == 5 and t[2] == "at":
                at = (int(t[3], 0), int(t[4], 0))
            elif len(t) != 2:
                raise PatchError("%s: .bitmap GLYPH [at X Y]" % where)
            cur = (int(t[1], 0), [], n, at)
            p.bitmaps.append(cur)
            block = "bitmap"
        elif d == ".draw":
            if len(t) < 7 or t[2] != "at" or set(t[7:]) - {"inverse", "bold"}:
                raise PatchError("%s: .draw GLYPH at X Y W H [inverse] [bold]" % where)
            cur = (int(t[1], 0), tuple(int(v, 0) for v in t[3:7]), [], n, "inverse" in t[7:], "bold" in t[7:])
            p.draws.append(cur)
            block = "draw"
        elif d == ".table":
            cur = (int(t[1], 0), int(t[2], 0), [], n)
            p.tables.append(cur)
            block = "table"
        else:
            raise PatchError("%s: unknown directive %r" % (where, d))
    if block:
        raise PatchError("%s: missing .end" % path)
    if p is None:
        raise PatchError("%s: empty patch" % path)
    return p


def split_directive(raw):
    lex = shlex.shlex(raw, posix=True)
    lex.commenters = ";"
    lex.whitespace_split = True
    return list(lex)


# Bundled patches live in targets/<id>/patches/. The map's `defaults` line lists the patches applied
# when none are selected, `optional` the others; together they fix the pool layout order.

def _map(m):
    return m if m is not None else fwmap_mod.load()


def load(name_or_path, m=None):
    """A patch by file path, or by name from the target's patches/ directory."""
    path = name_or_path
    if not os.path.exists(path):
        path = os.path.join(_map(m).patch_dir, name_or_path + ".patch")
    with open(path, encoding="utf-8") as f:
        return parse(f.read(), path)


def available(m=None):
    m = _map(m)
    names = sorted(f[:-6] for f in os.listdir(m.patch_dir) if f.endswith(".patch"))
    order = m.defaults + m.optional
    return [n for n in order if n in names] + [n for n in names if n not in order]


def defaults(m=None):
    m = _map(m)
    return [n for n in available(m) if n in m.defaults]


def code_size(p):
    return asm.block_size(p.code)


def allocate(patches, fwmap, layout=None):
    """Place each patch's code block in a pool. layout {name: addr} forces positions."""
    layout = dict(layout or {})
    used = [(a, a + code_size(p)) for p in patches if p.name in layout for a in [layout[p.name]]]
    for p in patches:
        n = code_size(p)
        if p.name in layout or n == 0:
            layout.setdefault(p.name, None)
            continue
        for s, e in fwmap.pools:
            a = s
            for us, ue in sorted(used):
                if us < a + n and a < ue:
                    a = max(a, ue)
            if a + n <= e:
                layout[p.name] = a
                used.append((a, a + n))
                break
        else:
            raise PatchError("no free pool space for %s (%d words)" % (p.name, n))
    for p in patches:
        a, n = layout[p.name], code_size(p)
        if n and not any(s <= a and a + n <= e for s, e in fwmap.pools):
            raise PatchError("%s: code at %#x..%#x is outside the pools" % (p.name, a, a + n))
    return layout


def canonical_layout(fwmap):
    """Pool positions of the bundled patches when all are applied, in the map's order.

    Used for every selection, so a given set of patches always produces the same image
    (CLI and web patcher agree, and unselected patches leave their space untouched).
    """
    return {k: v for k, v in allocate(resolve_patches(available(fwmap), fwmap), fwmap).items() if v is not None}


def find_string(w, fwmap, s):
    lo, hi = fwmap.ramdata
    target = [ord(c) for c in s]
    hits = [i for i in range(lo, hi - len(target)) if w[i:i + len(target)] == target]
    whole = [i for i in hits if not 0x20 <= w[i - 1] < 0x7f and w[i + len(target)] == 0]
    hits = whole or hits  # a whole string ("ON") before a part of one ("ON/OFF")
    if len(hits) != 1:
        raise PatchError("string %r found %d times (need exactly 1)" % (s, len(hits)))
    return hits[0]


def build(image, fwmap, patches, params=None, layout=None, check_sha=True, owner_out=None):
    """Apply patches to an official image. Returns (new_image, report lines).

    owner_out: optional dict, filled with {word address: patch name} for every word written.
    """
    if check_sha and container.sha256(image) != fwmap.sha256:
        raise PatchError("input is not the official %s (SHA-256 mismatch) — refusing to patch"
                         % fwmap.firmware)
    probs = container.validate(image)
    if probs:
        raise PatchError("input container invalid: " + "; ".join(probs))
    names = [p.name for p in patches]
    if len(set(names)) != len(names):
        raise PatchError("patch listed twice")
    for p in patches:
        missing = [r for r in p.requires if r not in names]
        if missing:
            raise PatchError("%s needs %s too" % (p.name, ", ".join(missing)))
    params = dict(params or {})
    syms = fwmap.symbols()
    known_params = {}
    for p in patches:
        for prm in p.params:
            if prm.name in syms or prm.name in known_params:
                raise PatchError("parameter name %r collides" % prm.name)
            v = params.pop(prm.name, prm.default)
            if not prm.lo <= v <= prm.hi:
                raise PatchError("%s must be %d..%d" % (prm.name, prm.lo, prm.hi))
            known_params[prm.name] = v
    if params:
        raise PatchError("unknown parameter(s): %s" % ", ".join(params))
    syms.update(known_params)

    if layout is None:
        bundled = canonical_layout(fwmap)
        layout = {p.name: bundled[p.name] for p in patches
                  if p.name in bundled and os.path.dirname(os.path.abspath(p.path)) == os.path.abspath(fwmap.patch_dir)}
    place = allocate(patches, fwmap, layout)
    # pass 1 over all code blocks: global labels (so patches can call each other)
    for p in patches:
        if place[p.name] is not None:
            _, labels = asm.assemble(p.code, syms, origin=place[p.name], label_prefix=p.name,
                                     labels_only=True)
            for k, v in labels.items():
                if k in syms:
                    raise PatchError("%s: label %r collides with an existing symbol" % (p.name, k))
                syms[k] = v

    w = container.words(image)
    orig = list(w)
    owner = {} if owner_out is None else owner_out
    report = []

    def put(addr, word, who):
        if addr in owner:
            raise PatchError("%s and %s both modify word %#x" % (owner[addr], who, addr))
        owner[addr] = who
        w[addr] = word

    for p in patches:
        try:
            if place[p.name] is not None:
                words, _ = asm.assemble(p.code, syms, origin=place[p.name], label_prefix=p.name,
                                        predefined_labels=True)
                for a, v in words.items():
                    put(a, v, p.name)
                report.append("%-18s code  %#07x..%#07x (%d words)" % (p.name, place[p.name],
                                                                      place[p.name] + len(words), len(words)))
            for h in p.hooks:
                cur = orig[h.addr:h.addr + len(h.expect)]
                if cur != h.expect:
                    raise PatchError("%s: hook %#x expects %s, firmware has %s"
                                     % (p.name, h.addr, fmt_words(h.expect), fmt_words(cur)))
                words, _ = asm.assemble(h.lines, syms, origin=h.addr, label_prefix=p.name)
                if sorted(words) != list(range(h.addr, h.addr + len(h.expect))):
                    raise PatchError("%s: hook %#x must assemble to exactly %d words"
                                     % (p.name, h.addr, len(h.expect)))
                for a, v in words.items():
                    put(a, v, p.name)
                report.append("%-18s hook  %#07x  %s -> %s" % (p.name, h.addr, fmt_words(h.expect),
                                                               fmt_words([words[a] for a in sorted(words)])))
            for old, new in p.strings:
                at = find_string(orig, fwmap, old)
                padded = [ord(c) for c in new] + [0] * (len(old) - len(new))
                for i, v in enumerate(padded):
                    if ord(old[i]) != v:
                        put(at + i, v, p.name)
                report.append("%-18s text  %r -> %r" % (p.name, old, new))
            for idx, rows, line, at in p.bitmaps:
                for a, v in bitmap_words(orig, fwmap, idx, rows, "%s:%d" % (p.path, line), at).items():
                    if v != orig[a]:
                        put(a, v, p.name)
                report.append("%-18s image %#04x (%dx%d%s)" % (p.name, idx, len(rows[0]), len(rows),
                                                             " at %d,%d" % at if at else ""))
            for idx, (x, y, dw, dh), lines, line, inv, bold in p.draws:
                where = "%s:%d" % (p.path, line)
                try:
                    rows = pixfont.draw(dw, dh, [(int(top, 0), txt) for top, txt in lines], inv, bold)
                except (pixfont.FontError, ValueError) as e:
                    raise PatchError("%s: %s" % (where, e))
                for a, v in bitmap_words(orig, fwmap, idx, rows, where, (x, y)).items():
                    if v != orig[a]:
                        put(a, v, p.name)
                report.append("%-18s draw  %#04x %s" % (p.name, idx, " / ".join(txt for _, txt in lines)))
            for ram, count, entries, line in p.tables:
                writes, info = table_words(orig, fwmap, ram, count, entries, "%s:%d" % (p.path, line))
                for a, v in writes.items():
                    put(a, v, p.name)
                report.append("%-18s table %#06x %s" % (p.name, ram, info))
        except asm.AsmError as e:
            raise PatchError("%s: %s" % (p.name, e))
    out = container.pack(container.fix_checksum(w))
    probs = container.validate(out)
    if probs:
        raise PatchError("internal error, output invalid: " + "; ".join(probs))
    return out, report


def glyph_info(w, fwmap, idx):
    """-> (byte offset, size in bytes, width, height) of glyph idx."""
    if not fwmap.glyphs:
        raise PatchError("map has no glyph table")
    table, _, count = fwmap.glyphs
    if not 0 <= idx < count:
        raise PatchError("glyph %#x out of range" % idx)
    a = table + 8 * idx
    return tuple(w[a + 2 * k] | w[a + 2 * k + 1] << 16 for k in range(4))


def bitmap_words(w, fwmap, idx, rows, where, at=None):
    """Encode '#'/'.' rows into the glyph's bitmap words {file address: word}.

    at=(x, y): rows cover only that rectangle; pixels outside it keep their current value."""
    off, size, width, height = glyph_info(w, fwmap, idx)
    x0, y0 = at or (0, 0)
    rw, rh = (len(rows[0]) if rows else 0), len(rows)
    if any(len(r) != rw for r in rows) or not rows:
        raise PatchError("%s: bitmap rows must have equal length" % where)
    if (at is None and (rh != height or rw != width)) or x0 + rw > width or y0 + rh > height:
        raise PatchError("%s: glyph %#x is %dx%d, bitmap is %dx%d%s"
                         % (where, idx, width, height, rw, rh, " at %d,%d" % at if at else ""))
    cb = (height + 7) // 8
    if cb * width != size:
        raise PatchError("%s: unexpected bitmap size for glyph %#x" % (where, idx))
    base = fwmap.glyphs[1]
    byte = lambda i: (w[base + (off + i) // 2] >> (8 * ((off + i) & 1))) & 0xFF
    data = bytearray(byte(i) for i in range(size))
    for y in range(rh):
        for x in range(rw):
            bit, i = 0x80 >> ((y0 + y) % 8), (x0 + x) * cb + (y0 + y) // 8
            data[i] = (data[i] | bit) if rows[y][x] == "#" else (data[i] & ~bit)
    out = {}
    for i, b in enumerate(data):
        a = base + (off + i) // 2
        cur = out.get(a, w[a])
        out[a] = (cur & 0xFF00) | b if (off + i) % 2 == 0 else (cur & 0x00FF) | b << 8
    return out


def table_words(w, fwmap, ram, count, entries, where):
    """Lay out the strings of a pointer table anew. -> ({file address: word}, report text).

    Each run of adjacent strings (each followed by its 0) is laid out within its own space. Strings
    that are also referenced from elsewhere (another pointer in the initialised data, or a code
    literal) are pinned: they keep their address, translated if the new text fits there, otherwise
    unchanged with a translated copy for the table. The others are packed into the gaps around them
    in any order (the pointers say where each one is), filling each gap as fully as possible."""
    from . import disasm
    lo, hi = fwmap.ramdata
    ptab = lo + ram
    ptrs = w[ptab:ptab + count]
    strs = {}
    for p in set(ptrs):
        a = lo + p
        e = a
        while e < hi and w[e]:
            e += 1
        if e >= hi:
            raise PatchError("%s: pointer %#x does not point to a string" % (where, p))
        strs[p] = "".join(chr(v) for v in w[a:e])
    order = sorted(strs)
    runs = []  # contiguous blocks of strings: each one is laid out on its own
    for p in order:
        if runs and runs[-1][-1] + len(strs[runs[-1][-1]]) + 1 == p:
            runs[-1].append(p)
        else:
            runs.append([p])
    for r in runs:
        if ptab < lo + r[-1] + len(strs[r[-1]]) + 1 and lo + r[0] < ptab + count:
            raise PatchError("%s: table overlaps its strings" % where)
    other = {w[a] for a in range(lo, hi) if not ptab <= a < ptab + count}
    other |= {lit for _, x, lit in disasm.iter_insns(w, fwmap.code)
              if lit is not None and x not in (0xd6c8, 0xd7c8)}  # call / ccall targets are code addresses
    pinned = {p for p in strs if p in other}
    new = {}
    for old, txt in entries:
        if re.fullmatch(r"\d+", old):
            i = int(old) - 1
            if not 0 <= i < count:
                raise PatchError("%s: entry %s outside the table (1..%d)" % (where, old, count))
            new[ptrs[i]] = txt
            continue
        hits = [p for p in strs if strs[p] == old]
        if not hits:
            raise PatchError("%s: %r is not a string of this table" % (where, old))
        for p in hits:
            new[p] = txt
    out, place, used, size = {}, {}, 0, 0
    text = lambda p: new.get(p, strs[p])
    for r in runs:
        start, end = r[0], r[-1] + len(strs[r[-1]]) + 1
        # pinned strings keep their address: with the new text if it fits before the next pinned one,
        # otherwise unchanged, and the table gets a translated copy placed like the free strings
        pins = [p for p in r if p in pinned]
        segs, cur, free, fixed = [], start, [], {}
        for j, p in enumerate(pins):
            limit = pins[j + 1] if j + 1 < len(pins) else end
            t = text(p) if p + len(text(p)) + 1 <= limit else strs[p]
            fixed[p] = t
            if t != text(p):
                free.append(p)
            segs.append((cur, p))
            cur = p + len(t) + 1
        segs.append((cur, end))
        free += [p for p in r if p not in pinned]
        free.sort()
        for k, (s0, s1) in enumerate(segs):
            # fill each gap as fully as possible (subset sum), the last one takes the rest
            sizes = [len(text(p)) + 1 for p in free]
            cap = s1 - s0
            if k == len(segs) - 1:
                pick = list(range(len(free)))
                if sum(sizes) > cap:
                    raise PatchError("%s: the strings need %d words more than their table has"
                                     % (where, sum(sizes) - cap))
            else:
                reach, hist, full = 1, [], (1 << (cap + 1)) - 1
                for n in sizes:
                    hist.append(reach)
                    reach |= (reach << n) & full
                t = reach.bit_length() - 1
                pick = []
                for i in range(len(free) - 1, -1, -1):
                    if t >= sizes[i] and hist[i] >> (t - sizes[i]) & 1 and not hist[i] >> t & 1:
                        pick.append(i)
                        t -= sizes[i]
                pick.reverse()
            cur = s0
            for i in pick:
                place[free[i]] = cur
                t = text(free[i])
                for j, c in enumerate(t):
                    out[lo + cur + j] = ord(c)
                out[lo + cur + len(t)] = 0
                cur += sizes[i]
            chosen = set(pick)
            free = [p for i, p in enumerate(free) if i not in chosen]
            for a in range(cur, s1):
                out[lo + a] = 0
            used += cur - s0
        for p, t in fixed.items():
            place.setdefault(p, p)
            for j, c in enumerate(t):
                out[lo + p + j] = ord(c)
            out[lo + p + len(t)] = 0
            used += len(t) + 1
        size += end - start
    for i, p in enumerate(ptrs):
        out[ptab + i] = place[p]
    out = {a: v for a, v in out.items() if v != w[a]}
    return out, "%d strings, %d translated, %d of %d words used, %d kept in place" % (
        len(strs), len(new), used, size, len(pinned))


def fmt_words(ws):
    return " ".join("%04x" % x for x in ws)


def resolve_patches(names, m=None):
    return [load(n, m) for n in names]


def parse_params(items):
    out = {}
    for it in items or []:
        k, _, v = it.partition("=")
        if not re.fullmatch(r"[A-Za-z_]\w*", k) or not v:
            raise PatchError("parameter must be NAME=VALUE, got %r" % it)
        out[k] = int(v, 0)
    return out
