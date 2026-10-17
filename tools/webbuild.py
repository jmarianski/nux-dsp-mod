#!/usr/bin/env python3
"""The game for the browser emulator (web/): the same compiled code as the patch, predecoded for web/p16.js.

The instructions are decoded here, by nek100-mod's isa.py (the simulator's own decoder), so the JS side only
executes: one entry per program word, {op, a, b} with branch targets already absolute. The asm glue's functions
that talk to the firmware (synth, farcopy, trace, ...) are natives: the JS emulator does what they do on the
piano (WebMIDI out, copies from the far data below, a log). Far data (music, test patterns) sits at made-up far
addresses; the native fr_init stores those where the C code expects them.

Output (web/build/, not in git: it carries WAD data): game.json.

Usage: python3 tools/webbuild.py [OUT.json]
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "firmware"))
sys.path.insert(0, os.path.join(ROOT, "..", "nek100-mod"))

OPS = ["bad", "ret", "sub", "mov_r", "mov_i", "cmp_r", "cmp_i", "add_r", "add_i", "and_r", "and_i", "or_r",
       "shl", "shr", "ldc", "ld_abs", "ld_r1", "ld_fp", "st_abs", "st_r1", "st_fp", "li", "addi",
       "jmp", "beq", "bne", "blt", "ljmp", "call"]
NATIVES = ["trace", "farcopy", "synth", "fr_init", "mdiag", "ljtest"]
NATIVE_BASE = 0x1f000
FAR_PATTERNS, FAR_MUSIC = 0x2f000, 0x30000
MMIO = {"clock_lo": 0x6d78, "clock_hi": 0x6d79, "lcd_flag": 0x6a50, "dev_vol": 0x0145, "framebuffer": 0x662a}


def decode_word(words, pc):
    """-> (op id, a, b, length) for the word at pc ("bad" for anything the simulator does not execute)."""
    from nuxdsp import isa
    x = words.get(pc, 0xFFFF)
    two = isa.is_two_words(x)
    d = isa.decode(x, words.get(pc + 1, 0xFFFF) if two else None)
    n = 2 if two else 1
    if d is None:
        return 0, 0, 0, n
    op, a = d
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


def build_ray():
    import ray
    from nuxdsp import asm, fwmap
    r = ray.compile_ray(ray.expected_selftest())
    natives = {name: NATIVE_BASE + k for k, name in enumerate(NATIVES)}
    syms = dict(fwmap.load().symbols(), **natives)
    words, labels = asm.assemble(r.lines + ray.ADIAG.splitlines(), syms, origin=ray.ORG, label_prefix="ray")
    for addr in natives.values():
        words[addr] = 0xD1CA
    lo, hi = min(words), max(words) + 2
    op, a, b = [], [], []
    for pc in range(lo, hi):
        o, x, y, _ = decode_word(words, pc)
        op.append(o)
        a.append(x)
        b.append(y)
    s = r.symbols
    far = [{"addr": FAR_PATTERNS + 0x100 * k, "words": ray.pattern(k)} for k in range(3)]
    far.append({"addr": FAR_MUSIC, "words": music()})
    init = []
    for k in range(3):
        init += [[s["pt_hi"] + k, (FAR_PATTERNS + 0x100 * k) >> 16], [s["pt_lo"] + k, (FAR_PATTERNS + 0x100 * k) & 0xFFFF]]
    init += [[s["mu_shi"], FAR_MUSIC >> 16], [s["mu_slo"], FAR_MUSIC & 0xFFFF]]
    wanted = ["__cc_init", "rc_start", "rc_tick", "rc_key", "frame", "selftest", "mu_stop"]
    return {
        "name": "ray",
        "ops": OPS,
        "code": {"start": lo, "op": op, "a": a, "b": b},
        "natives": {str(v): k for k, v in natives.items()},
        "entry": {k: labels[k] for k in wanted},
        "frames": {k: r.frames[k][0] for k in wanted if k in r.frames},
        "symbols": {k: v for k, v in s.items() if "__" not in k},
        "mmio": MMIO,
        "far": far,
        "fr_init": init,
        "keys": {"strafe_left": 47, "left": 48, "forward": 49, "back": 50, "forward2": 51, "right": 52,
                 "strafe_right": 53},
        "tick_ms": 10,
    }


def main(argv):
    out = argv[0] if argv else os.path.join(ROOT, "web", "build", "game.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    prog = build_ray()
    with open(out, "w") as f:
        json.dump(prog, f, separators=(",", ":"))
    print("wrote", out, "-", len(prog["code"]["op"]), "words of code")


if __name__ == "__main__":
    main(sys.argv[1:])
