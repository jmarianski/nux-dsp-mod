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
    # |b| <= 256 (sines, small factors): |a| = ah * 256 + al, and ah * |b|, al * |b| both fit 16 bits unsigned, so
    # (|a| * |b|) >> 8 = ah * |b| + ((al * |b|) >> 8) exactly, with two multiplies.
    fast = ([f"ld    r5, [{f}+1]", "mov   r1, #0"] + _abs("r5", "fq", 1)
            + ["li    r6, #257", "cmp   r5, r6", "blt   .fqa", "jmp   .fqw", ".fqa:", f"ld    r4, [{f}+0]"]
            + _abs("r4", "fq", 2)
            + WORK1 + ["mov   r7, r4", "and   r7, #255", "mul   r5", "shr   r7, 8", "mov   r6, r7",
               "mov   r7, r4", "shr   r7, 8", "mul   r5", "add   r7, r6",
               "mov   r6, r1", "and   r6, #1", "cmp   r6, #0", "beq   .fqp",
               "mov   r6, #0", "sub   r6, r7", "mov   r7, r6", ".fqp:", "ret", ".fqw:"])
    return fast + (_signed_in(f, "fm") + WORK1 + [f"st    [{f}+1], r1"] + _um32(f + "+0", "fm")
            + ["shr   r1, 8", "shl   r7, 8", "or    r7, r1",
               f"ld    r6, [{f}+1]", "and   r6, #1", "cmp   r6, #0", "beq   .fmp",
               "mov   r6, #0", "sub   r6, r7", "mov   r7, r6", ".fmp:", "ret"])


def _um8(p):
    """r1:r7 (lo:hi) = r4 * r5 for r5 < 256: two multiplies (ah * b and al * b both fit 16 bits). Uses r6."""
    return ["mov   r7, r4", "and   r7, #255", "mul   r5", "mov   r1, r7",
            "mov   r7, r4", "shr   r7, 8", "mul   r5",
            "mov   r6, r7", "shl   r6, 8", "add   r1, r6", "shr   r7, 8", "cmp   r1, r6",
            f"blt   .{p}c", f"jmp   .{p}n", f".{p}c:", "add   r7, #1", f".{p}n:"]


def _md_steps(n, k):
    """n steps of the shift-subtract division: r4 = remainder (< r1), r5 = dividend bits on top, quotient below."""
    out = []
    for i in range(n):
        out += ["mov   r6, r5", "shr   r6, 15", "shl   r4, 1", "or    r4, r6", "shl   r5, 1",
                "cmp   r4, r1", f"blt   .md{k}s{i}", "sub   r4, r1", "add   r5, #1", f".md{k}s{i}:"]
    return out


