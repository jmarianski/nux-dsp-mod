"""Draft a new target from an existing one: find the same code in another firmware file.

Both firmware files stay on your machine; the draft only holds addresses (map entries, hook sites)
and the `expect` words the patches already need. Everything is matched by *code signature*: a window of
instruction words starting at the address, with the literal word of two-word instructions masked
(absolute addresses and imm16 differ between builds, opcodes and relative branches mostly do not).
RAM variables are carried over through those literals: if `ld r7, [0x0144]` in the old firmware is
`ld r7, [0x0150]` at the matching place in the new one, `touch` moves to 0x0150.

The result is a starting point, not a port: review every entry, re-check pools and hooks in a listing
of the new firmware, and test on the instrument.
"""
import os
import re
from collections import Counter, defaultdict

from . import container, fwmap as fwmap_mod, isa, patcher

WINDOW = 12  # instructions per signature
FUZZY_WINDOW = 64  # words compared by the fallback
FUZZY_MIN = 0.75   # fraction of equal words a fuzzy match needs
RARE = 64          # anchors occurring more often than this are not used by the fallback


def norm(x):
    """Word as compared: short branches lose their offset (it changes when code in between changes)."""
    d = isa.decode(x, 0) if not isa.is_two_words(x) else None
    return x & 0xFF00 if d and any(isinstance(t, tuple) and t[0] == "rel8" for t in d[1]) else x


def signature(w, a, n=WINDOW):
    """Normalised words from a (literal words of two-word instructions -> None), literal positions."""
    sig, lits = [], []
    while len(sig) < n and a < len(w):
        x = w[a]
        if isa.is_two_words(x) and a + 1 < len(w):
            sig += [x, None]
            lits.append(a + 1)
            a += 2
        else:
            sig.append(norm(x))
            a += 1
    return tuple(sig), lits


class Finder:
    def __init__(self, w):
        self.w = w
        self.n = [norm(x) for x in w]
        self.index = defaultdict(list)
        for a in range(len(w) - 2):
            self.index[(self.n[a], self.n[a + 1])].append(a)

    def anchors(self, sig):
        return [i for i in range(len(sig) - 1) if None not in sig[i:i + 2]]

    def score(self, sig, a):
        if a < 0 or a + len(sig) > len(self.n):
            return 0
        return sum(1 for i, v in enumerate(sig) if v is not None and self.n[a + i] == v)

    def find(self, sig):
        """Addresses whose normalised window equals sig (None: window has no anchor)."""
        an = self.anchors(sig)
        if not an:
            return None
        start = an[0]
        need = sum(v is not None for v in sig)
        return [b - start for b in self.index.get(sig[start:start + 2], []) if self.score(sig, b - start) == need]

    def fuzzy(self, sig):
        """Best approximate position: (address, fraction equal) when clearly better than the runner-up."""
        votes = Counter()
        for i in self.anchors(sig):
            hits = self.index.get(sig[i:i + 2], [])
            if len(hits) <= RARE:
                votes.update(b - i for b in hits)
        need = sum(v is not None for v in sig)
        ranked = sorted(((self.score(sig, a), a) for a, _ in votes.most_common(20)), reverse=True)
        if not ranked or not need:
            return None, 0
        best, a = ranked[0]
        second = ranked[1][0] if len(ranked) > 1 else 0
        if best >= FUZZY_MIN * need and best - second >= 0.15 * need:
            return a, best / need
        return None, best / need


def match(old_w, finder, a):
    """-> (new address or None, how: 'exact' / 'fuzzy 83%' / 'N candidates', {old literal: new literal}).

    The window grows until it is unique (short functions and prologues repeat a lot); when no window
    matches exactly, the best approximate match over FUZZY_WINDOW words is taken if it is clear."""
    hits = None
    for n in (WINDOW, 2 * WINDOW, 4 * WINDOW, 8 * WINDOW):
        sig, lits = signature(old_w, a, n)
        hits = finder.find(sig)
        if hits is not None and len(hits) <= 1:
            break
    how = "exact"
    if not hits or len(hits) != 1:
        if hits:
            return None, "%d candidates" % len(hits), {}
        sig, lits = signature(old_w, a, FUZZY_WINDOW)
        b, q = finder.fuzzy(sig)
        if b is None:
            return None, "no match (best %d%%)" % (100 * q), {}
        hits, how = [b], "fuzzy %d%%" % (100 * q)
    b = hits[0]
    return b, how, {old_w[x]: finder.w[b + (x - a)] for x in lits}


def quality(how):
    return 2.0 if how == "exact" else float(how.split()[1].rstrip("%")) / 100 if how.startswith("fuzzy") else 0


def walk(old_w, new_w, a, b, limit=2000):
    """Follow identical code from a (old) and b (new): {old literal: Counter of new literals}."""
    out = defaultdict(Counter)
    for _ in range(limit):
        if a + 1 >= len(old_w) or b + 1 >= len(new_w) or norm(old_w[a]) != norm(new_w[b]):
            break
        if isa.is_two_words(old_w[a]):
            out[old_w[a + 1]][new_w[b + 1]] += 1
            a, b = a + 2, b + 2
        else:
            a, b = a + 1, b + 1
    return out


