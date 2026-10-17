#!/usr/bin/env python3
"""The game for the browser emulator (web/): the same compiled code as the patch, predecoded for web/p16.js.

The instructions are decoded here, by nek100-mod's isa.py (the simulator's own decoder), so the JS side only
executes: one entry per program word, {op, a, b} with branch targets already absolute. The asm glue's functions
that talk to the firmware (synth, farcopy, trace, ...) are natives: the JS emulator does what they do on the
piano (WebMIDI out, copies from the far data below, a log). Far data (music, test patterns) sits at made-up far
addresses; the native fr_init stores those where the C code expects them.

Output (web/build/, not in git: it carries WAD data): game.json.

Usage: python3 tools/webbuild.py [--engine doom|ray] [OUT.json]
"""
import json
import os
import sys
import argparse
from pathlib import Path
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "firmware"))
sys.path.insert(0, os.path.join(ROOT, "..", "nek100-mod"))

OPS = ["bad", "ret", "sub", "mov_r", "mov_i", "cmp_r", "cmp_i", "add_r", "add_i", "and_r", "and_i", "or_r",
       "shl", "shr", "ldc", "ld_abs", "ld_r1", "ld_fp", "st_abs", "st_r1", "st_fp", "li", "addi",
       "jmp", "beq", "bne", "blt", "ljmp", "call", "mul"]
NATIVES = ["trace", "farcopy", "synth", "fr_init", "mdiag", "ljtest"]
NATIVE_BASE = 0x3fff0
FAR_PATTERNS, FAR_MUSIC = 0x2f000, 0x30000
MMIO = {"clock_lo": 0x6d78, "clock_hi": 0x6d79, "lcd_flag": 0x6a50, "dev_vol": 0x0145, "framebuffer": 0x662a}


def decode_word(words, pc):
    """-> (op id, a, b, length) for the word at pc ("bad" for anything the simulator does not execute)."""
    from nuxdsp import isa
    x = words.get(pc, 0xFFFF)
    two = isa.is_two_words(x) and (x & 0xFFF8) != 0xD4C8  # mul is one word, as on the device
    d = isa.decode(x, words.get(pc + 1, 0xFFFF) if two else None)
    n = 2 if two else 1
    if d is None:
        return 0, 0, 0, n
    op, a = d
    if op == "mul":
        return OPS.index("mul"), a[0], 0, 1
    if op == "ret":
        return OPS.index("ret"), 0, 0, n
    if op == "sub":
        return OPS.index("sub"), a[0], a[1][1], n
    if op in ("mov", "cmp", "add", "and", "or"):
        reg = isinstance(a[1], tuple)
        name = op + ("_r" if reg else "_i")
        return OPS.index(name), a[0], a[1][1] if reg else a[1] & 0xFF, n
    if op in ("shl", "shr", "ldc", "li", "addi"):
        return OPS.index(op), a[0], a[1], n
    if op in ("ld", "st"):
        return OPS.index(op + "_" + a[1][0]), a[0], a[1][1], n
    if op in ("jmp", "beq", "bne", "blt"):
        return OPS.index(op), 0, pc + 1 + a[0][1], n
    if op == "ljmp":
        return OPS.index("ljmp"), 0, (pc & ~0xFFFF) | a[0][1], n
    if op == "call":
        return OPS.index("call"), 0, a[0][1], n
    return 0, 0, 0, n


def music():
    try:
        import ray
        return ray.music()
    except (FileNotFoundError, OSError):
        return [0x00FF, 0]                       # no WAD: a song that is only its end


def program(r, wanted, extra_lines=()):
    from nuxdsp import asm, fwmap
    natives = {name: NATIVE_BASE + k for k, name in enumerate(NATIVES)}
    syms = dict(fwmap.load().symbols(), **natives)
    words, labels = asm.assemble(r.lines + list(extra_lines), syms, origin=0x1a280, label_prefix="game")
    lo, hi = min(words), max(words) + 1
    op, a, b = [], [], []
    for pc in range(lo, hi):
        o, x, y, _ = decode_word(words, pc)
        op.append(o)
        a.append(x)
        b.append(y)
    return {
        "ops": OPS,
        "code": {"start": lo, "op": op, "a": a, "b": b},
        "natives": {str(v): k for k, v in natives.items()},
        "entry": {k: labels[k] for k in wanted},
        "frames": {k: r.frames[k][0] for k in wanted if k in r.frames},
        "symbols": {k: v for k, v in r.symbols.items() if "__" not in k},
        "mmio": MMIO,
        "ram_words": r.ram_used,
        "keys": {"strafe_left": 47, "left": 48, "forward": 49, "back": 50, "forward2": 51, "right": 52,
                 "strafe_right": 53},
        "tick_ms": 10,
    }


