"""p16cc: compile C, assemble with nek100-mod's assembler, run in its ISA simulator (our ISA model only)."""
import os
import random
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOD = os.path.join(ROOT, "..")   # nek100-mod, this directory's parent
pytestmark = pytest.mark.skipif(not os.path.isdir(MOD), reason="needs nek100-mod")
sys.path.insert(0, os.path.join(ROOT, "cc"))
sys.path.insert(0, MOD)

ORG = 0x1a280
RAM = (0x6440, 0x6500)


def test_isolated_task_leaf_does_not_share_static_scratch():
    import p16cc
    src = "int worker(int a) { int b = a + 1; return b * a; } int key(int n, int v) { return (1 << n) | v; }"
    r = p16cc.compile_c(src, isolated=("key",))
    start, size = r.frames["key"]
    for name, (other, count) in r.frames.items():
        if name != "key":
            assert start + size <= other or other + count <= start
    with pytest.raises(p16cc.CError, match="defined leaf"):
        p16cc.compile_c("int helper(int a) { return a; } int key(int a) { return helper(a); }", isolated=("key",))


def build(src, externs=None, ram=RAM):
    import p16cc
    from nuxdsp import asm
    r = p16cc.compile_c(src, ram)
    words, labels = asm.assemble(r.lines, dict(externs or {}), origin=ORG, label_prefix="t")
    return r, words, labels


class Prog:
    def __init__(self, src, externs=None, code_extra=None, ram=RAM):
        from nuxdsp import sim
        self.r, words, self.labels = build(src, externs, ram)
        words.update(code_extra or {})

        class Code(dict):
            def __missing__(self, k):
                return 0xFFFF

        self.sim = sim.Sim(Code(words), {})
        self.sim.ram = {a: 0xBEEF for a in range(ram[0], ram[1])}   # leftovers, as after power-on
        self.sim.call(self.labels["__cc_init"])

    def __call__(self, name, *args):
        base = self.r.frames[name][0]
        for k, v in enumerate(args):
            self.sim.wr(base + k, v)
        self.sim.steps = 0
        self.sim.call(self.labels[name], max_steps=2_000_000)
        return self.sim.r[7]

    def g(self, name, k=0):
        return self.sim.rd(self.r.symbols[name] + k)

    def gs(self, name, k=0):
        return s16(self.g(name, k))


def s16(v):
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


def c_op(op, a, b, unsigned):
    """C semantics of a op b for 16-bit int / unsigned (b != 0 for / and %)."""
    x, y = (a & 0xFFFF, b & 0xFFFF) if unsigned else (s16(a), s16(b))
    if op == "/":
        q = abs(x) // abs(y) * (1 if (x < 0) == (y < 0) else -1)
        return q & 0xFFFF
    if op == "%":
        q = abs(x) // abs(y) * (1 if (x < 0) == (y < 0) else -1)
        return (x - q * y) & 0xFFFF
    if op in ("<<", ">>"):
        y &= 15
        return (x << y if op == "<<" else x >> y) & 0xFFFF
    v = {"+": x + y, "-": x - y, "*": x * y, "&": x & y, "|": x | y, "^": x ^ y, "==": x == y, "!=": x != y,
         "<": x < y, ">": x > y, "<=": x <= y, ">=": x >= y, "&&": bool(x) and bool(y), "||": bool(x) or bool(y)}[op]
    return int(v) & 0xFFFF


OPS = ["+", "-", "*", "/", "%", "&", "|", "^", "<<", ">>", "==", "!=", "<", ">", "<=", ">=", "&&", "||"]
EDGE = [0, 1, 2, 3, 7, 255, 256, 1000, 0x7FFF, 0x8000, 0x8001, 0xFFFF, 0xFFFE, 0xFF00, 12345, 0xC000]


@pytest.mark.parametrize("unsigned", [False, True])
def test_operators_match_c(unsigned):
    t = "unsigned" if unsigned else "int"
    rnd = random.Random(1)
    vals = EDGE + [rnd.randrange(65536) for _ in range(10)]
    src = "\n".join("%s f%d(%s a, %s b) { return a %s b; }" % (t, n, t, t, op) for n, op in enumerate(OPS))
    p = Prog(src, ram=(0x6000, 0x6100))
    bad = []
    for n, op in enumerate(OPS):
        for a in vals:
            for b in vals:
                if op in ("/", "%") and b == 0:
                    continue
                if op in ("<<", ">>") and b > 15:
                    continue
                got, want = p("f%d" % n, a, b), c_op(op, a, b, unsigned)
                if got != want:
                    bad.append("%#x %s %#x = %#x, want %#x" % (a, op, b, got, want))
    assert not bad, "\n".join(bad[:20])


