#!/usr/bin/env python3
"""Build and audit the local NEK-100 demo firmware. Does not flash the device.

Usage: python3 tools/builddemo.py [--firmware ../NEK100_DSP_V1.0.7.bin]
Outputs proprietary/WAD-derived files only under the ignored build/ directory.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "firmware"))
sys.path.insert(0, str(ROOT.parent / "nek100-mod"))
import budget
import doom
import wad
from nuxdsp import fwmap, patcher, asm, container


def linked_program(image, demo, result, place, target, summary, silent_audio=False):
    """Decode the actual linked C instruction words and data from the audited .bin.

    The firmware services still use host natives. Calls and far-data addresses are
    the actual linker values, so the same gameplay replay can check the real artifact.
    """
    import webbuild
    import ray
    labels = target.symbols()
    for key, lines, _n in patcher.code_blocks(demo):
        _words, found = asm.assemble(lines, labels, origin=place[key], label_prefix=demo.name, labels_only=True)
        labels.update(found)
    words = container.words(image)
    for key, lines, _n in patcher.code_blocks(demo):
        compiled, _ = asm.assemble(lines, labels, origin=place[key], label_prefix=demo.name, predefined_labels=True)
        if any(words[a] != v for a, v in compiled.items()):
            raise ValueError("linked image differs from the assembled demo")
    prog = webbuild.build_doom(silent_audio=silent_audio)
    lo, hi = place[demo.name], labels["mu_data"]
    instructions = {a: words[a] for a in range(lo, hi)}
    decoded = [webbuild.decode_word(instructions, a) for a in range(lo, hi)]
    prog["code"] = {"start": lo, "op": [x[0] for x in decoded], "a": [x[1] for x in decoded], "b": [x[2] for x in decoded]}
    prog["entry"] = {name: labels[name] for name in prog["entry"]}
    prog["natives"] = {str(labels[name]): name for name in ("farcopy", "synth", "fr_init", "trace")}
    m = doom.doommap.Map()
    tables = m.words(); tables.update(doom.assets())
    prog["far"] = [{"addr": labels["mu_data"], "words": words[labels["mu_data"]:labels["mu_data"] + len(ray.music())]}]
    init = [[result.symbols["mu_shi"], labels["mu_data"] >> 16], [result.symbols["mu_slo"], labels["mu_data"] & 0xffff]]
    for i, name in enumerate(doom.TABLES):
        addr = labels["data_" + name]
        prog["far"].append({"addr": addr, "words": words[addr:addr + len(tables[name])]})
        init += [[result.symbols["map_hi"] + i, addr >> 16], [result.symbols["map_lo"] + i, addr & 0xffff]]
    prog["fr_init"] = init
    prog["budget"] = summary
    prog["artifact"] = "NEK100_DSP_demo.bin"
    return prog


def build(firmware, out, silent_audio=False, extra=()):
    m = fwmap.load()
    r = doom.compile_doom(silent_audio=silent_audio)
    ram = budget.check_ram(r.ram_used)
    text = doom.patch(silent_audio=silent_audio)
    demo = patcher.parse(text, str(out / "doom_demo.patch"))
    patches = [patcher.load(name, m) for name in list(m.defaults) + list(extra)] + [demo]
    canonical = patcher.canonical_layout(m)
    layout = {key: canonical[key] for p in patches for key, _lines, _n in patcher.code_blocks(p) if key in canonical}
    regions = patcher.allocate(patches, m, layout)
    image, report = patcher.build(firmware.read_bytes(), m, patches, layout=regions)
    rom = budget.check_firmware(image)
    game_regions = [(key, regions[key], n) for key, _lines, n in patcher.code_blocks(demo)]
    # The bank-0 service wrapper is already constrained by its target pool. Audit far code/data separately.
    program = budget.check_regions([reg for reg in game_regions if reg[1] >= budget.ROM_START])
    summary = {"ram": ram, "program": program, "firmware": rom,
               "regions": {key: {"address": addr, "words": n} for key, addr, n in game_regions}}
    linked = linked_program(image, demo, r, regions, m, summary, silent_audio=silent_audio)
    out.mkdir(parents=True, exist_ok=True)
    (out / "doom_demo.patch").write_text(text)
    (out / "NEK100_DSP_demo.bin").write_bytes(image)
    (out / "memory-budget.json").write_text(json.dumps(summary, indent=2) + "\n")
    (out / "linked-game.json").write_text(json.dumps(linked, separators=(",", ":")))
    (out / "firmware-build.txt").write_text("\n".join(report) + "\n")
    print(f"RAM: {ram['used']}/{ram['limit']} words, {ram['free']} free (+ {ram['glue_reserved']} glue, {ram['framebuffer']} framebuffer)")
    print(f"Demo code/data: {program['used']}/{program['limit']} far words")
    print(f"Full firmware: {rom['used']}/{rom['limit']} words ({len(image)} bytes)")
    print("Local build:", out / "NEK100_DSP_demo.bin")
    return summary


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--firmware", type=Path, default=ROOT.parent / "NEK100_DSP_V1.0.7.bin")
    p.add_argument("--extra", nargs="*", default=["battery_percent"],
                   help="optional nek100-mod patches to add (default: battery_percent; --extra alone: none)")
    p.add_argument("--sfx", choices=["shot", "drums"], default="shot",
                   help="effects: the GM gunshot (program 127, soundbank slot 500) or the GM drums")
    p.add_argument("--silent", action="store_true", help="no music and no sound effects: the game sends nothing to the synth")
    p.add_argument("--wad", help="textures, sprites, music (default: wad/freedoom1.wad; DOOM1.WAD builds stay private)")
    p.add_argument("--map", help="the WAD whose E1M1 is played (default: maps/hangar.wad), e.g. DOOM1.WAD for id's")
    args = p.parse_args()
    wad.use(args.wad, args.map)
    if not wad.shareable():
        print(f"note: {Path(wad.WAD).name} / {Path(wad.MAP).name} are not free: keep this build private")
    doom.SFX_DRUMS = args.sfx == "drums"
    build(args.firmware, ROOT / "build", silent_audio=args.silent, extra=args.extra)
