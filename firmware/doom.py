#!/usr/bin/env python3
"""Compile the E1M1 demo for the same P16 used by the piano and web emulator.

--patch OUT generates a local patch. Map/music/build data stays outside git.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(HERE.parent / "cc"))
import doommap
import p16cc

RAM = (0x6448, 0x662a)
ORG = 0x1a280
TABLES = ["vertices", "nodes", "subsecs", "segs", "sectors", "collision", "blockmap", "sine", "entities", "dynamics",
          "sprites", "font", "walltex"]


def assets():
    """Small original silhouettes with a one-pixel light outline, and a 3x5 HUD font."""
    import fbtest
    rows = dict(fbtest.FONT_ROWS)
    rows.update({"H": ["#.#", "#.#", "###", "#.#", "#.#"], "A": [".#.", "#.#", "###", "#.#", "#.#"],
                 "K": ["#.#", "#.#", "##.", "#.#", "#.#"], "W": ["#.#", "#.#", "###", "###", "#.#"],
                 "I": ["###", ".#.", ".#.", ".#.", "###"], "E": ["###", "#..", "##.", "#..", "###"],
                 "/": ["..#", "..#", ".#.", "#..", "#.."]})
    font = [sum((rows[ch][y][x] == "#") << y for y in range(5)) for ch in "0123456789HAKWINDE/" for x in range(3)]
    human = ["........", "..####..", "..#oo#..", "..####..", "...##...", "..####..", ".######.", ".######.",
             ".#.##.#.", "...##...", "..####..", "..#..#..", "..#..#..", "..#..#..", ".##..##.", "........"]
    imp = ["........", "..#..#..", "..####..", "..#oo#..", "..####..", ".######.", ".######.", ".#.##.#.",
           "...##...", "..####..", "..####..", "..#..#..", "..#..#..", ".##..##.", "........", "........"]
    shapes = [human, imp]
    for kind in range(3, 10):
        shape = [list("........") for _ in range(16)]
        for y in range(5, 12):
            for x in range(1, 7):
                shape[y][x] = "#"
        if kind in (3, 4, 5):
            for y in range(6, 11): shape[y][3] = "o"
            for x in range(2, 6): shape[8][x] = "o"
        elif kind == 6:
            for y in range(6, 11):
                shape[y][2] = shape[y][5] = "o"
        elif kind == 9:
            shape = [list("........") for _ in range(16)]
            for x in range(1, 7): shape[7][x] = shape[8][x] = "#"
            for y in range(9, 12): shape[y][5] = "#"
        else:
            for y in range(6, 11): shape[y][3] = "o"
        shapes.append(shape)
    sprites = []
    for shape in shapes:
        for y in range(16):
            mask = ink = 0
            for x in range(8):
                if shape[y][x] == "#": ink |= 1 << x
                if any(shape[yy][xx] != "." for yy in range(max(0, y - 1), min(16, y + 2))
                       for xx in range(max(0, x - 1), min(8, x + 2))): mask |= 1 << x
            sprites += [mask, ink]
    return {"sprites": sprites, "font": font}


def compile_doom(m=None, silent_audio=False):
    m = m or doommap.Map()
    # The fixed explicit stack must cover the deepest front-to-back BSP path.
    def depth(n):
        return 1 if n & 0x8000 else 1 + max(depth(c) for c in m.nodes[n][4:])
    if depth(m.root) > 32:
        raise ValueError("map exceeds the 32-word BSP stack")
    x, y, a = m.start()
    bx, by, bw, bh = m.block_info
    pre = (f"#define SILENT_AUDIO {int(silent_audio)}\n"
           + f"#define MAP_ROOT {m.root}\n#define START_X {x}\n#define START_Y {y}\n#define START_A {a}\n"
           + f"#define BLOCK_X {bx}\n#define BLOCK_Y {by}\n#define BLOCK_W {bw}\n#define BLOCK_H {bh}\n"
           + f"#define ENEMY_N {len(getattr(m, 'enemies', []))}\n#define PICKUP_N {len(getattr(m, 'pickups', []))}\n"
           + f"#define DYNAMIC_N {len(getattr(m, 'dynamics', []))}\n")
    src = (HERE / "doom.c").read_text().replace(
        "/* MUSIC_SOURCE: inserted by ray.py / doom.py, shared by both engines. */", (HERE / "music.c").read_text())
    src = src.replace("/* GAME_SOURCE: inserted by doom.py. */", (HERE / "game.c").read_text())
    return p16cc.compile_c(pre + src, RAM, long_jumps=False, isolated=("rc_key",))


def patch(m=None, silent_audio=False):
    """Local firmware patch, including WAD-derived data. Never add the output to git."""
    import ray
    import fbtest
    m = m or doommap.Map()
    r = compile_doom(m, silent_audio=silent_audio)
    tables = m.words(); tables.update(assets())
    init = []
    for i, name in enumerate(TABLES):
        for half, shift in (("hi", ">> 16"), ("lo", "& 0xffff")):
            init += [f"    li r7, #(data_{name} {shift})", f"    st [map_{half}+{i}], r7"]
    for half, shift in (("shi", ">> 16"), ("slo", "& 0xffff")):
        init += [f"    li r7, #(mu_data {shift})", f"    st [mu_{half}], r7"]
    icon = "\n".join(f"    mov r7, #{v}\n    st [{0x662a + k:#x}], r7" for k, v in sorted(fbtest.skull_bytes().items()))
    panel = ray.GLUE[ray.GLUE.index("dm_panel:"):ray.GLUE.index("\ndm_key:")]
    keys = ray.GLUE[ray.GLUE.index("dm_key:"):ray.GLUE.index("\nljtest:")]
    services = ray.GLUE[ray.GLUE.index("farcopy:"):ray.GLUE.index("\nmdiag:")]
    data = "mu_data:\n" + ray.dw(ray.music()) + "\n"
    data += "\n".join(f"data_{name}:\n{ray.dw(tables[name])}" for name in TABLES)
    glue = f"""
