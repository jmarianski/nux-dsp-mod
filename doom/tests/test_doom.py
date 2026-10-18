"""Run the compiled 16-bit map renderer, comparing every pixel to the Python reference.

The WAD (Freedoom, or a local DOOM1.WAD) is not a fixture in git. These tests skip without it.
"""
import json
from pathlib import Path
import random
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import wad  # noqa: E402
pytestmark = pytest.mark.skipif(
    not Path(wad.WAD).exists() or not shutil.which("node"), reason="needs local WAD and node")

POSITIONS = [(192, 64, a) for a in (0, 32, 64, 96, 128, 192, 235)] + [
    # Stairs into the hangar, the skylight over the pool, crates, the lift and the balcony above.
    (192, 600, 64), (-300, 780, 30), (300, 760, 100), (400, 900, 50), (-200, 1300, 220), (560, 1200, 64),
    # First door, both faces, oblique and near-plane clipped; the other doors, the gate and the exit switch.
    (192, 280, 64), (192, 380, 192), (150, 300, 50), (200, 310, 70),
    (-380, 1104, 128), (-560, 1000, 100), (-720, 1500, 192), (-720, 1500, 64), (-720, 1700, 128)]

NODE = r"""
const {P16, rayNatives} = require(process.argv[2]);
const fs = require('fs');
const p = JSON.parse(fs.readFileSync(process.argv[3]));
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const m = new P16(p, rayNatives());
m.call('__cc_init'); m.call('rc_start');m.call('start_game');
m.wr(p.symbols.game_visible, 0);
const arithmetic = input.math.map(([fn, ...args]) => {
  const ret = m.call(fn, ...args);
  return [ret, m.get('prod_hi'), m.get('prod_lo')];
});
const frames = input.positions.map(([x, y, a, z]) => {
  m.wr(p.symbols.px, x); m.wr(p.symbols.py, y); m.wr(p.symbols.pa, a);
  m.wr(p.symbols.pz, z);
  const before = m.steps;
    m.call('frame');
  return {fb: Array.from(m.ram.slice(p.mmio.framebuffer, p.mmio.framebuffer + 1024)), steps: m.steps - before};
});
process.stdout.write(JSON.stringify({arithmetic, frames, ram: p.ram_words}));
"""


@pytest.fixture(scope="module")
def compiled(tmp_path_factory):
    import webbuild
    import doommap
    d = tmp_path_factory.mktemp("doom")
    webbuild.main([str(d / "game.json")])
    (d / "run.js").write_text(NODE)
    rng = random.Random(0xD00D)
    math = [["umul32", a, b] for a, b in [(0, 65535), (65535, 65535), (32768, 32768)] + [
        (rng.randrange(65536), rng.randrange(65536)) for _ in range(80)]]
    math += [["smul32", a, b] for a, b in [(-32768, -32768), (-32768, 32767), (-1, 1)] + [
        (rng.randint(-32768, 32767), rng.randint(-32768, 32767)) for _ in range(80)]]
    math += [["muldiv", a, b, c] for a, b, c in [(8192, 64, 17), (-10, 10, 0), (32767, 32767, 1)] + [
        (rng.randint(-32768, 32767), rng.randint(-32768, 32767), rng.randint(-32768, 32767)) for _ in range(80)]]
    m = doommap.Map()
    positions = [(*pos, m.sectors[doommap.find_sector(m, *pos[:2])][0]) for pos in POSITIONS]
    result = subprocess.run(["node", str(d / "run.js"), str(ROOT / "web" / "p16.js"), str(d / "game.json")],
                            input=json.dumps({"math": math, "positions": positions}),
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout), math


def test_products_and_division(compiled):
    import doommap
    out, math = compiled
    for (fn, a, b, *rest), (ret, hi, lo) in zip(math, out["arithmetic"]):
        if fn in ("umul32", "smul32"):
            assert hi * 65536 + lo == (a * b) & 0xffffffff, (fn, a, b, hi, lo)
        else:
            c = rest[0]
            expected = max(-32767, min(32767, doommap.muldiv(a, b, c)))
            assert ret == expected & 0xffff, (fn, a, b, c, ret, expected)


@pytest.mark.parametrize("index,pos", list(enumerate(POSITIONS)))
def test_bsp_pixels_match_reference(compiled, index, pos):
    import doommap
    out, _ = compiled
    fb = doommap.Renderer(doommap.Map()).frame(*pos)
    packed = [sum(fb[p * 8 + bit][x] << bit for bit in range(8)) for p in range(7) for x in range(128)]
    diff = [i for i, (a, b) in enumerate(zip(packed, out["frames"][index]["fb"][:896])) if a != b]  # page 7: HUD
    assert not diff, (pos, len(diff), diff[:20])


def test_fits_the_pianos_free_ram(compiled):
    assert compiled[0]["ram"] <= 0x662a - 0x6448


@pytest.mark.parametrize("height", [0, 24, 60])
def test_door_texture_at_partial_openings(tmp_path, height):
    import doommap
    import webbuild
    m = doommap.Map()
    # Test moving geometry independently of AI/HUD. The browser check also uses F.
    sec = m.dynamics[0][0]
    floor, _ceiling, light = m.sectors[sec]
    m.sectors[sec] = floor, height, light
    program = tmp_path / "game.json"
    program.write_text(json.dumps(webbuild.build_doom(m)))
    script = tmp_path / "run.js"; script.write_text(NODE)
    pos = (192, 280, 64)
    result = subprocess.run(["node", str(script), str(ROOT / "web" / "p16.js"), str(program)],
                            input=json.dumps({"math": [], "positions": [[*pos, 0]]}),
                            capture_output=True, text=True, check=True)
    fb = doommap.Renderer(m).frame(*pos)
    expected = [sum(fb[p * 8 + bit][x] << bit for bit in range(8)) for p in range(7) for x in range(128)]
    assert json.loads(result.stdout)["frames"][0]["fb"][:896] == expected     # page 7: the HUD's, scratch until then
