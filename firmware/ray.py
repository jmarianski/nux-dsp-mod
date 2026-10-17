#!/usr/bin/env python3
"""Generate ray.patch: the raycaster (ray.c, compiled by cc/p16cc.py) on the NEK-100's LCD.

Extra > DOOM (extra_menu's item 7) starts it, any panel key stops it. Keys (as the desktop bridge):
C3 / E3 turn, C#3 or D#3 forward, D3 back, B2 / F3 strafe. C8: the ljmp test (a "1" bottom right
if d0ce jumps within bank 1; the first build, with ljmp in the self-test, crashed on Enter). Top-left: the last frame's time in ~ms; a
second number under it means the C self-test (computed here in the simulator) gave another value on the
device.

The asm glue around the C code: dm_start (pending; the next tick calls __cc_init and rc_start), dm_icon (the
skull), dm_panel (any panel key stops, every key becomes 0x7f), dm_key (notes to rc_key, then type 0), and the
tick hook (rc_tick, then the stock LCD refresh). All far code. RAM: rc_on and rc_r1 at 0x6430.., C from 0x6432
to the framebuffer (0x662a).

Usage: python3 firmware/ray.py [OUT.patch]      python3 firmware/ray.py --preview  (a frame from the simulator)
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "cc"))
import fbtest  # noqa: E402  (the skull icon, the digits font)
import p16cc  # noqa: E402

MAP = [
    "################",
    "#..............#",
    "#..##....##....#",
    "#..#......#....#",
    "#.....##.......#",
    "#..............#",
    "#.##.......###.#",
    "#.#.........#..#",
    "#.#..####...#..#",
    "#....#..#......#",
    "#....#..#..##..#",
    "#..............#",
    "#.###....#.....#",
    "#........#..#..#",
    "#...........#..#",
    "################",
]
RC_ON, RC_R1 = 0x6430, 0x6431
RAM = (0x6432, 0x662a)
DP_MAGIC, DP_PEND = 0x600D, 0x600E
ORG = 0x1a280


def data_c(expect):
    rows = [sum((c == "#") << x for x, c in enumerate(r)) for r in MAP]
    sin = [round(256 * math.sin(i * math.pi / 128)) for i in range(65)]
    digs = []
    for g in "0123456789":
        digs += fbtest.font_words()[fbtest.GLYPHS.index(g) * 3:fbtest.GLYPHS.index(g) * 3 + 3]
    return ("#define SELFTEST_EXPECT %d\n" % expect
            + "unsigned map[16] = {%s};\n" % ", ".join("%#06x" % r for r in rows)
            + "int sintab[65] = {%s};\n" % ", ".join(map(str, sin))
            + "unsigned digits[30] = {%s};\n" % ", ".join("%#04x" % d for d in digs))


def compile_ray(expect):
    return p16cc.compile_c(data_c(expect) + open(os.path.join(HERE, "ray.c")).read(), RAM, long_jumps=False)


class Machine:
    """The compiled program in nek100-mod's simulator, with the firmware's symbols."""

    def __init__(self, result):
        from nuxdsp import asm, fwmap, sim
        syms = dict(fwmap.load().symbols(), ljtest=0x1f000)      # the glue's ljtest: a bare ret here
        words, self.labels = asm.assemble(result.lines, syms, origin=ORG, label_prefix="ray")
        words[0x1f000] = 0xD1CA
        self.r = result

        class Code(dict):
            def __missing__(self, k):
                return 0xFFFF

        self.sim = sim.Sim(Code(words), {})
        self.fb = syms["framebuffer"]

    def call(self, name, *args):
        base = self.r.frames.get(name, (0, 0))[0]
        for k, v in enumerate(args):
            self.sim.wr(base + k, v)
        self.sim.steps = 0
        self.sim.call(self.labels[name], max_steps=20_000_000)
        return self.sim.r[7]

    def screen(self):
        rows = []
        for y in range(64):
            rows.append("".join("#" if self.sim.rd(self.fb + (y >> 3) * 128 + x) >> (y & 7) & 1 else "."
                                for x in range(128)))
        return "\n".join(rows)


def expected_selftest():
    m = Machine(compile_ray(0))
    m.call("__cc_init")
    return m.call("selftest")


GLUE = """
dm_start:                               ; extra_menu's item 7 (Enter): Extra redraws itself next, the tick starts us
    li    r6, #DP_PEND
    st    [rc_on], r6
    ret

dm_icon:                                ; extra_menu draws page 3: the skull in item 7's place
{icon}
    ret