.equ rc_on, 0x6430
.equ rc_r1, 0x6431
.equ DP_MAGIC, 0x600d
.equ DP_PEND, 0x600e
.equ fc_s0, 0x6445
.equ fc_s2, 0x6446
.equ fc_s3, 0x6447
dm_start:
    li r7, #DP_PEND
    st [rc_on], r7
    ret
dm_icon:
{icon}
    ret
{panel}
{keys}
{services}
trace:                                  ; channel-16 USB progress, as the tested ray diagnostics
    st [fc_s0], r0
    st [fc_s2], r2
    st [fc_s3], r3
    mov r5, r7
    shr r7, 7
    and r7, #0x7f
    shl r7, 8
    and r5, #0x7f
    or r7, r5
    push r7
    li r6, #0x0bbf
    push r6
    ccall 0x062cc
    ld r0, [fc_s0]
    ld r2, [fc_s2]
    ld r3, [fc_s3]
    ret
fr_init:
{chr(10).join(init)}
    ret
rc_tickh:
    ld r7, [rc_on]
    li r6, #DP_PEND
    cmp r7, r6
    beq .start
    li r6, #DP_MAGIC
    cmp r7, r6
    bne .refresh
    call rc_tick
    jmp .refresh
.start:
    li r7, #DP_MAGIC
    st [rc_on], r7
    call __cc_init
    call rc_start
.refresh:
    ccall 0x4e75
    ret
"""
    return f""".patch doom_demo
.title "doom-piano: playable E1M1 demo"
.requires extra_menu touch_off
; Local generated output: contains WAD-derived data. RAM {r.ram_used}/{RAM[1] - RAM[0]} words.
.hook 0x007ea expect 0xd7c8 0x4e75
    call rc_tickh
.end
.code 0x1a280
{glue}
{r.text()}
{data}
.end
.code
{ray.FR_COPY0}
.end
"""


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--patch":
        out = Path(sys.argv[2]); out.parent.mkdir(parents=True, exist_ok=True); out.write_text(patch())
        print("wrote local patch", out)
    else:
        r = compile_doom()
        print(f"E1M1: {r.ram_used} RAM words of {RAM[1] - RAM[0]}")
