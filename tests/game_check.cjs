"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const {P16, rayNatives} = require(process.argv[2]);
const p = JSON.parse(fs.readFileSync(process.argv[3]));
let peakDepth = 0, writes = 0;
function machine() {
  const m = new P16(p, rayNatives());
  m.writeGuard = (a) => {
    writes++;
    assert((a >= 0x6448 && a < 0x6448 + p.ram_words) || (a >= 0x662a && a < 0x6a2a) ||
      [0x6a50, 0x145, 0x6d78, 0x6d79].includes(a), "RAM spill at 0x" + a.toString(16));
  };
  m.call("__cc_init"); m.call("rc_start"); m.call("start_game");
  for (let i = 0; i < 4; i++) { m.wr(m.sym("enemy_state") + i, 0x7c00); m.wr(m.sym("pickup_bits") + i, 65535); }
  for (let i = 0; i < 2; i++) m.wr(m.sym("roster_bits") + i, 65535);     // no monster comes into the slots
  return m;
}
// The first zombie's record in the entities table (kind 1 in its low byte).
function zombie(m) {
  const at = m.get("map_hi", 8) * 65536 + m.get("map_lo", 8);
  for (let k = 0; ; k++) if ((m.farRead(at + 3 * k + 2) & 255) === 1) return k;
}
function set(m, x, y, z, a) {
  for (const [k, v] of Object.entries({px:x, py:y, pz:z, pa:a})) m.wr(m.sym(k), v);
}
function enemy(m, x, y, hp=20) {           // hp in points, stored in 2-point units
  m.wr(m.sym("enemy_x"), x); m.wr(m.sym("enemy_y"), y); m.wr(m.sym("enemy_state"), (zombie(m) << 10) | (hp >> 1));
}
function peak(m) { peakDepth = Math.max(peakDepth, m.maxCallDepth); }

// Exact analytic intersections, both cross-product signs and products wider than 16 bits.
{
 const m=machine(); let seed=17; const next=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed;};
 for(let i=0;i<100;i++) {
  const dx=((next()%125)-62)*16,dy=((next()%125)-62)*16,k=1+(next()%15);
  const ex=(next()%4095)-2047,ey=(next()%4095)-2047;
  if(!dx&&!dy || dx*ey===dy*ex)continue;
  m.wr(m.sym('ray_x'),0);m.wr(m.sym('ray_y'),0);m.wr(m.sym('ray_dx'),dx);m.wr(m.sym('ray_dy'),dy);
  assert.equal(m.call('ray_fraction',dx*k/16-ex,dy*k/16-ey,dx*k/16+ex,dy*k/16+ey),k*1024);
 }
 peak(m);
}

