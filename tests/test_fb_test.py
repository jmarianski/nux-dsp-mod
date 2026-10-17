"""Build fb_test into the official firmware and run its far renderer under nek100-mod's ISA simulator.

Needs ../nek100-mod and the official NEK100_DSP_V1.0.7.bin (DOOM_PIANO_FW or ../nek100-re/orig); skipped otherwise.
The firmware's copy routine (0x7638) is not simulated: the test does its job (far data -> RAM) from the image,
so the far addresses and word counts in the bank-0 code are checked separately. Our ISA model only.
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
    from nuxdsp import container, fwmap, patcher
    import fbtest

    patch = tmp_path_factory.mktemp("p") / "fb_test.patch"
    fbtest.main(str(patch))
    m = fwmap.load()
    pats = patcher.resolve_patches(DEFAULTS, m) + [patcher.load(str(patch), m)]
    out, report = patcher.build(open(FW, "rb").read(), m, pats)
    words = container.words(out)
    far = int([l for l in report if l.startswith("fb_test#2")][0].split()[2].split("..")[0], 16)
    near = int([l for l in report if l.startswith("fb_test ") and "code" in l][0].split()[2].split("..")[0], 16)
    return fbtest, words, near, far


def copies(words, near):
    """The (bank:address, RAM destination, count) of each `call 0x7638` in dp_vol, from the li's before it."""
    out, regs, a = [], {}, near
    while a < near + 0x60:
        x = words[a]
        if (x & 0xF8FF) == 0xD048:  # li rR, #imm16
            regs[(x >> 8) & 7] = words[a + 1]
            a += 2
            continue
        if x == 0xD6C8 and words[a + 1] == 0x7638:
            out.append(((regs[4] << 16) | regs[5], regs[2], regs[7]))
            a += 2
            continue
        a += 2 if x in (0xD6C8, 0xD6C9, 0xD7C8) else 1
    return out


def sim_frame(fbtest, words, far, ram):
    from nuxdsp import sim

    class Code(dict):
        def __missing__(self, k):
            return words[k] if k < len(words) else 0xFFFF

    s = sim.Sim(Code(), ram)
    s.call(far)
    return s


def test_far_copies_point_at_our_data(built):
    fbtest, words, near, far = built
    (card_src, card_dst, card_n), (data_src, data_dst, data_n) = copies(words, near)
    assert card_src > 0xFFFF and data_src > 0xFFFF  # really far
    assert (card_dst, card_n) == (FB, 1024)
    card = []
    for w in fbtest.splash.pack(fbtest.splash.test_card()):
        card += [w & 0xFF, w >> 8]
    assert list(words[card_src:card_src + 1024]) == card
    assert data_dst == fbtest.RAM["dp_tab"]
    assert data_dst + data_n == fbtest.RAM["dp_fnt"] + 3 * len(fbtest.GLYPHS)


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
        text = letter + "%05d" % ram[fbtest.RAM[var]]
        for j, ch in enumerate(text):
            g = fbtest.GLYPHS.index(ch)
            for c in range(3):
                fb[i * 128 + j * 4 + c] = font[g * 3 + c] << 1
            fb[i * 128 + j * 4 + 3] = 0
    return fb


@pytest.mark.parametrize("y", [20, 23, 56 - 1, 0 + 1])
def test_frame_renders_box_line_and_numbers(built, y):
    fbtest, words, near, far = built
    (_, _, _), (data_src, data_dst, data_n) = copies(words, near)
    R = fbtest.RAM
    ram = {data_dst + i: words[data_src + i] for i in range(data_n)}  # what 0x7638 does in dp_vol
    ram.update({R["dp_lx"]: 5, R["dp_x"]: 40, R["dp_dx"]: 1, R["dp_y"]: y, R["dp_dy"]: 0xFFFF if y > 50 else 1,
                R["dp_sec"]: 123, R["dp_d"]: 1000, R["dp_b"]: 4567, R["dp_l"]: 32000, 0x6a50: 0x8000})
    ram = {k: v for k, v in ram.items()}
    dy = -1 if y > 50 else 1
    before = dict(ram)
    before[R["dp_dy"]] = dy
    s = sim_frame(fbtest, words, far, ram)
    fb = [s.rd(FB + i) for i in range(1024)]
    assert fb == model(fbtest, before)
    assert s.rd(0x6a50) == 0x8001
    assert s.rd(FB + 1024) == 0