@pytest.mark.parametrize("unsigned", [False, True])
def test_operators_with_constants_match_c(unsigned):
    """Constant right operands take other paths (imm8, shifts, powers of two, multiply by shifts)."""
    t = "unsigned" if unsigned else "int"
    consts = [0, 1, 2, 3, 4, 5, 7, 8, 10, 16, 100, 127, 128, 255, 256, 1000, 1024, 0x7FFF, 0x8000, 0xFFFF]
    src, cases = [], []
    for n, op in enumerate(OPS):
        for m, c in enumerate(consts):
            if op in ("/", "%") and c == 0:
                continue
            if op in ("<<", ">>") and c > 15:
                continue
            name = "f%d_%d" % (n, m)
            src.append("%s %s(%s a) { return a %s %d; }" % (t, name, t, op, c))
            cases.append((name, op, c))
    p = Prog("\n".join(src), ram=(0x6000, 0x6800))
    bad = []
    for name, op, c in cases:
        for a in EDGE:
            got = p(name, a)
            want = c_op(op, a, c, unsigned or (c >= 0x8000 and op not in ("<<", ">>")))  # 0x8000.. is unsigned
            if got != want:
                bad.append("%#x %s %d = %#x, want %#x" % (a, op, c, got, want))
    assert not bad, "\n".join(bad[:20])


def test_unary_and_casts():
    p = Prog("""
        int neg(int a) { return -a; }
        int inv(int a) { return ~a; }
        int lnot(int a) { return !a; }
        unsigned u(int a) { return (unsigned)a >> 15; }
        int s(unsigned a) { return (int)a >> 15; }
    """)
    for a in EDGE:
        assert p("neg", a) == (-a) & 0xFFFF
        assert p("inv", a) == (~a) & 0xFFFF
        assert p("lnot", a) == int(a == 0)
        assert p("u", a) == a >> 15
        assert p("s", a) == (s16(a) >> 15) & 0xFFFF


def test_control_flow():
    p = Prog("""
        int fib(int n) { int a = 0, b = 1, t; while (n--) { t = a + b; a = b; b = t; } return a; }
        int collatz(unsigned n) { int k = 0; do { if (n & 1) n = 3 * n + 1; else n >>= 1; k++; } while (n != 1); return k; }
        int primes(int n) {
            int c = 0, i, j;
            for (i = 2; i < n; i++) {
                for (j = 2; j * j <= i; j++)
                    if (i % j == 0) break;
                if (j * j <= i) continue;
                c++;
            }
            return c;
        }
        int sw(int x) {
            int r = 0;
            switch (x) {
            case 1: r = 10; break;
            case 2: r = 20;
            case 3: r += 3; break;
            case 1000: r = -1; break;
            default: r = 99;
            }
            return r;
        }
        int tern(int a, int b) { return a > b ? a : b < 0 ? -b : b; }
    """)
    assert p("fib", 10) == 55 and p("fib", 24) == 46368
    assert p("collatz", 27) == 111
    assert p("primes", 100) == 25
    assert [p("sw", x) for x in (1, 2, 3, 4, 1000)] == [10, 23, 3, 99, 0xFFFF]
    assert p("tern", 5, 3) == 5 and p("tern", 2, 0xFFFD) == 2 and p("tern", 0xFFFB, 0xFFFD) == 3 and p("tern", 2, 4) == 4


def test_short_circuit_and_side_effects():
    p = Prog("""
        int n;
        int hit(int v) { n++; return v; }
        int a(int x, int y) { n = 0; return hit(x) && hit(y); }
        int o(int x, int y) { n = 0; return hit(x) || hit(y); }
        int post(void) { int i = 5; int j = i++; return j * 10 + i; }
        int pre(void) { int i = 5; int j = --i; return j * 10 + i; }
    """)
    assert p("a", 0, 1) == 0 and p.g("n") == 1
    assert p("a", 1, 2) == 1 and p.g("n") == 2
    assert p("o", 3, 0) == 1 and p.g("n") == 1
    assert p("o", 0, 0) == 0 and p.g("n") == 2
    assert p("post") == 56 and p("pre") == 44


