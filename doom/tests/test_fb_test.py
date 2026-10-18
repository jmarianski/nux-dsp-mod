"""Build fb_test into the official firmware and run its far renderer under nek100-mod's ISA simulator.

Needs the official NEK100_DSP_V1.0.7.bin (NEK100_FW, or next to nek100-mod); skipped otherwise.
The firmware's copy routine (0x7638) is not simulated: the call that copies the card is checked word for word
against init_all's (0x4928). The font and tables come from simulating dp_init. Our ISA model only.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOD = os.path.join(ROOT, "..")   # nek100-mod, this directory's parent
FW = os.environ.get("NEK100_FW") or os.path.join(ROOT, "..", "..", "NEK100_DSP_V1.0.7.bin")
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
    assert syms["dm_start"] == far and syms["dp_cpcard"] == near
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
    far = syms["dm_start"]
    calls = [words[i] for i in range(far, card - 1) if words[i + 1] == a]
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
    assert [s.rd(R["dp_keys"] + k) for k in range(128)] == [0] * 128 and s.rd(R["dp_note"]) == 0
    assert all(R["dp_tab"] <= a < R["dp_fnt"] + len(font) or a == R["dp_note"] or R["dp_keys"] <= a < R["dp_keys"] + 128
               for a in s.ram.written)


def model(fbtest, ram):
    """What one frame should look like, from the state before it."""
    fb = [0] * 1024
    lx = (ram[fbtest.RAM["dp_lx"]] + 1) & 127
    for p in range(8):
        fb[p * 128 + lx] = 0xFF
    held = lambda k: ram.get(fbtest.RAM["dp_keys"] + fbtest.KEYS[k], 0) != 0
    x = ram[fbtest.RAM["dp_x"]] + 2 * (held("right") - held("left"))
    y = ram[fbtest.RAM["dp_y"]] + 2 * (held("down") - (held("up") or held("up2")))
    x = 120 if x >= 120 else 32 if x < 33 else x
    y = 56 if y >= 56 else 0 if y < 1 else y
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


@pytest.mark.parametrize("x, y, keys", [(40, 20, ()), (40, 23, ("right", "down")), (60, 55, ("left", "up")),
                                         (33, 1, ("left", "up2")), (119, 30, ("right",)), (50, 54, ("down",))])
def test_frame_renders_box_line_and_numbers(built, x, y, keys):
    fbtest, words, syms = built
    R = fbtest.RAM
    ram = dict(sim_call(words, syms["dp_init"], {}).ram)
    ram.update({R["dp_lx"]: 5, R["dp_x"]: x, R["dp_y"]: y, R["dp_sec"]: 123, R["dp_d"]: 1000, R["dp_b"]: 4567,
                R["dp_l"]: 32000, R["dp_note"]: 60, 0x6a50: 0x8000})
    ram.update({R["dp_keys"] + fbtest.KEYS[k]: 100 for k in keys})
    before = dict(ram)
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


@pytest.mark.parametrize("us", [0, 1023, 1024, 1_000_000, 0x8000FFFF, 0xFFFFFFFF])
def test_now_is_the_clock_in_1024_us(built, us):
    fbtest, words, syms = built
    ram = {fbtest.CLOCK: us & 0xFFFF, fbtest.CLOCK + 1: us >> 16}
    s = sim_call(words, syms["dp_now"], ram)
    assert s.r[7] == (us >> 10) & 0xFFFF


def call_words(a):
    return [0xd6c8 | a >> 16, a & 0xFFFF]


def has(words, seq, start=0x100):
    return any(list(words[i:i + len(seq)]) == seq for i in range(start, len(words) - len(seq)) if words[i] == seq[0])


def test_no_hooks_but_the_tick(built):
    """Notes and panel keys come through nek100-mod's weak symbols; the stock code at the old hooks is intact."""
    fbtest, words, syms = built
    from nuxdsp import container
    w0 = container.words(open(FW, "rb").read())
    assert list(words[0x282f:0x2833]) == list(w0[0x282f:0x2833])
    assert list(words[0x3864:0x3867]) == list(w0[0x3864:0x3867])
    assert list(words[0x7ea:0x7ec]) == call_words(syms["dp_tick"])


@pytest.mark.parametrize("name", ["dm_start", "dm_icon", "dm_panel", "dm_key"])
def test_weak_symbols_are_ours(built, name):
    fbtest, words, syms = built
    assert syms[name] >= 0x1a280 and has(words, call_words(syms[name]))


