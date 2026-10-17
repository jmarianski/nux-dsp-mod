"""The hand-written P16 arithmetic (firmware/mathasm.py) against Python, run in the web emulator."""
import json
from pathlib import Path
import random
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
pytestmark = pytest.mark.skipif(not shutil.which("node") or not (ROOT / "wad" / "DOOM1.WAD").exists(),
                                reason="needs local WAD and node")

SCRIPT = r"""
const fs=require('fs');const {P16,rayNatives}=require(process.argv[2]);
const p=JSON.parse(fs.readFileSync(process.argv[3]));const cases=JSON.parse(fs.readFileSync(process.argv[4]));
const m=new P16(p,rayNatives());m.call('__cc_init');
const out=cases.map(([f,a,b,c])=>{if(f==='screen_y')m.wr(m.sym('eye'),c&65535);
  const r=f==='screen_y'?m.call(f,a&65535,b&65535):m.call(f,a&65535,b&65535,c&65535);
  return f==='umul32'||f==='smul32'?[m.get('prod_hi'),m.get('prod_lo')]:[r&65535];});
console.log(JSON.stringify(out));
"""


def trunc_div(a, b):
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def expected(f, a, b, c):
    if f == "umul32":
        v = (a & 0xFFFF) * (b & 0xFFFF)
        return [v >> 16, v & 0xFFFF]
    if f == "smul32":
        v = (a * b) & 0xFFFFFFFF
        return [v >> 16, v & 0xFFFF]
    if f == "screen_y":
        q = max(-1000, min(1000, ((a - c) * b) >> 13))
        return [(32 - q) & 0xFFFF]
    if f == "fmul":
        return [trunc_div(a * b, 256) & 0xFFFF]
    if not c:
        return [0]
    q = abs(a * b) // abs(c)
    q = min(q, 32767)
    return [(-q if (a * b < 0) != (c < 0) else q) & 0xFFFF]


def test_math_matches_python(tmp_path):
    import webbuild
    rnd = random.Random(1)
    edge = [0, 1, -1, 2, 255, 256, -256, 32767, -32767, -32768, 8192, 17, -17, 100, -1000]
    vals = lambda: rnd.choice(edge) if rnd.random() < 0.3 else rnd.randint(-32768, 32767)
    cases = []
    for _ in range(600):
        a, b, c = vals(), vals(), vals()
        small = rnd.randint(-256, 256)
        cases += [["umul32", a & 0xFFFF, b & 0xFFFF, 0], ["smul32", a, b, 0], ["fmul", a, b, 0], ["muldiv", a, b, c],
                  ["fmul", a, small, 0]]
    for _ in range(3000):                       # muldiv: every quotient length (its 0/4/8/12/16-step paths)
        c = rnd.choice([1, 2, 3, 17, 255, 256, 1000, 32767, rnd.randint(1, 32767)]) * rnd.choice([1, -1])
        q = rnd.randint(0, (1 << rnd.randint(0, 16)) - 1)
        b = rnd.choice([1, 2, 64, 255, 256, 8192, rnd.randint(1, 32767)])
        a = max(-32768, min(32767, (q * abs(c) + rnd.randint(0, abs(c) - 1)) // b)) * rnd.choice([1, -1])
        cases.append(["muldiv", a, b * rnd.choice([1, -1]), c])
    for _ in range(1500):                       # screen_y(h, s) with eye: near and far heights, scales up to NEAR's
        eye = rnd.randint(-200, 300)
        h = eye + (rnd.randint(-255, 255) if rnd.random() < 0.8 else rnd.randint(-2000, 2000))
        cases.append(["screen_y", h, rnd.choice([0, 1, 8191, 8192, 30840, 32767, rnd.randint(0, 32767)]), eye])
    prog = tmp_path / "game.json"
    prog.write_text(json.dumps(webbuild.build_doom()))
    (tmp_path / "cases.json").write_text(json.dumps(cases))
    (tmp_path / "m.cjs").write_text(SCRIPT)
    got = json.loads(subprocess.run(["node", str(tmp_path / "m.cjs"), str(ROOT / "web" / "p16.js"), str(prog),
                                     str(tmp_path / "cases.json")], capture_output=True, text=True, check=True).stdout)
    bad = [(c, g, expected(*c)) for c, g in zip(cases, got) if g != expected(*c)]
    assert not bad, bad[:5]