def muldiv():
    """a * b / c toward zero, saturated to +-32767. Only the quotient bits it needs: the quotient is below 2^n
    exactly when (product >> n) < |c|, so for n = 0, 4, 8, 12 it starts there and runs n steps (E1M1's quotients
    are mostly 4..10 bits; half of the column ones are 0). A factor below 256 multiplies in two steps."""
    f = "muldiv__f"
    out = [f"ld    r7, [{f}+2]", "cmp   r7, #0", "bne   .mdgo", "ret", ".mdgo:"]
    out += _signed_in(f, "md") + ["ld    r6, [work]", "add   r6, #2", "st    [work], r6"]
    out += [f"ld    r7, [{f}+2]", "li    r6, #0x8000", "cmp   r7, r6", "blt   .mdc",
            "mov   r6, #0", "sub   r6, r7", "mov   r7, r6", "add   r1, #1", ".mdc:",
            f"st    [{f}+2], r7", f"st    [{f}+1], r1"]                    # f+2 = |c|, f+1 = negatives
    # the product: a factor below 256 goes in r5 and takes two multiplies
    out += ["li    r6, #256", "cmp   r5, r6", "blt   .mdsm", "cmp   r4, r6", "blt   .mdsw"]
    out += _um32(f + "+0", "md") + ["jmp   .mdpr", ".mdsw:", "mov   r6, r4", "mov   r4, r5", "mov   r5, r6",
                                     ".mdsm:"] + _um8("mdq") + [".mdpr:"]
    out += ["mov   r4, r7", "mov   r5, r1", f"ld    r1, [{f}+2]",           # rem:q = product, r1 = |c|
            "cmp   r4, r1", "blt   .mdok", "li    r5, #0x7fff"] + _md_sign("x") + [".mdok:"]
    # quotient 0: product < |c|
    out += ["cmp   r4, #0", "bne   .md4", "cmp   r5, r1", "blt   .mdz", "jmp   .md4", ".mdz:", "mov   r7, #0", "ret"]
    for n, nxt in ((4, ".md8"), (8, ".md12"), (12, ".md16")):
        here = ".md%d" % n
        out += [here + ":", "mov   r6, r4", f"shr   r6, {n}", "cmp   r6, #0", f"bne   {here}x",
                "mov   r6, r4", f"shl   r6, {16 - n}", "mov   r7, r5", f"shr   r7, {n}", "or    r6, r7",
                "cmp   r6, r1", f"blt   {here}go", f"{here}x:", f"ljmp  {nxt}", f"{here}go:",
                "mov   r4, r6", f"shl   r5, {16 - n}"] + _md_steps(n, n) + _md_sign(str(n))
    out += [".md16:"] + _md_steps(16, 16)                                   # rem < |c| <= 0x8000: no carry out
    out += ["li    r6, #0x8000", "cmp   r5, r6", "blt   .mdsg", "li    r5, #0x7fff", ".mdsg:"] + _md_sign("")
    return out


def _md_sign(k):
    """return r5 with muldiv's sign (frame word 1 counts the negatives)."""
    return ["ld    r6, [muldiv__f+1]", "and   r6, #1", "cmp   r6, #0", f"beq   .mdp{k}",
            "mov   r7, #0", "sub   r7, r5", "ret", f".mdp{k}:", "mov   r7, r5", "ret"]


def screen_y():
    """Fast path of screen_y(h, s) = 32 - clamp((h - eye) * s >> 13, +-1000) for |h - eye| < 256 and s < 0x8000:
    with s = sh * 256 + sl, X = |d| * s = (A + Bh) * 256 + Bl where A = |d| * sh, B = |d| * sl = Bh * 256 + Bl, all
    16-bit; floor(X / 8192) = (A + Bh) >> 5, rounded up for negative d when the low 13 bits are not zero (the C's
    arithmetic shift floors). Otherwise falls through into the C below it (the full product)."""
    f = "screen_y__f"
    return ([f"ld    r4, [{f}+1]", "li    r6, #0x8000", "cmp   r4, r6", "blt   .sya", "jmp   .syw", ".sya:",
             f"ld    r7, [{f}+0]", "ld    r6, [eye]", "sub   r7, r6", "mov   r1, #0",
             "li    r6, #0x8000", "cmp   r7, r6", "blt   .syb", "mov   r6, #0", "sub   r6, r7", "mov   r7, r6",
             "mov   r1, #1", ".syb:",
             "li    r6, #256", "cmp   r7, r6", "blt   .syc", "jmp   .syw", ".syc:", "mov   r5, r7"] + WORK1 + [
             "mov   r7, r4", "and   r7, #255", "mul   r5",                    # B = |d| * sl
             "mov   r6, r7", "and   r6, #255", f"st    [{f}+0], r6",          # Bl (h is not needed any more)
             "shr   r7, 8", "mov   r6, r7",                                   # Bh
             "mov   r7, r4", "shr   r7, 8", "mul   r5", "add   r7, r6",       # A' = |d| * sh + Bh
             "mov   r4, r7", "shr   r4, 5",                                   # m = A' >> 5
             "cmp   r1, #0", "beq   .syd",
             "and   r7, #31", f"ld    r6, [{f}+0]", "or    r7, r6", "cmp   r7, #0", "beq   .syd", "add   r4, #1",
             ".syd:", "li    r6, #1001", "cmp   r4, r6", "blt   .sye", "li    r4, #1000", ".sye:",
             "cmp   r1, #0", "beq   .syf", "mov   r7, r4", "add   r7, #32", "ret",
             ".syf:", "mov   r7, #32", "sub   r7, r4", "ret", ".syw:"])


