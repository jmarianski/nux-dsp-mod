"""The linked silent firmware must not call the instrument synthesizer."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = Path(os.environ.get("NEK100_FW") or ROOT.parent.parent / "NEK100_DSP_V1.0.7.bin")   # as builddemo's
pytestmark = pytest.mark.skipif(
    not shutil.which("node") or not FIRMWARE.exists(),
    reason="needs Node and the local official NUX firmware")


def test_linked_silent_firmware_emits_no_synth_messages(tmp_path):
    import builddemo

    summary = builddemo.build(FIRMWARE, tmp_path, silent_audio=True)
    (tmp_path / "check.cjs").write_text(r"""
const fs=require('node:fs');
const {P16,rayNatives}=require(process.argv[2]);
const p=JSON.parse(fs.readFileSync(process.argv[3]));
let synthMessages=0;
const m=new P16(p,rayNatives({synth:()=>synthMessages++}));
m.call('__cc_init');m.call('rc_start');m.call('start_game');
m.call('rc_key',72,100);m.call('game_tick');m.call('rc_key',72,0);
m.call('damage',250);m.call('mu_stop');
m.call('rc_key',23,100);m.call('game_tick');m.call('rc_key',23,0);   // dead: enter, the skill menu
m.call('rc_key',72,100);m.call('game_tick');                                // fire picks the skill
for(let i=1;i<=30;i++){
 const us=i*10000;m.wr(p.mmio.clock_lo,us&65535);m.wr(p.mmio.clock_hi,Math.floor(us/65536));
 m.call('rc_tick');
}
if(synthMessages!==0)throw Error('silent build sent '+synthMessages+' synth messages');
console.log(JSON.stringify({synthMessages,health:m.get('health'),gameMode:m.get('game_mode')}));
""")
    result = subprocess.run(["node", str(tmp_path / "check.cjs"), str(ROOT / "web" / "p16.js"),
                             str(tmp_path / "linked-game.json")], capture_output=True, text=True, check=True)
    observed = json.loads(result.stdout)
    assert observed["synthMessages"] == 0
    assert observed["health"] == 100 and observed["gameMode"] == 0
    assert summary["ram"]["used"] <= summary["ram"]["limit"]
