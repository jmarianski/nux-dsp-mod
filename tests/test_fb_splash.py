"""Build fb_splash into the official firmware and run its code under nek100-mod's ISA simulator.

Needs ../nek100-mod and the official NEK100_DSP_V1.0.7.bin (DOOM_PIANO_FW or ../nek100-re/orig); skipped otherwise.
Checks our logic against our ISA model only, not the device.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOD = os.path.join(ROOT, "..", "nek100-mod")
FW = os.environ.get("DOOM_PIANO_FW", os.path.join(ROOT, "..", "nek100-re", "orig", "NEK100_DSP_V1.0.7.bin"))
pytestmark = pytest.mark.skipif(not (os.path.isdir(MOD) and os.path.exists(FW)), reason="needs nek100-mod and firmware")

DEFAULTS = "boot_preset touch_off sustain_in_preset version_tag octave_per_part extra_menu".split()


def test_draw_fills_framebuffer_and_requests_refresh(tmp_path):
    sys.path.insert(0, MOD)
    sys.path.insert(0, os.path.join(ROOT, "firmware"))
    from nuxdsp import container, fwmap, patcher, sim
    import splash

    patch = tmp_path / "fb_splash.patch"
    splash.main(str(patch))
    m = fwmap.load()
    pats = patcher.resolve_patches(DEFAULTS, m) + [patcher.load(str(patch), m)]
    out, report = patcher.build(open(FW, "rb").read(), m, pats)
    words = container.words(out)
    hook = [l for l in report if "fb_splash" in l and "hook" in l][0]
    entry = int(hook.split()[-1], 16)  # d6c8 XXXX: call target

    class Code(dict):
        def __missing__(self, k):
            return words[k] if k < len(words) else 0xFFFF

    s = sim.Sim(Code(), {0x6a50: 0x8000})
    s.call(entry)
    fb = [s.rd(0x662a + i) for i in range(1024)]
    expect = []
    for w in splash.pack(splash.test_card()):
        expect += [w & 0xFF, w >> 8]
    assert fb == expect
    assert s.rd(0x6a50) == 0x8001
    assert s.rd(0x662a + 1024) == 0  # nothing written past the framebuffer
