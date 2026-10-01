"""Disassembler: firmware image + our map -> annotated assembly listing (generated locally).

The listing re-assembles to a byte-identical image (`nek100mod asm`), so it can be edited directly
for experiments. Do not redistribute generated listings: they contain the vendor's code.
"""
from . import container, isa


def iter_insns(w, ranges):
    for s, e in ranges:
        a = s
        while a < e:
            x = w[a]
            if isa.is_two_words(x):
                yield a, x, w[a + 1]
                a += 2
            else:
                yield a, x, None
                a += 1


def target_of(a, op, args):
    if op in ("call", "ccall"):
        return args[0][1]
    if op in ("jmp", "b.e0", "blt", "beq", "bne"):
        return a + 1 + args[0][1]
    if op.startswith("lb"):
        return a + 2 + args[0][1]
    return None


def format_insn(a, x, lit, fmt_target, var_name):
    """-> (text, hint). fmt_target(addr) and var_name(addr) give symbolic names."""
    d = isa.decode(x, lit)
    if d is None:
        raw = ".dw %#06x" % x if lit is None else ".dw %#06x, %#06x" % (x, lit)
        return raw, isa.hint(x, lit)
    op, args = d
    if op == "ret":
        return "ret", None
    if op in ("mov", "cmp", "add", "and", "or"):
        dst, src = args
        s = "r%d" % src[1] if isinstance(src, tuple) else "#%#x" % src
        return "%-5s r%d, %s" % (op, dst, s), None
    if op in ("shl", "shr"):
        return "%-5s r%d, %d" % (op, args[0], args[1]), None
    if op == "ldc":
        return "ldc   r%d, [r1+%d]" % args, None
    if op in ("ld", "st"):
        r, m = args
        mem = "[%s]" % (var_name(m[1]) or "%#06x" % m[1]) if m[0] == "abs" else "[%s+%d]" % m
        return ("ld    r%d, %s" % (r, mem)) if op == "ld" else ("st    %s, r%d" % (mem, r)), None
    if op == "push":
        a0 = args[0]
        return ("push  #%#x" % a0[1]) if isinstance(a0, tuple) else ("push  r%d" % a0), None
    if op in ("li", "addi"):
        r, v = args
        name = var_name(v) if r == 1 else None
        return "%-5s r%d, #%s" % (op, r, name or "%#06x" % v), None
    return "%-5s %s" % (op, fmt_target(target_of(a, op, args))), None


class Listing:
    def __init__(self, image, fwmap):
        self.w = container.words(image)
        self.map = fwmap
        self.insns = list(iter_insns(self.w, fwmap.code))
        self.dec = {a: isa.decode(x, lit) for a, x, lit in self.insns}
        starts = {a for a, _, _ in self.insns}
        named = fwmap.code_names()
        self.labels = {a: e.name for a, e in named.items() if a in starts}
        for a, x, lit in self.insns:
            d = self.dec[a]
            if d:
                t = target_of(a, *d)
                if t is not None and t in starts and t not in self.labels:
                    self.labels[t] = ("sub_%05x" if d[0] in ("call", "ccall") else "L_%05x") % t
        self.comments = {a: e.comment for a, e in named.items() if e.comment and a in starts}

    def fmt_target(self, t):
        return self.labels.get(t, "%#x" % t)

    def fmt(self, a, x, lit):
        return format_insn(a, x, lit, self.fmt_target, self.map.var_name)

    def render(self):
        out = ["; NEK-100 DSP %s — generated locally by nek100mod from your firmware file." % self.map.firmware,
               "; Contains the vendor's code: keep it for yourself, share patches instead.", ""]
        for e in self.map.by_kind("var"):
            c = ("    ; " + e.comment) if e.comment else ""
            out.append(".equ %s, %#06x%s" % (e.name, e.addr, c))
        for s, e in self.map.code:
            out += ["", ".org %#07x" % s]
            for a, x, lit in self.insns:
                if not s <= a < e:
                    continue
                if a in self.labels:
                    if a in self.comments:
                        out.append("")
                        out.append("; %s" % self.comments[a])
                    out.append("%s:" % self.labels[a])
                text, h = self.fmt(a, x, lit)
                out.append("    %-34s ; %05x%s" % (text, a, ("  " + h) if h else ""))
        return "\n".join(out) + "\n"
