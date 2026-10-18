import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
pytestmark = pytest.mark.skipif(not shutil.which("node") or not (ROOT / "wad" / "DOOM1.WAD").exists(),
                                reason="needs local WAD and node")


def test_demo_loop_and_runtime_ram(tmp_path):
    import webbuild
    webbuild.main([str(tmp_path / "game.json")])
    result = subprocess.run(["node", str(ROOT / "tests" / "game_check.cjs"), str(ROOT / "web" / "p16.js"),
                             str(tmp_path / "game.json")], capture_output=True, text=True, check=True)
    summary = json.loads(result.stdout)
    assert summary["ram"] <= 482
    assert summary["writes"] > 10000
    assert summary["peakDepth"] <= 20


def test_hard_memory_budget_rejections():
    import budget
    assert budget.check_ram(482)["free"] == 0
    with pytest.raises(ValueError, match="RAM budget"):
        budget.check_ram(483)
    with pytest.raises(ValueError, match="program budget"):
        budget.check_regions([("too much", budget.ROM_START, budget.ROM_END - budget.ROM_START + 1)])
    with pytest.raises(ValueError, match="overlap"):
        budget.check_regions([("code", budget.ROM_START, 100), ("data", budget.ROM_START + 50, 100)])
    with pytest.raises(ValueError, match="firmware exceeds"):
        budget.check_firmware(b"\0" * (budget.PARTITION_WORDS * 2 + 2))


def test_navigation_does_not_open_the_actual_map():
    import doommap
    import webbuild
    m = doommap.Map()
    before = list(m.sectors)
    program = webbuild.build_doom(m)
    assert m.sectors == before
    nav = program["navigation"]
    assert tuple(nav["route"][0]) == m.start()[:2]
    assert nav["target"] == 3  # Original easy soldier, beyond the first door.
    end, enemy = nav["route"][-1], m.enemies[nav["target"]]
    assert abs(end[0] - enemy[0]) + abs(end[1] - enemy[1]) == 64


def test_cooperative_render_keeps_input_live_and_rejects_full_frame_callback(tmp_path):
    import webbuild
    program = tmp_path / "game.json"
    webbuild.main([str(program)])
    script = r"""
const assert=require('node:assert/strict'),fs=require('fs');
const {P16,rayNatives}=require(process.argv[2]);
const p=JSON.parse(fs.readFileSync(process.argv[3]));
const m=new P16(p,rayNatives());m.call('__cc_init');m.call('rc_start');m.call('start_game');
assert(m.maxCallbackSteps.rc_start<50000);
m.wr(m.sym('game_visible'),0);m.call('frame');
const fb=p.mmio.framebuffer,expected=Array.from(m.ram.slice(fb,fb+1024));
const y=m.get('py'),epoch=m.get('nframe');m.call('frame_begin');m.call('rc_key',49,100);
for(let tick=1;m.get('nframe')===epoch;tick++){
 assert(tick<600,'render must finish');const us=tick*10000;
 m.wr(p.mmio.clock_lo,us&65535);m.wr(p.mmio.clock_hi,Math.floor(us/65536));
 m.call('rc_tick');assert.equal(m.get('callback_stage'),0);
}
assert.notEqual(m.get('py'),y,'input/physics must run between render slices');
assert.deepEqual(Array.from(m.ram.slice(fb,fb+1024)),expected,'the in-progress camera must stay fixed');
assert(m.maxCallbackSteps.rc_tick<=p.callback_limits.rc_tick);
// Reproduce the previous call shape: putting a whole frame in rc_start must fail the gate.
p.entry.rc_start=p.entry.frame;
assert.throws(()=>m.call('rc_start'),/budżet 50000/);
console.log(JSON.stringify(m.maxCallbackSteps));
"""
    path = tmp_path / "cooperative.cjs"; path.write_text(script)
    subprocess.run(["node", str(path), str(ROOT / "web" / "p16.js"), str(program)],
                   capture_output=True, text=True, check=True)


def test_actual_firmware_can_finish_e1m1(tmp_path):
    firmware = ROOT.parent / "NEK100_DSP_V1.0.7.bin"
    if not firmware.exists():
        pytest.skip("needs the local official NUX firmware")
    import builddemo
    import playthrough
    summary = builddemo.build(firmware, tmp_path)
    (tmp_path / "route.json").write_text(json.dumps(playthrough.route()))
    subprocess.run(["node", str(ROOT / "tools" / "playthrough.cjs"), str(ROOT / "web" / "p16.js"),
                    str(tmp_path / "linked-game.json"), str(tmp_path / "route.json")],
                   capture_output=True, text=True, check=True)
    result = json.loads((tmp_path / "playthrough-result.json").read_text())
    assert result["result"] == "WIN" and result["kills"] == 6 and result["health"] > 0
    assert summary["ram"]["used"] <= summary["ram"]["limit"]
    assert summary["firmware"]["used"] <= summary["firmware"]["limit"]