def port(old_img, new_img, m, out_dir, new_id=None):
    """Write a draft target directory. Returns report lines."""
    old_w, new_w = container.words(old_img), container.words(new_img)
    finder = Finder(new_w)
    report, votes = [], defaultdict(Counter)
    found = {e.name: match(old_w, finder, e.addr) for e in m.by_kind("func", "label")}
    # two entries on one new address: keep the clearly better match, drop the others
    by_new = defaultdict(list)
    for name, (b, how, _) in found.items():
        if b is not None:
            by_new[b].append(name)
    for b, names in by_new.items():
        if len(names) > 1:
            names.sort(key=lambda k: quality(found[k][1]), reverse=True)
            keep = quality(found[names[0]][1]) > quality(found[names[1]][1])
            for k in names[1:] if keep else names:
                found[k] = (None, "same place as %s" % " / ".join(x for x in names if x != k), {})
    moved = {}
    for e in m.by_kind("func", "label"):
        b, n, lits = found[e.name]
        moved[e.name] = b
        report.append("%-6s %-24s %#07x -> %s" % (e.kind, e.name, e.addr,
                                                  ("%#07x" % b) + ("" if n == "exact" else "  (%s)" % n) if b is not None
                                                  else "NOT FOUND (%s)" % n))
        if b is not None:
            for o, c in walk(old_w, new_w, e.addr, b).items():
                votes[o].update(c)
    funcs = sorted((e.addr, moved[e.name]) for e in m.by_kind("func") if moved[e.name] is not None)

    def locate(a):
        """A hook site: at the same offset in its (ported) function if the code there still matches,
        otherwise wherever its own signature leads."""
        f = max((x for x in funcs if x[0] <= a), default=None)
        if f and a - f[0] < 0x400:
            c = f[1] + a - f[0]
            for start in (a, max(f[0], a - 8)):  # the code at the hook, or the code leading to it
                sig, _ = signature(old_w, start, 8)
                need = sum(v is not None for v in sig)
                if need and finder.score(sig, c - (a - start)) >= FUZZY_MIN * need:
                    return c, "in %s" % next(e.name for e in m.by_kind("func") if e.addr == f[0])
        b, how, _ = match(old_w, finder, a)
        return b, how
    var_new = {}
    for e in m.by_kind("var"):
        c = Counter()  # literals pointing anywhere into the variable vote for its new base address
        for k in range(e.size):
            for v, n in votes.get(e.addr + k, {}).items():
                c[(v - k) & 0xFFFF] += n
        var_new[e.name] = c.most_common(1)[0][0] if c else None
        report.append("var    %-24s %#07x -> %s" % (e.name, e.addr, "%#07x" % var_new[e.name] if c else
                                                    "unknown (no matched code uses it)"))
    pools = []
    for s, e in m.pools:
        b, n, _ = match(old_w, finder, s)
        pools.append((s, e, b))
        report.append("pool   %#07x..%#07x -> %s" % (s, e, "%#07x (%s; verify it is unreferenced!)" % (b, n)
                                                    if b is not None else "NOT FOUND (%s)" % n))

    new_id = new_id or os.path.basename(os.path.abspath(out_dir))
    os.makedirs(os.path.join(out_dir, "patches"), exist_ok=True)
    lines = ["# DRAFT generated by `nuxdsp port` from target %s. Every entry is unverified:" % m.id,
             "# check it in a listing of the new firmware, then remove this notice.", "",
             "firmware TODO_NAME sha256 %s" % container.sha256(new_img),
             'device   "TODO brand model"', "input    TODO_official_file.bin", "output   TODO_mod.bin",
             "defaults " + " ".join(m.defaults), "optional " + " ".join(m.optional), "",
             "# TODO: code / ramdata / glyphs ranges of the new file (old values for reference)"]
    lines += ["# code    %#07x %#07x" % r for r in m.code]
    if m.ramdata:
        lines.append("# ramdata %#07x %#07x" % m.ramdata)
    if m.glyphs:
        lines.append("# glyphs  %#07x %#07x %d" % m.glyphs)
    for s, e, b in pools:
        lines.append(("pool    %#07x %#07x     ; ported, VERIFY unreferenced" % (b, b + e - s)) if b is not None
                     else "# pool %#07x %#07x not found" % (s, e))
    lines.append("")
    for e in m.entries:
        new = moved.get(e.name) if e.kind != "var" else var_new.get(e.name)
        size = " %d" % e.size if e.kind == "var" and e.size != 1 else ""
        text = "%-5s %#07x %s%s" % (e.kind, new, e.name, size) if new is not None else \
            "# %-5s ??????? %s%s" % (e.kind, e.name, size)
        lines.append("%-38s ; (ported) %s" % (text, e.comment) if e.comment else text + "    ; (ported)")
    with open(os.path.join(out_dir, "target.map"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    for name in patcher.available(m):
        p = patcher.load(name, m)
        with open(p.path, encoding="utf-8") as f:
            src = f.read()

        def fix(mo):
            a = int(mo.group(1), 0)
            k = len(mo.group(2).split())
            b, n = locate(a)
            if b is None:
                report.append("hook   %-24s %#07x -> NOT FOUND (%s)" % (name, a, n))
                return "; TODO port: " + mo.group(0)
            old, new = old_w[a:a + k], new_w[b:b + k]
            sig, _ = signature(old_w, a, k)
            same = all(v is None or norm(new[i]) == v for i, v in enumerate(sig[:k]))
            report.append("hook   %-24s %#07x -> %#07x%s%s" % (name, a, b, "" if n == "exact" else "  (%s)" % n,
                                                              "" if same else "  WORDS DIFFER"))
            line = ".hook %#07x expect %s" % (b, " ".join("%#06x" % v for v in new))
            if not same:
                line = ("; PORT: the replaced words differ from %s (%s), check what they do here\n" %
                        (m.id, " ".join("%#06x" % v for v in old))) + line
            return line
        src = re.sub(r"^\.hook\s+(\S+)\s+expect\s+([0-9a-fA-Fx ]*[0-9a-fA-F])", fix, src, flags=re.M)
        with open(os.path.join(out_dir, "patches", name + ".patch"), "w", encoding="utf-8") as f:
            f.write(src)
    return report

