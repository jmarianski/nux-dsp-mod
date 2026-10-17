"""Hand-written P16 for doom.c's arithmetic (umul32, smul32, fmul, muldiv), as __asm statements.

Registers: r1, r4, r5, r6, r7 only (the C ABI keeps r0, r2, r3). Arguments are read from each function's static
frame (NAME__f); the frame words are reused as scratch once read, so no RAM is added.
"""


def _um32(t, p):
    """r1:r7 (lo:hi) = r4 * r5, unsigned; t = a scratch RAM word. Uses r6."""
    def mid(k):
        return ["mov   r6, r7", "shl   r6, 8", "add   r1, r6", "shr   r7, 8", "cmp   r1, r6",
                f"blt   .{p}c{k}", f"jmp   .{p}n{k}", f".{p}c{k}:", "add   r7, #1", f".{p}n{k}:",
                f"ld    r6, [{t}]", "add   r6, r7", f"st    [{t}], r6"]
    return (["mov   r7, r4", "and   r7, #255", "mov   r6, r5", "and   r6, #255", "mul   r6", "mov   r1, r7",
             "mov   r7, r4", "shr   r7, 8", "mov   r6, r5", "shr   r6, 8", "mul   r6", f"st    [{t}], r7",
             "mov   r7, r4", "shr   r7, 8", "mov   r6, r5", "and   r6, #255", "mul   r6"] + mid(1)
            + ["mov   r7, r4", "and   r7, #255", "mov   r6, r5", "shr   r6, 8", "mul   r6"] + mid(2)
            + [f"ld    r7, [{t}]"])


def _abs(reg, p, k):
    """reg = |reg|; r1 counts the negatives. Uses r6, r7."""
    return ["li    r6, #0x8000", f"cmp   {reg}, r6", f"blt   .{p}a{k}", "mov   r7, #0", f"sub   r7, {reg}",
            f"mov   {reg}, r7", "add   r1, #1", f".{p}a{k}:"]


def _signed_in(f, p):
    """r4 = |a|, r5 = |b| from f+0, f+1; the count of negatives saved in f+1."""
    return ([f"ld    r4, [{f}+0]", f"ld    r5, [{f}+1]", "mov   r1, #0"] + _abs("r4", p, 1) + _abs("r5", p, 2))


WORK1 = ["ld    r6, [work]", "add   r6, #1", "st    [work], r6"]   # doom.c's frame budget, ~64 instructions a unit


def umul32():
    f = "umul32__f"
    return ([f"ld    r4, [{f}+0]", f"ld    r5, [{f}+1]"] + _um32(f + "+0", "um")
            + ["st    [prod_lo], r1", "st    [prod_hi], r7", "ret"])


def smul32():
    f = "smul32__f"
    return (_signed_in(f, "sm") + WORK1 + [f"st    [{f}+1], r1"] + _um32(f + "+0", "sm")
            + [f"ld    r6, [{f}+1]", "and   r6, #1", "cmp   r6, #0", "beq   .smp",
               "li    r6, #0xffff", "sub   r6, r7", "mov   r7, r6",          # hi = ~hi
               "cmp   r1, #0", "bne   .smz", "add   r7, #1", ".smz:",       # + (lo == 0)
               "mov   r6, #0", "sub   r6, r1", "mov   r1, r6",               # lo = -lo
               ".smp:", "st    [prod_lo], r1", "st    [prod_hi], r7", "ret"])


def fmul():
    f = "fmul__f"
    return (_signed_in(f, "fm") + WORK1 + [f"st    [{f}+1], r1"] + _um32(f + "+0", "fm")
            + ["shr   r1, 8", "shl   r7, 8", "or    r7, r1",
               f"ld    r6, [{f}+1]", "and   r6, #1", "cmp   r6, #0", "beq   .fmp",
               "mov   r6, #0", "sub   r6, r7", "mov   r7, r6", ".fmp:", "ret"])


def muldiv():
    f = "muldiv__f"
    out = [f"ld    r7, [{f}+2]", "cmp   r7, #0", "bne   .mdgo", "ret", ".mdgo:"]
    out += _signed_in(f, "md") + ["ld    r6, [work]", "add   r6, #3", "st    [work], r6"]
    out += [f"ld    r7, [{f}+2]", "li    r6, #0x8000", "cmp   r7, r6", "blt   .mdc",
            "mov   r6, #0", "sub   r6, r7", "mov   r7, r6", "add   r1, #1", ".mdc:",
            f"st    [{f}+2], r7", f"st    [{f}+1], r1"]                    # f+2 = |c|, f+1 = negatives
    out += _um32(f + "+0", "md")
    out += ["mov   r4, r7", "mov   r5, r1", f"ld    r1, [{f}+2]",           # rem:q = product, r1 = |c|
            "cmp   r4, r1", "blt   .mdok", "li    r5, #0x7fff"] + _md_sign("x") + [".mdok:"]
    for k in range(16):                                                     # rem < |c| <= 0x8000: no carry out
        out += ["mov   r6, r5", "shr   r6, 15", "shl   r4, 1", "or    r4, r6", "shl   r5, 1",
                "cmp   r4, r1", f"blt   .mds{k}", "sub   r4, r1", "add   r5, #1", f".mds{k}:"]
    out += ["li    r6, #0x8000", "cmp   r5, r6", "blt   .mdsg", "li    r5, #0x7fff", ".mdsg:"] + _md_sign("")
    return out


def _md_sign(k):
    """return r5 with muldiv's sign (frame word 1 counts the negatives)."""
    return ["ld    r6, [muldiv__f+1]", "and   r6, #1", "cmp   r6, #0", f"beq   .mdp{k}",
            "mov   r7, #0", "sub   r7, r5", "ret", f".mdp{k}:", "mov   r7, r5", "ret"]


FUNCTIONS = {"umul32": umul32, "smul32": smul32, "fmul": fmul, "muldiv": muldiv}


def insert(src):
    """Replace each /* ASM name */ marker in src by the routine as __asm statements."""
    for name, gen in FUNCTIONS.items():
        body = "".join('__asm("    %s"); ' % l if not l.startswith(".") else '__asm("%s"); ' % l for l in gen())
        marker = "/* ASM %s */" % name
        if marker not in src:
            raise ValueError("no %s in doom.c" % marker)
        src = src.replace(marker, body)
    return src