def _tx_store():
    """framebuffer[((y - 1) >> 3) * 128 + col] |= bits (r0 = y, r2 = bits); then bits = 0, mask = 1."""
    return ["mov   r1, r0", "li    r7, #0xffff", "add   r1, r7", "shr   r1, 3", "shl   r1, 7", "ld    r6, [col]",
            "add   r1, r6", "li    r6, #framebuffer", "add   r1, r6", "ld    r6, [r1+0]", "or    r6, r2",
            "st    [r1+0], r6", "mov   r2, #0", "mov   r3, #1"]


def texels():
    """texels(lo, hi, v, z): rows lo..hi-1 of column col, texture row (v >> 8) & 31 of tex_col (4-bit grays, four
    a word) drawn where it is >= thr[y & 3]; v += z a row. A page's bits are gathered, then or-ed in once.
    r0 = y, r2 = bits, r3 = this row's bit, r4 = v, r5 = z; r0, r2, r3 are saved in the frame's locals."""
    f = "texels__f"
    out = [f"st    [{f}+4], r0", f"st    [{f}+5], r2", f"st    [{f}+6], r3",
           f"ld    r0, [{f}+0]", f"ld    r4, [{f}+2]", f"ld    r5, [{f}+3]", "mov   r2, #0", "mov   r3, #1",
           "mov   r6, r0", "and   r6, #7",
           ".txm:", "cmp   r6, #0", "beq   .txl", "shl   r3, 1", "li    r7, #0xffff", "add   r6, r7", "jmp   .txm",
           ".txl:", f"ld    r7, [{f}+1]", "cmp   r0, r7", "blt   .txp", "jmp   .txe"]
    out += [".txp:", "mov   r6, r4", "shr   r6, 10", "and   r6, #7",            # the word: row >> 2
            "li    r1, #tex_col", "add   r1, r6", "ld    r7, [r1+0]",
            "mov   r6, r4", "shr   r6, 8", "and   r6, #3",                       # the nibble: row & 3
            "cmp   r6, #2", "blt   .txa", "shr   r7, 8", ".txa:",
            "and   r6, #1", "cmp   r6, #0", "beq   .txb", "shr   r7, 4", ".txb:", "and   r7, #15",
            "mov   r6, r0", "and   r6, #3", "li    r1, #thr", "add   r1, r6", "ld    r6, [r1+0]",
            "cmp   r7, r6", "blt   .txo", "or    r2, r3", ".txo:",
            "shl   r3, 1", "add   r4, r5", "add   r0, #1",
            "mov   r6, r0", "and   r6, #7", "cmp   r6, #0", "bne   .txc"] + _tx_store()
    out += [".txc:", f"ld    r7, [{f}+1]", "cmp   r0, r7", "blt   .txp",
            "cmp   r2, #0", "beq   .txe"] + _tx_store()
    out += [".txe:", f"ld    r0, [{f}+4]", f"ld    r2, [{f}+5]", f"ld    r3, [{f}+6]", "ret"]
    return out


FUNCTIONS = {"umul32": umul32, "smul32": smul32, "fmul": fmul, "muldiv": muldiv, "screen_y": screen_y,
             "texels": texels}


def insert(src):
    """Replace each /* ASM name */ marker in src by the routine as __asm statements."""
    for name, gen in FUNCTIONS.items():
        body = "".join('__asm("    %s"); ' % l if not l.startswith(".") else '__asm("%s"); ' % l for l in gen())
        marker = "/* ASM %s */" % name
        if marker not in src:
            raise ValueError("no %s in doom.c" % marker)
        src = src.replace(marker, body)
    return src
