"""The browser emulator (web/p16.js, in node) runs the predecoded program exactly as the Python simulator does."""
import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOD = os.path.join(ROOT, "..")   # nek100-mod, this directory's parent
pytestmark = [pytest.mark.skipif(not os.path.isdir(MOD), reason="needs nek100-mod"),
              pytest.mark.skipif(not shutil.which("node"), reason="needs node")]
sys.path.insert(0, os.path.join(ROOT, "firmware"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, MOD)

NODE = r"""
const { P16, rayNatives } = require(process.argv[2]);
const prog = JSON.parse(require("fs").readFileSync(process.argv[3]));
const markers = [], notes = [];
const m = new P16(prog, rayNatives({ trace: (v) => markers.push(v), synth: (s, a, b) => notes.push([s, a, b]) }));
m.wr(prog.mmio.dev_vol, 10);
m.call("__cc_init");
m.call("rc_start");
for (let t = 0; t < 70; t++) { m.wr(prog.mmio.clock_lo, (t * 10000) & 0xffff); m.call("rc_tick"); }
const s = prog.symbols;
const out = { stage: m.rd(s.stage), st_ok: m.rd(s.st_ok), fmode: m.rd(s.fmode), markers: markers.slice(0, 80) };
m.call("rc_key", 52, 100);
m.call("frame");
m.call("rc_key", 52, 0);
m.call("rc_key", 49, 90);
for (let k = 0; k < 5; k++) m.call("frame");
out.fb = Array.from(m.ram.slice(prog.mmio.framebuffer, prog.mmio.framebuffer + 1024));
out.pos = [m.rd(s.px), m.rd(s.py), m.rd(s.pa)];
out.notes = notes.length;
process.stdout.write(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def web(tmp_path_factory):
    import webbuild
    d = tmp_path_factory.mktemp("web")
    webbuild.main(["--engine", "ray", str(d / "game.json")])
    (d / "run.js").write_text(NODE)
    out = subprocess.run(["node", str(d / "run.js"), os.path.join(ROOT, "web", "p16.js"), str(d / "game.json")],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def test_startup_reaches_the_game(web):
    assert web["stage"] == 2 and web["st_ok"] == 1 and web["fmode"] == 0
    assert web["markers"][0] == 0x2000                    # the first dv marker
    assert 0x301 in web["markers"]                        # self-test ok


def test_frames_match_the_python_simulator(web):
    import ray
    m = ray.Machine(ray.compile_ray(ray.expected_selftest()))
    m.call("__cc_init")
    m.call("rc_start")
    m.sim.wr(m.r.symbols["st_ok"], 1)                    # the emulator ran the self-test; no number under fps
    m.call("rc_key", 52, 100)
    m.call("frame")
    m.call("rc_key", 52, 0)
    m.call("rc_key", 49, 90)
    for _ in range(5):
        m.call("frame")
    s = m.r.symbols
    assert web["pos"] == [m.sim.rd(s["px"]), m.sim.rd(s["py"]), m.sim.rd(s["pa"])]
    fb = [m.sim.rd(m.fb + k) for k in range(1024)]
    # the top-left number is the fps counter, which only the emulator's clock moved
    diff = [k for k in range(1024) if fb[k] != web["fb"][k] and not (k < 12)]
    assert not diff, diff[:8]


def test_hardware_multiply_is_one_word():
    import webbuild
    op, a, b, n = webbuild.decode_word({0: 0xd4ce, 1: 0xd1ca}, 0)
    assert (webbuild.OPS[op], a, n) == ("mul", 6, 1)