def test_start_is_pending_until_the_tick(built):
    fbtest, words, syms = built
    s = sim_call(words, syms["dm_start"], Watch({fbtest.RAM["dp_on"]: 0x6b}))
    assert s.rd(fbtest.RAM["dp_on"]) == fbtest.DP_PEND and s.ram.written == {fbtest.RAM["dp_on"]}
    t = syms["dp_tick"]
    body = list(words[t:t + 12])
    assert fbtest.DP_PEND in body and has(words[:t + 12], call_words(syms["dp_go"]), t)
    assert fbtest.DP_MAGIC in list(words[syms["dp_go"]:syms["dp_go"] + 3])


def run_key(fbtest, words, syms, on, ev_type, key, vel):
    R, ev = fbtest.RAM, 0x7100
    ram = Watch({ev + 2: 0, ev + 3: ev_type, ev + 4: key, ev + 5: vel,
                 R["dp_on"]: fbtest.DP_MAGIC if on else 0x6b, R["dp_note"]: 7, 0x000b: 55, 0x000c: 1})
    from nuxdsp import sim

    class Code(dict):
        def __missing__(self, k):
            return words[k] if k < len(words) else 0xFFFF

    s = sim.Sim(Code(), {})
    s.ram = ram
    s.r[1], s.r[3], s.r[7] = ev, 0x1234, ev_type
    s.call(syms["dm_key"])
    assert s.r[1] == ev and s.r[3] == 0x1234
    return s


@pytest.mark.parametrize("ev_type", [9, 8, 0xb])
def test_key_passes_everything_while_off(built, ev_type):
    fbtest, words, syms = built
    s = run_key(fbtest, words, syms, False, ev_type, 60, 100)
    assert s.r[7] == ev_type and not s.ram.written


def test_key_takes_notes_while_on(built):
    fbtest, words, syms = built
    R = fbtest.RAM
    s = run_key(fbtest, words, syms, True, 9, 48, 90)
    assert s.r[7] == 0 and s.rd(0x7103) == 0                       # type 0: nobody handles it
    assert s.rd(R["dp_keys"] + 48) == 90 and s.rd(R["dp_note"]) == 48
    assert s.rd(0x000b) == 0 and s.rd(0x000c) == 0
    for ev_type, vel in ((8, 64), (9, 0)):                         # note off, and note on with velocity 0
        s = run_key(fbtest, words, syms, True, ev_type, 48, vel)
        assert s.r[7] == 0 and s.rd(R["dp_keys"] + 48) == 0 and s.rd(R["dp_note"]) == 7
    s = run_key(fbtest, words, syms, True, 0xb, 64, 127)           # pedal and other CCs: the firmware's
    assert s.r[7] == 0xb and not s.ram.written


def test_panel_while_off_changes_nothing(built):
    """key_event zeroes idle_ticks with r6:r7 after us: they must come back 0."""
    fbtest, words, syms = built
    s = sim_call(words, syms["dm_panel"], Watch({fbtest.RAM["dp_on"]: 0x6b}))
    assert s.r[6] == 0 and s.r[7] == 0 and not s.ram.written


def test_panel_while_on_eats_the_key(built):
    """Real-fp loads and ccall are not simulated: the words. A press stops and redraws; every key becomes 0x7f."""
    fbtest, words, syms = built
    a = syms["dm_panel"]
    body = list(words[a:syms["dm_key"]])
    i = body.index(0xd2cf)
    assert body[i:i + 3] == [0xd2cf, 0x0002, 0x0f00]               # ld r7, [fp+2]; cmp r7, #0
    k = body.index(0xd3cf)
    assert body[k - 1:k + 2] == [0x077f, 0xd3cf, 0x0003]           # mov r7, #0x7f; st [fp+3], r7
    assert body[-3:] == [0x0600, 0x0700, 0xd1ca]   # mov r6, #0; mov r7, #0; ret
    from nuxdsp import fwmap
    c = body.index(0xd7c8)
    assert i < c < k and body[c + 1] == fwmap.load().symbols()["draw_screen"]   # ccall draw_screen on a press


def test_icon_is_the_skull(built):
    fbtest, words, syms = built
    s = sim_call(words, syms["dm_icon"], Watch({}))
    assert {a - FB: s.rd(a) for a in s.ram.written} == fbtest.skull_bytes()
    assert all(FB + 2 * 128 + 52 <= a < FB + 5 * 128 and 52 <= (a - FB) % 128 < 76 for a in s.ram.written)


def test_extra_menu_offers_doom(built):
    """extra_menu's item 7 calls dm_start when this patch is in (dm_start is weak there)."""
    fbtest, words, syms = built
    from nuxdsp import fwmap, patcher
    m = fwmap.load()
    out, report = patcher.build(open(FW, "rb").read(), m, patcher.resolve_patches(DEFAULTS, m))
    from nuxdsp import container
    alone = container.words(out)
    call = [0xd6c8 | syms["dm_start"] >> 16, syms["dm_start"] & 0xFFFF]
    assert any(list(words[i:i + 2]) == call for i in range(0x100, len(words) - 1) if words[i] == call[0])
