"""Collision contracts on synthetic rooms and the compiled map's blockmap.

The Python oracle scans every line; the P16 program uses the generated far index.
Synthetic rooms characterize radius, diagonal walls, headroom and stair limits.
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
pytestmark = pytest.mark.skipif(not shutil.which("node") or not Path(wad.WAD).exists(),
                                reason="needs local WAD and node")

NODE = r"""
const {P16, rayNatives} = require(process.argv[2]);
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const m = new P16(input.program, rayNatives());
m.call('__cc_init'); m.natives.fr_init(m);
function set(x, y, z, a = 0) {
  for (const [k, v] of Object.entries({px:x, py:y, pz:z, pa:a})) m.wr(m.sym(k), v);
}
function signed(v) { return v & 0x8000 ? v - 65536 : v; }
const positions = input.positions.map(([x, y, z]) => {
  set(x, y, z);
  return m.call('can_move', x, y) ? signed(m.get('move_floor')) : null;
});
const moves = input.moves.map(({start, deltas}) => {
  set(...start);
  return deltas.map(([dx, dy]) => {
    m.call('move_player', dx, dy);
    return ['px', 'py', 'pz'].map((k) => signed(m.get(k)));
  });
});
set(0,0,0);
function steer(held) {
  set(0,0,0); m.wr(m.sym('held'), held); m.call('steer');
  return [signed(m.get('px')), signed(m.get('py'))];
}
process.stdout.write(JSON.stringify({positions, moves}));
"""


def room(step=0, ceiling=128, blocking=False, diagonal=False):
    import doommap
    m = doommap.Map.__new__(doommap.Map)
    m.vertices = [(-256, -128), (256, -128), (256, 128), (-256, 128)]
    m.nodes = [(0, 0, 0, 256, 0x8000, 0x8001)]
    m.bounds = [(128, -128, 0, 256, 128, -128, -256, 0)]
    m.root = 0
    m.subsecs = [(0, 0, 1), (0, 0, 0)]
    m.segs = []
    m.wall_surfaces = {}; m.wall_textures = {}; m.texture_heights = {}
    m.sky = [[0] * 128 for _ in range(64)]; m.flat_grays = [0, 0]
    m.sectors = [(0, 128, 160), (step, ceiling, 160)]
    m.things = [(-128, 0, 0, 1, 7)]
    m.collision = [(*m.vertices[i], *m.vertices[(i + 1) % 4], 0, 0xffff) for i in range(4)]
    m.collision.append((-64 if diagonal else 0, -128, 64 if diagonal else 0, 128, 0,
                        0xffff if blocking else 1))
    m.block_info, m.blockmap = doommap.collision_grid(m.collision)
    return m


def run(m, positions=(), moves=()):
    import webbuild
    result = subprocess.run(["node", "-e", NODE, "unused", str(ROOT / "web" / "p16.js")],
                            input=json.dumps({"program": webbuild.build_doom(m), "positions": positions, "moves": moves}),
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


@pytest.mark.parametrize("step,ceiling,blocking,expected", [
    (0, 128, False, 0), (24, 128, False, 24), (25, 128, False, None),
    (0, 56, False, 0), (0, 55, False, None), (0, 0, False, None), (0, 128, True, None)])
def test_portal_step_and_headroom(step, ceiling, blocking, expected):
    m = room(step, ceiling, blocking)
    # The centre is still on the near side: clearance must cover the entire player box.
    assert run(m, positions=[(-8, 0, 0)])["positions"] == [expected]


def test_radius_and_contact_with_a_wall():
    m = room(blocking=True)
    positions = [(-16, 0, 0), (-15, 0, 0), (-240, 0, 0), (-241, 0, 0), (-128, 112, 0), (-128, 113, 0)]
    assert run(m, positions)["positions"] == [0, None, 0, None, 0, None]


def test_thin_walls_and_sliding():
    out = run(room(blocking=True), moves=[
        {"start": [-24, 0, 0], "deltas": [[64, 0]]},
        {"start": [-24, 0, 0], "deltas": [[48, 24]]}])
    assert out["moves"] == [[[-16, 0, 0]], [[-16, 24, 0]]]


def test_climb_then_descend():
    out = run(room(step=24), moves=[{"start": [-24, 0, 0], "deltas": [[48, 0], [-48, 0]]}])
    assert out["moves"] == [[[24, 0, 24], [-24, 0, 0]]]


def test_diagonal_and_endpoint_collision():
    import doommap
    m = room(blocking=True, diagonal=True)
    positions = [(x, y, 0) for x in range(-100, 101, 5) for y in (-112, -64, 0, 64, 112)]
    expected = [doommap.position_floor(m, *p) for p in positions]
    assert run(m, positions)["positions"] == expected
    assert expected[positions.index((-40, 0, 0))] == 0
    assert expected[positions.index((0, 0, 0))] is None


def test_map_index_matches_all_linedefs():
    import doommap
    m = doommap.Map()
    rng = random.Random(0xc0111de)
    positions = []
    # Most samples are near geometry or grid boundaries, where omissions are visible.
    for x1, y1, x2, y2, _f, _b in m.collision:
        x, y = (x1 + x2) // 2 + rng.randint(-20, 20), (y1 + y2) // 2 + rng.randint(-20, 20)
        positions.append((x, y, m.sectors[doommap.find_sector(m, x, y)][0]))
    xs, ys = [v[0] for v in m.vertices], [v[1] for v in m.vertices]
    for _ in range(150):
        x, y = rng.randrange(min(xs), max(xs) + 1), rng.randrange(min(ys), max(ys) + 1)
        positions.append((x, y, m.sectors[doommap.find_sector(m, x, y)][0]))
    expected = [doommap.position_floor(m, *p) for p in positions]
    assert run(m, positions)["positions"] == expected