def build_ray():
    import ray
    r = ray.compile_ray(ray.expected_selftest())
    s = r.symbols
    far = [{"addr": FAR_PATTERNS + 0x100 * k, "words": ray.pattern(k)} for k in range(3)]
    far.append({"addr": FAR_MUSIC, "words": music()})
    init = []
    for k in range(3):
        init += [[s["pt_hi"] + k, (FAR_PATTERNS + 0x100 * k) >> 16], [s["pt_lo"] + k, (FAR_PATTERNS + 0x100 * k) & 0xFFFF]]
    init += [[s["mu_shi"], FAR_MUSIC >> 16], [s["mu_slo"], FAR_MUSIC & 0xFFFF]]
    wanted = ["__cc_init", "rc_start", "rc_tick", "rc_key", "frame", "selftest", "mu_stop", "mu_restart"]
    return dict(program(r, wanted, ray.ADIAG.splitlines()), **{
        "name": "ray",
        "label": "Raycaster testowy",
        "far": far,
        "fr_init": init,
    })


def build_doom(m=None, silent_audio=False):
    import doom
    import doommap
    m = m or doommap.Map()
    r = doom.compile_doom(m, silent_audio=silent_audio)
    s = r.symbols
    far = [{"addr": FAR_MUSIC, "words": music()}]
    init = [[s["mu_shi"], FAR_MUSIC >> 16], [s["mu_slo"], FAR_MUSIC & 0xffff]]
    addr = 0x20000
    tables = m.words()
    tables.update(doom.assets())
    for k, name in enumerate(doom.TABLES):
        words = tables[name]
        far.append({"addr": addr, "words": words})
        init += [[s["map_hi"] + k, addr >> 16], [s["map_lo"] + k, addr & 0xffff]]
        addr += len(words)
    wanted = ["__cc_init", "rc_start", "rc_tick", "rc_key", "frame", "mu_stop", "mu_restart", "umul32", "smul32", "fmul", "muldiv",
              "can_move", "move_player", "steer", "sector_at", "game_tick", "use_game", "fire_game", "ray_clear",
              "dynamic_tick", "pickup_tick", "damage", "game_init", "read_sector", "audio_restart", "ray_fraction",
              "frame_begin", "frame_work", "bsp_work", "pickup_draw_work", "enemy_draw_work", "draw_overlay", "bsp_step"]
    result = dict(program(r, wanted), name="doom", label="E1M1 · demo", far=far, fr_init=init)
    # Engineering limits on decoded C/P16 work, including startup. Host natives
    # and device firmware/RTOS time still require a hardware measurement.
    # The earlier device-tested raycaster peaks at 134294 decoded instructions/tick.
    result["callback_limits"] = {"__cc_init": 10000, "rc_start": 50000, "rc_tick": 136000, "rc_key": 2000}
    result["hardware_timing_verified"] = False
    result["silent_audio"] = silent_audio
    result["status"] = "hardware-diagnostic"
    import budget
    result["budget"] = {"ram": budget.check_ram(r.ram_used), "program": budget.check_regions(
        [("compiled C", result["code"]["start"], len(result["code"]["op"]))] +
        [(f"far data {k}", seg["addr"], len(seg["words"])) for k, seg in enumerate(far)])}
    result["keys"].update(fire=72, use=74, restart=23, run=76)
    enemies = getattr(m, "enemies", [])
    if enemies:
        # Browser-only navigation aid. It is not part of the linked image or RAM budget.
        from playthrough import route
        start = m.start()[:2]
        first = min(range(len(enemies)), key=lambda i: abs(enemies[i][0] - start[0]) + abs(enemies[i][1] - start[1]))
        path = route(enemies[first][:2], m=m)
        result["navigation"] = {"route": path[:-4] if len(path) > 4 else path,
                                "target": first, "enemy_count": len(enemies), "start": start}
    return result


def main(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("out", nargs="?", default=os.path.join(ROOT, "web", "build", "game.json"))
    p.add_argument("--engine", choices=["doom", "ray"], default="doom")
    args = p.parse_args(argv)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    prog = build_doom() if args.engine == "doom" else build_ray()
    # Readers never see half a JSON file, including after an interrupted build.
    tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=out.parent, delete=False) as f:
            tmp = f.name
            json.dump(prog, f, separators=(",", ":"))
        os.replace(tmp, out)
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)
    print("wrote", out, "-", len(prog["code"]["op"]), "words of code")


if __name__ == "__main__":
    main(sys.argv[1:])