def test_arrays_and_pointers():
    p = Prog("""
        int a[10];
        int m[3][4] = {{1, 2, 3, 4}, {5, 6, 7, 8}, {9, 10, 11, 12}};
        unsigned fb[16];
        int fill(int n) { int i; for (i = 0; i < n; i++) a[i] = i * i; return a[n - 1]; }
        int sum(int *p, int n) { int s = 0; while (n--) s += *p++; return s; }
        int total(void) { return sum(a, 10); }
        int diag(void) { int i, s = 0; for (i = 0; i < 3; i++) s += m[i][i + 1]; return s; }
        int rows(void) { int *r; r = m[2]; return r[3] - *m[1]; }
        int swap(int *x, int *y) { int t = *x; *x = *y; *y = t; return 0; }
        int test_swap(void) { swap(&a[1], &a[2]); return a[1] * 100 + a[2]; }
        int bits(int x, int y) { fb[(y >> 3) * 2 + (x >> 3)] |= 1 << (y & 7); return fb[(y >> 3) * 2 + (x >> 3)]; }
        int ptrdiff(void) { int *p = &a[7], *q = &a[2]; return p - q; }
        int compound(int i) { a[i] += 5; a[i] <<= 1; a[i + 1] -= a[i]; return a[i + 1]; }
    """)
    assert p("fill", 10) == 81
    assert p("total") == sum(i * i for i in range(10))
    assert p("diag") == 2 + 7 + 12
    assert p("rows") == 12 - 5
    assert p("test_swap") == 4 * 100 + 1
    assert p("bits", 9, 10) == 1 << 2 and p("bits", 9, 13) == (1 << 2) | (1 << 5)
    assert p("ptrdiff") == 5
    p("fill", 10)
    assert s16(p("compound", 3)) == 16 - (9 + 5) * 2


def test_nested_calls_keep_arguments():
    """Sibling callees share a frame: arguments computed by calls must not clobber each other."""
    p = Prog("""
        int add3(int a, int b, int c) { return a * 100 + b * 10 + c; }
        int twice(int x) { return x + x; }
        int inc(int x) { return x + 1; }
        int f(int v) { return add3(twice(v), inc(v), twice(inc(v))); }
        int deep(int v) { return inc(inc(inc(inc(v)))); }
    """)
    assert p("f", 2) == 4 * 100 + 3 * 10 + 6
    assert p("deep", 7) == 11


def test_globals_init_and_statics():
    p = Prog("""
        int x = 0x1234, y = -5, z;
        unsigned t[5] = {1, 0, 0x8000};
        int counter(void) { static int c = 10; return c++; }
    """)
    assert p.g("x") == 0x1234 and p.gs("y") == -5 and p.g("z") == 0
    assert [p.g("t", k) for k in range(5)] == [1, 0, 0x8000, 0, 0]
    assert [p("counter") for _ in range(3)] == [10, 11, 12]


def test_extern_variables_and_functions():
    """extern names resolve in the assembler; extern functions take r7, r6, r5."""
    from nuxdsp import isa
    asm_fn = {0x1f000 + k: w for k, w in enumerate(isa.encode("sub", (7, ("r", 6))) + isa.encode("sub", (7, ("r", 5)))
                                                   + isa.encode("ret", ()))}
    p = Prog("""
        extern int screen;
        extern int fb[];
        int ext(int a, int b, int c);
        int f(void) { fb[3] = screen + 1; return ext(100, 30, 7); }
    """, externs={"screen": 0x6100, "fb": 0x6200, "ext": 0x1f000}, code_extra=asm_fn)
    p.sim.wr(0x6100, 41)
    assert p("f") == 63 and p.sim.rd(0x6203) == 42


def test_long_jumps():
    """A loop body longer than a short branch reaches: the compiler picks ljmp and long conditionals."""
    body = "\n".join("x = x * 3 + %d; x ^= x >> 3;" % k for k in range(40))
    p = Prog("int f(int n) { int x = 1; while (n-- > 0) { %s } return x; }" % body)
    assert any("ljmp" in l for l in p.r.lines)
    x = 1
    for _ in range(3):
        for k in range(40):
            x = (x * 3 + k) & 0xFFFF
            x ^= s16(x) >> 3 & 0xFFFF
            x &= 0xFFFF
    assert p("f", 3) == x


def test_frames_overlay():
    p = Prog("""
        int a(int x) { int t[20]; t[0] = x; return t[0]; }
        int b(int x) { int t[20]; t[0] = x; return t[0]; }
        int top(int x) { return a(x) + b(x); }
    """)
    fa, fb, ft = p.r.frames["a"], p.r.frames["b"], p.r.frames["top"]
    assert fa[0] == fb[0] and fa[0] >= ft[0] + ft[1]
    assert p("top", 4) == 8


def test_errors():
    import p16cc
    with pytest.raises(p16cc.CError, match="recursion"):
        p16cc.compile_c("int f(int n) { return n ? f(n - 1) : 0; }")
    with pytest.raises(p16cc.CError, match="RAM"):
        p16cc.compile_c("int big[1000];")
    with pytest.raises(p16cc.CError, match="not supported"):
        p16cc.compile_c("long x;")
    with pytest.raises(p16cc.CError, match="unknown name"):
        p16cc.compile_c("int f(void) { return y; }")