// Closed doors stop movement and bullets. Use raises the ceiling, then both pass.
{
  const m = machine(); set(m, 192, 280, 0, 64); enemy(m, 192, 400);
  assert.equal(m.call("can_move", 192, 336), 0);
  m.call("fire_game"); assert.equal(m.get("enemy_state") & 31, 10);
  m.call("rc_key",74,100); m.call("rc_key",74,0); m.call("game_tick");
  assert.equal(m.get("dynamic_open") & 1, 1, "a tap shorter than one frame still uses the door");
  m.call("dynamic_tick"); assert.equal(m.call("ray_clear",192,400,0),0, "a tiny door gap blocks sight");
  for (let i=0; i<16; i++) m.call("dynamic_tick");
  assert.equal(m.get("dynamic_height"), 108);
  assert.equal(m.call("can_move", 192, 336), 1);
  m.wr(m.sym("shot_cd"), 0); m.call("fire_game"); assert.equal(m.get("enemy_state") & 31, 5);
  m.wr(m.sym("shot_cd"), 0); m.call("fire_game"); assert.equal(m.get("enemy_state") & 31, 0);
  assert.equal(m.get("kills"), 1); assert.equal(m.get("ammo"), 47); peak(m);
}
// An opaque wall blocks hitscan, and empty ammo never damages a target.
{
  const m = machine(); set(m, 64, 160, 0, 128); enemy(m, -100, 160);
  m.call("fire_game"); assert.equal(m.get("enemy_state") & 31, 10);
  set(m, 192, 64, 0, 64); enemy(m, 192, 184); m.wr(m.sym("ammo"),0); m.wr(m.sym("shot_cd"),0);
  m.call("fire_game"); assert.equal(m.get("enemy_state") & 31, 10); peak(m);
}
// Pickups are persistent and do not grant their payload twice.
{
  const m = machine();
  const data = p.far.find(s => s.addr === (m.get("map_hi",8)*65536 + m.get("map_lo",8))).words;
  let e = 0; while (data[e*3+2] > 255) e++;       // the monsters' records carry skill flags in the high byte
  const i = Array.from({length:50}, (_,i)=>i).find(i => data[(e+i)*3+2] === 7);
  set(m, data[(e+i)*3], data[(e+i)*3+1],0,0); m.wr(m.sym("pickup_bits") + (i>>4), 65535 & ~(1 << (i&15)));
  m.wr(m.sym("ammo"),0); m.call("pickup_tick"); assert.equal(m.get("ammo"),10);
  m.call("pickup_tick"); assert.equal(m.get("ammo"),10); peak(m);
}
// Enemy attacks can kill the player. Enter opens the skill menu, fire there restarts all persistent state.
{
  const m = machine(); set(m,192,64,0,64); enemy(m,192,144);
  m.wr(m.sym("health"),8); m.call("game_tick"); assert.equal(m.get("game_mode"),1);
  assert.equal(m.get("health"),0);
  m.call("rc_key",23,100); m.call("rc_key",23,0); m.call("game_tick"); assert.equal(m.get("game_mode"),4);
  m.call("rc_key",72,100); m.call("rc_key",72,0); m.call("game_tick");
  assert.equal(m.get("game_mode"),0); assert.equal(m.get("health"),100); assert.equal(m.get("ammo"),50);
  for (let i = 0; i < 4; i++) { const st = m.get("enemy_state", i); assert((st & 31) || (st & 0x7c00) === 0x7c00, "no corpse left"); }
  assert.equal(m.get("pickup_bits"),0); peak(m);
}
// A short fire tap is latched until the next game frame.
{
  const m = machine(); m.call("rc_key",72,100); m.call("rc_key",72,0); m.call("game_tick");
  assert.equal(m.get("ammo"),49); peak(m);
}
// The actual exit switch ends the demo; Enter, then fire in the menu, recovers to the start.
{
  const m = machine(); set(m,-880,1712,-48,128); m.call("use_game");
  assert.equal(m.get("game_mode"),2); m.call("frame");
  m.call("rc_key",23,100); m.call("game_tick"); m.call("rc_key",23,0); assert.equal(m.get("game_mode"),4);
  m.call("rc_key",74,100); m.call("game_tick");
  assert.equal(m.get("game_mode"),0); assert.equal(m.get("px"),192); peak(m);
}
// The title waits for any key; the menu's cursor moves with forward/back, within the five skills.
{
  const m = new P16(p, rayNatives()); m.call("__cc_init"); m.call("rc_start");
  assert.equal(m.get("game_mode"),3); assert.equal(m.get("skill"),2);
  m.call("rc_key",50,100); m.call("game_tick"); m.call("rc_key",50,0); assert.equal(m.get("game_mode"),4);
  for (let k = 0; k < 3; k++) { m.call("rc_key",49,100); m.call("game_tick"); m.call("rc_key",49,0); m.call("game_tick"); }
  assert.equal(m.get("skill"),0);
  for (let k = 0; k < 6; k++) { m.call("rc_key",50,100); m.call("game_tick"); m.call("rc_key",50,0); m.call("game_tick"); }
  assert.equal(m.get("skill"),4); assert.equal(m.get("render_state"),6);
  m.call("rc_key",72,100); m.call("game_tick"); assert.equal(m.get("game_mode"),0); assert.equal(m.get("skill"),4);
  peak(m);
}
// Slots: on ultra-violence the zombie beyond the first door comes in first, the hangar's shotgun guy too; from the exit
// room they give way to nearer ones and go back to the roster.
{
  const m = new P16(p, rayNatives()); m.call("__cc_init"); m.call("rc_start");
  m.wr(m.sym("skill"), 3); m.call("start_game");
  const st = m.get("enemy_state", 0), k = (st >> 10) & 31;
  const met = (r) => m.get("roster_bits", r >> 4) & (1 << (r & 15));
  assert.equal(st & 31, 10, "a zombie: 20 points"); assert(met(k));
  assert(Array.from({length:4}, (_, i) => m.get("enemy_state", i) & 31).includes(15), "the shotgun guy by the stairs");
  set(m, -880, 1824, 0, 0); for (let n = 0; n < 4; n++) m.call("slot_tick");
  const moved = Array.from({length:4}, (_, i) => (m.get("enemy_state", i) >> 10) & 31);
  assert(moved.every(r => r !== 31), "the far end has its own monsters");
  assert(!moved.includes(k) && !met(k), "the far one was evicted, whole");
  peak(m);
}
assert(peakDepth <= 20, "call depth exceeds the hardware-characterized range");
console.log(JSON.stringify({peakDepth,writes,ram:p.ram_words,program:p.budget.program.used}));
