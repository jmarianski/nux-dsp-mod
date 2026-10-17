"""Build fb_test into the official firmware and run its far renderer under nek100-mod's ISA simulator.

Needs ../nek100-mod and the official NEK100_DSP_V1.0.7.bin (DOOM_PIANO_FW or ../nek100-re/orig); skipped otherwise.
The firmware's copy routine (0x7638) is not simulated: the call that copies the card is checked word for word
against init_all's (0x4928). The font and tables come from simulating dp_init. Our ISA model only.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOD = os.path.join(ROOT, "..", "nek100-mod")
FW = os.environ.get("DOOM_PIANO_FW", os.path.join(ROOT, "..", "nek100-re", "orig", "NEK100_DSP_V1.0.7.bin"))
pytestmark = pytest.mark.skipif(not (os.path.isdir(MOD) and os.path.exists(FW)), reason="needs nek100-mod and firmware")

DEFAULTS = "boot_preset touch_off sustain_in_preset version_tag octave_per_part extra_menu".split()
FB = 0x662a


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    sys.path.insert(0, MOD)
    sys.path.insert(0, os.path.join(ROOT, "firmware"))
    from nuxdsp import asm, container, fwmap, patcher
    import fbtest

    patch = tmp_path_factory.mktemp("p") / "fb_test.patch"
    fbtest.main(str(patch))
    m = fwmap.load()
    pats = patcher.resolve_patches(DEFAULTS, m) + [patcher.load(str(patch), m)]
    out, report = patcher.build(open(FW, "rb").read(), m, pats)
    words = container.words(out)
    far = int([l for l in report if l.startswith("fb_test#2")][0].split()[2].split("..")[0], 16)
    near = int([l for l in report if l.startswith("fb_test ") and "code" in l][0].split()[2].split("..")[0], 16)
    syms = {}
    for key, lines, _ in patcher.code_blocks(pats[-1]):
        syms.update(asm.assemble(lines, m.symbols(),
                                 origin=near if key == "fb_test" else far, label_prefix="fb_test", labels_only=True)[1])
    assert syms["dp_frame"] == far
    return fbtest, words, syms


class Watch(dict):
    """RAM that remembers every address written."""
    def __init__(self, *a):
        super().__init__(*a)
        self.written = set()

    def __setitem__(self, k, v):
        self.written.add(k)
        super().__setitem__(k, v)


def allowed(fbtest, a):
    return FB <= a < FB + 1024 or a == 0x6a50 or fbtest.RAM["dp_on"] <= a < fbtest.RAM["dp_tab"]


def sim_call(words, addr, ram):
    from nuxdsp import sim

    class Code(dict):
        def __missing__(self, k):
            return words[k] if k < len(words) else 0xFFFF

    s = sim.Sim(Code(), {})
    s.ram = ram  # Sim copies its argument; keep ours (Watch) to see every write
    s.call(addr)
    return s


def test_card_copy_is_init_alls(built):
    """dp_cpcard = 0x4928 with our pointer, destination and count; the card is at that pointer."""
    fbtest, words, syms = built
    from nuxdsp import container
    w0 = container.words(open(FW, "rb").read())
    a, card = syms["dp_cpcard"], syms["dp_card"]
    ours, fw = list(words[a:a + 20]), list(w0[0x4928:0x4941])
    same = lambda o, f: ours[o[0]:o[1]] == fw[f[0]:f[1]]
    assert same((0, 2), (0, 2))                                   # enter #4
    assert ours[2:4] == [0xf8d0 | card >> 16, card & 0xffff] and fw[2:4] == [0xf8d1, 0x2cf7]  # li32 L0, program ptr
    assert same((4, 8), (4, 8))                                   # st [fp-1], r0; st [fp-2], r1
    assert ours[8:10] == [0xd048, FB] and fw[8:11] == [0xd148, 0x3a2a, 0x8001]  # r0 = RAM destination
    assert same((10, 11), (11, 12))                               # mov r1, x9
    assert ours[11:13] == [0xd748, 1024] and fw[16:18] == [0xd748, 0x2c00]       # r7 = count
    assert same((13, 20), (18, 25))                               # ld32 L2,[fp-2]; fix32 L2; mov32 L1,L0; call; ret_pop
    near = syms["dp_vol"]
    calls = [words[i] for i in range(near, a - 1) if words[i + 1] == a]
    assert calls == [0xd7c8]  # ccall, as every call of an enter/ret_pop function in the firmware (call crashed)
    card_words = []
    for x in fbtest.splash.pack(fbtest.splash.test_card()):
        card_words += [x & 0xFF, x >> 8]
    assert list(words[card:card + 1024]) == card_words


def test_init_writes_tables_and_font(built):
    fbtest, words, syms = built
    s = sim_call(words, syms["dp_init"], Watch({}))
    R = fbtest.RAM
    tab, div = fbtest.table_words()
    assert [s.rd(R["dp_tab"] + i) for i in range(len(tab))] == tab
    assert [s.rd(R["dp_div"] + i) for i in range(len(div))] == div
    font = fbtest.font_words()
    assert [s.rd(R["dp_fnt"] + i) for i in range(len(font))] == font
    assert all(R["dp_tab"] <= a < R["dp_fnt"] + len(font) for a in s.ram.written)


def model(fbtest, ram):
    """What one frame should look like, from the state before it."""
    fb = [0] * 1024
    lx = (ram[fbtest.RAM["dp_lx"]] + 1) & 127
    for p in range(8):
        fb[p * 128 + lx] = 0xFF
    x = ram[fbtest.RAM["dp_x"]] + ram[fbtest.RAM["dp_dx"]]
    y = ram[fbtest.RAM["dp_y"]] + ram[fbtest.RAM["dp_dy"]]
    for c in range(8):
        for r in range(8):
            yy = y + r
            fb[(yy >> 3) * 128 + x + c] |= 1 << (yy & 7)
    font = fbtest.font_words()
    for i, (letter, var) in enumerate(fbtest.LINES):
        text = letter + "%05d" % ram.get(fbtest.address(var), 0)
        for j, ch in enumerate(text):
            g = fbtest.GLYPHS.index(ch)
            for c in range(3):
                fb[i * 128 + j * 4 + c] = font[g * 3 + c] << 1
            fb[i * 128 + j * 4 + 3] = 0
    return fb


@pytest.mark.parametrize("y", [20, 23, 56 - 1, 0 + 1])
def test_frame_renders_box_line_and_numbers(built, y):
    fbtest, words, syms = built
    R = fbtest.RAM
    ram = dict(sim_call(words, syms["dp_init"], {}).ram)
    ram.update({R["dp_lx"]: 5, R["dp_x"]: 40, R["dp_dx"]: 1, R["dp_y"]: y, R["dp_dy"]: 0xFFFF if y > 50 else 1,
                R["dp_sec"]: 123, R["dp_d"]: 1000, R["dp_b"]: 4567, R["dp_l"]: 32000, 0x6a50: 0x8000})
    ram = {k: v for k, v in ram.items()}
    dy = -1 if y > 50 else 1
    before = dict(ram)
    before[R["dp_dy"]] = dy
    s = sim_call(words, syms["dp_frame"], Watch(ram))
    fb = [s.rd(FB + i) for i in range(1024)]
    assert all(allowed(fbtest, a) for a in s.ram.written)
    assert fb == model(fbtest, before)
    assert s.rd(0x6a50) == 0x8001
    assert s.rd(FB + 1024) == 0


def test_frame_terminates_on_power_on_leftovers(built):
    """init_all fills RAM 0x632a..0x6629 with leftovers of the ramdata copy (0x2c00 words from 0x12cf7 to
    0x3a2a); the first build hung on them. The renderer must finish whatever dp_* holds."""
    fbtest, words, syms = built
    orig = open(FW, "rb").read()
    from nuxdsp import container
    w0 = container.words(orig)
    ram = {a: w0[0x12cf7 + a - 0x3a2a] for a in range(0x6500, 0x6600)}
    ram[0x6a50] = 0
    s = sim_call(words, syms["dp_frame"], Watch(ram))
    assert s.steps < 100000
    bad = sorted(a for a in s.ram.written if not allowed(fbtest, a))
    assert not bad, "writes outside the framebuffer and dp_*: " + " ".join("%#x" % a for a in bad[:8])
