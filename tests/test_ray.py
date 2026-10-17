"""The raycaster (firmware/ray.c) in the simulator: frames stay in the framebuffer and C RAM, keys move."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOD = os.path.join(ROOT, "..", "nek100-mod")
pytestmark = pytest.mark.skipif(not os.path.isdir(MOD), reason="needs nek100-mod")
sys.path.insert(0, os.path.join(ROOT, "firmware"))
sys.path.insert(0, MOD)


class Watch(dict):
    def __init__(self, *a):
        super().__init__(*a)
        self.written = set()

    def __setitem__(self, k, v):
        self.written.add(k)
        super().__setitem__(k, v)


@pytest.fixture(scope="module")
def m():
    import ray
    m = ray.Machine(ray.compile_ray(ray.expected_selftest()))
    m.sim.ram = Watch({a: 0xBEEF for a in range(ray.RAM[0], ray.RAM[1])})
    m.call("__cc_init")
    m.call("rc_start")
    m.call("rc_tick")                         # stage 0: the self-test
    return m


def test_selftest_passes_in_the_simulator(m):
    import ray
    assert m.sim.rd(m.r.symbols["st_ok"]) == 1


def test_frame_writes_only_framebuffer_and_c_ram(m):
    import ray
    m.sim.ram.written.clear()
    m.call("frame")
    bad = [a for a in m.sim.ram.written
           if not (ray.RAM[0] <= a < ray.RAM[1] or m.fb <= a < m.fb + 1024 or a == 0x6a50)]
    assert not bad, [hex(a) for a in bad[:8]]
    assert m.sim.rd(0x6a50) & 1


def test_walls_and_view(m):
    """Facing +x from (1.5, 1.5): the far wall (x = 15) is small and solid in the middle, the near y wall on
    the left is a checkerboard, the block at (3..4, 2) is near on the right."""
    rows = m.screen().split("\n")
    col = lambda x: "".join(r[x] for r in rows)
    assert 0 < col(64).count("#") < 20
    left = col(20)
    assert "#.#" in left or ".#." in left
    assert col(120).count("#") > 40


def test_keys_turn_and_move(m):
    s = m.r.symbols
    pa0, px0 = m.sim.rd(s["pa"]), m.sim.rd(s["px"])
    m.call("rc_key", 52, 100)                 # E3: turn right
    m.call("frame")
    assert m.sim.rd(s["pa"]) == (pa0 + 4) & 255
    m.call("rc_key", 52, 0)
    m.call("rc_key", 49, 90)                  # C#3: forward
    m.call("frame")
    assert m.sim.rd(s["px"]) > px0
    m.call("rc_key", 49, 0)
    assert m.sim.rd(s["held"]) == 0


def test_walls_stop_the_player(m):
    s = m.r.symbols
    m.sim.wr(s["pa"], 128)                    # facing -x, the wall at x = 0
    m.call("rc_key", 51, 90)
    for _ in range(30):
        m.call("frame")
    m.call("rc_key", 51, 0)
    assert m.sim.rd(s["px"]) >= 256
