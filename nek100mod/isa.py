"""Instruction set of the NEK-100 DSP control CPU (Dream SAM5xxx, P16-like, 16-bit words).

There is no public documentation; everything here is reverse engineered.
Confidence per form is listed in docs/ISA.md (C = confirmed on hardware, H = inferred from code).
Unknown encodings are kept as `.dw`, so disassemble -> assemble is always byte-identical.

Registers r0..r7, fp. Word addresses everywhere (code and data are word-addressed).
"""

R = range(8)


def is_two_words(x):
    """Instruction length rule (validated on the whole image by the round-trip test)."""
    hi, lo = x >> 12, x & 0xFF
    if hi == 0xD and (x & 0xFF00) in (0xD100, 0xD500) and lo >= 0xC8:
        return False  # d1c8..d1cf (ret family), d5c8..d5cf (epilogue)
    if hi == 0xD and (x & 0x48) == 0x48:
        return True
    if hi == 0xC and lo in (0x4C, 0x4E):
        return True
    if (x & 0xF8EF) == 0xF880:
        return True  # ld/st rN, [abs16]
    if (x & 0xF8FF) == 0xF8E7:
        return True  # long conditional branch, rel16
    return False


def decode(x, lit):
    """Return (op, args) for a known encoding, else None.

    args: registers as ints, immediates as ints, targets as ('abs', addr) / ('rel8', r) / ('rel16', r).
    """
    hi, lo = x >> 8, x & 0xFF
    if lit is None:
        if x == 0xD1CA:
            return "ret", ()
        if hi < 0x10:
            return ("cmp" if hi & 8 else "mov"), (hi & 7, lo)
        if hi < 0x20:
            return ("and" if hi & 8 else "add"), (hi & 7, lo)
        if (x & 0xF0F0) == 0x8000 and lo < 8:
            return ("cmp" if hi & 8 else "mov"), (hi & 7, ("r", lo))
        if (x & 0xF8F8) == 0x9000:
            return "add", (hi & 7, ("r", lo))
        if (x & 0xF8F8) == 0xA000:
            return "or", (hi & 7, ("r", lo))
        if (x & 0xF8FF) == 0xF098:
            return "shl", (hi & 7, 8)
        if (x & 0xF8FF) == 0xF0D8:
            return "shr", (hi & 7, 8)
        if 0xC0 <= hi < 0xD0 and (lo >> 4) in (0x9, 0xB):
            base = "r1" if lo >> 4 == 0x9 else "fp"
            return ("st" if hi & 8 else "ld"), (hi & 7, (base, lo & 0xF))
        if (x & 0xFFF8) == 0x7E00:
            return "push", (lo,)
        if hi == 0x78:
            return "jmp", (("rel8", lo - 256 if lo & 0x80 else lo),)
        if 0xE0 <= hi <= 0xE3:
            op = {0xE0: "b.e0", 0xE1: "blt", 0xE2: "beq", 0xE3: "bne"}[hi]
            return op, (("rel8", lo - 256 if lo & 0x80 else lo),)
        return None
    if x == 0xD6C8:
        return "call", (("abs", lit),)
    if x == 0xD7C8:
        return "ccall", (("abs", lit),)
    if (x & 0xF8FF) == 0xD048:
        return "li", (hi & 7, lit)
    if (x & 0xF8FF) == 0xD04A:
        return "addi", (hi & 7, lit)
    if (x & 0xF8EF) == 0xF880:
        return ("st" if x & 0x10 else "ld"), (hi & 7, ("abs", lit))
    if x == 0xC14C:
        return "push", (("imm", lit),)
    if (x & 0xF8FF) == 0xF8E7:
        return "lb%d" % (hi & 7), (("rel16", lit - 0x10000 if lit & 0x8000 else lit),)
    return None


def encode(op, args):
    """Encode a decoded form back to a list of words (inverse of decode)."""
    if op == "ret":
        return [0xD1CA]
    if op in ("mov", "cmp", "add", "and", "or"):
        d, s = args
        if isinstance(s, tuple):  # register form
            base = {"mov": 0x8000, "cmp": 0x8800, "add": 0x9000, "or": 0xA000}[op]
            return [base | d << 8 | s[1]]
        base = {"mov": 0x0000, "cmp": 0x0800, "add": 0x1000, "and": 0x1800}[op]
        return [base | d << 8 | (s & 0xFF)]
    if op in ("shl", "shr"):
        return [(0xF098 if op == "shl" else 0xF0D8) | args[0] << 8]
    if op in ("ld", "st"):
        r, m = args
        if m[0] == "abs":
            return [(0xF890 if op == "st" else 0xF880) | r << 8, m[1] & 0xFFFF]
        base = 0x90 if m[0] == "r1" else 0xB0
        return [0xC000 | (8 if op == "st" else 0) << 8 | r << 8 | base | m[1]]
    if op == "push":
        a = args[0]
        return [0xC14C, a[1] & 0xFFFF] if isinstance(a, tuple) else [0x7E00 | a]
    if op == "jmp":
        return [0x7800 | (args[0][1] & 0xFF)]
    if op in ("b.e0", "blt", "beq", "bne"):
        return [({"b.e0": 0xE0, "blt": 0xE1, "beq": 0xE2, "bne": 0xE3}[op]) << 8 | (args[0][1] & 0xFF)]
    if op in ("call", "ccall"):
        return [0xD6C8 if op == "call" else 0xD7C8, args[0][1] & 0xFFFF]
    if op in ("li", "addi"):
        return [(0xD048 if op == "li" else 0xD04A) | args[0] << 8, args[1] & 0xFFFF]
    if op.startswith("lb"):
        return [0xF8E7 | int(op[2]) << 8, args[0][1] & 0xFFFF]
    raise ValueError(op)


def size_of(op, operands_text):
    """Instruction size in words from its textual form (used by the assembler's first pass)."""
    if op in ("call", "ccall", "li", "addi") or op.startswith("lb"):
        return 2
    if op == "push":
        return 2 if operands_text.strip().startswith("#") else 1
    if op in ("ld", "st"):
        mem = operands_text[operands_text.index("["):]
        inner = mem.strip()[1:].split("]")[0].replace(" ", "")
        return 1 if inner.startswith(("r1+", "fp+")) or inner in ("r1", "fp") else 2
    return 1


# Hints for frequent words whose meaning is only guessed (shown as comments next to `.dw`).
def hint(x, lit):
    if x == 0x7D0E:
        return "prologue?"
    if x == 0xC04C:
        return "enter? #%d" % lit
    if (x & 0xFFF8) == 0xD5C8:
        return "epilogue? pop %d" % (x & 7)
    if x == 0xD0CE:
        return "br? %#06x" % lit
    if x == 0xFFFF:
        return "padding"
    return None