dm_panel:                               ; key_event ([fp+3] key, [fp+2] state, 0 = pressed); r6 = r7 = 0 in and
    ld    r7, [rc_on]                   ; out. While on, every panel key becomes 0x7f (no handler); a press stops
    li    r6, #DP_MAGIC                 ; and redraws the screen (Extra)
    cmp   r7, r6
    bne   .po
    .dw   0xd2cf, 0x0002                ; ld r7, [fp+2]: state
    cmp   r7, #0
    bne   .pe
    st    [rc_on], r7
    ld    r7, [screen]
    push  r7
    ccall draw_screen
.pe:
    mov   r7, #0x7f
    .dw   0xd3cf, 0x0003                ; st [fp+3], r7
.po:
    mov   r6, #0
    mov   r7, #0
    ret

dm_key:                                 ; touch_off: r1 = event ([+3] type 9 on / 8 off, [+4] key, [+5] velocity),
    cmp   r7, #9                        ; r7 = its type; keeps r1, r3. While on: rc_key(key, velocity or 0), and
    beq   .kk                           ; type 0, which nothing handles
    cmp   r7, #8
    beq   .kk
    ret
.kk:
    ld    r6, [rc_on]
    li    r5, #DP_MAGIC
    cmp   r6, r5
    beq   .km
    ret
.km:
    st    [rc_r1], r1
    ld    r6, [r1+5]
    cmp   r7, #8
    bne   .kn
    mov   r6, #0
.kn:
    st    [rc_key__f+1], r6
    ld    r6, [r1+4]
    and   r6, #0x7f
    st    [rc_key__f+0], r6
    call  rc_key                        ; C keeps r0, r2, r3
    ld    r1, [rc_r1]
    mov   r7, #0
    st    [0x000b], r7                  ; idle_ticks = 0, as the firmware does for a note
    st    [0x000c], r7
    st    [r1+3], r7
    ret

ljtest:                                 ; C8 in the game: is d0ce an absolute jump within bank 1? Coming back sets
    ljmp  .lj_t                         ; lj = 1 (shown bottom right); a crash says it is not
    mov   r7, #2
    st    [lj], r7
    ret
.lj_t:
    mov   r7, #1
    st    [lj], r7
    ret

rc_tickh:                               ; in place of tick_10ms's ccall lcd_refresh
    ld    r7, [rc_on]
    li    r6, #DP_PEND
    cmp   r7, r6
    bne   .on
    li    r7, #DP_MAGIC
    st    [rc_on], r7
    call  __cc_init
    call  rc_start
    jmp   .refresh
.on:
    li    r6, #DP_MAGIC
    cmp   r7, r6
    bne   .refresh
    call  rc_tick
.refresh:
    ccall 0x4e75
    ret
"""


def patch():
    expect = expected_selftest()
    r = compile_ray(expect)
    icon = "\n".join("    mov   r7, #%#04x\n    st    [%#06x], r7" % (b, 0x662a + a)
                     for a, b in sorted(fbtest.skull_bytes().items()))
    body = "\n".join(r.lines)
    return f""".patch doom_ray
.title "doom-piano: Extra > DOOM, a raycaster in C on the LCD (keys move, a panel key leaves)"
.requires extra_menu touch_off
; Generated by doom-piano/firmware/ray.py from ray.c (cc/p16cc.py), do not edit by hand. Our own code only.
; C self-test expected: {expect}. C RAM: {r.ram_used} words from {RAM[0]:#06x}.

.hook 0x007ea expect 0xd7c8 0x4e75     ; tick_10ms: ccall lcd_refresh (sends the framebuffer when flagged)
    call  rc_tickh
.end

.code 0x1a280
.equ rc_on, {RC_ON:#06x}
.equ rc_r1, {RC_R1:#06x}
.equ DP_MAGIC, {DP_MAGIC:#06x}
.equ DP_PEND, {DP_PEND:#06x}
{GLUE.format(icon=icon)}
{body}
.end
"""


def main(argv):
    if argv[:1] == ["--preview"]:
        m = Machine(compile_ray(expected_selftest()))
        m.call("__cc_init")
        m.call("rc_start")
        print(m.screen())
        steps = m.sim.steps
        m.call("frame")
        print("frame: %d instructions (rc_start incl. self-test: %d)" % (m.sim.steps, steps))
        return
    out = argv[0] if argv else os.path.join(HERE, "ray.patch")
    open(out, "w").write(patch())
    print("wrote", out)


if __name__ == "__main__":
    main(sys.argv[1:])
