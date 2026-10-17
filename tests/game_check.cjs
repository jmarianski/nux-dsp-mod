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
  m.call("__cc_init"); m.call("rc_start");
  for (let i = 0; i < 4; i++) { m.wr(m.sym("enemy_state") + i, 0); m.wr(m.sym("pickup_bits") + i, 65535); }
  return m;
}
function set(m, x, y, z, a) {
  for (const [k, v] of Object.entries({px:x, py:y, pz:z, pa:a})) m.wr(m.sym(k), v);
}
function enemy(m, x, y, hp=20) {
  m.wr(m.sym("enemy_x"), x); m.wr(m.sym("enemy_y"), y); m.wr(m.sym("enemy_state"), hp);
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
  const m = machine(); set(m, 1488, -2496, 0, 0); enemy(m, 1600, -2496);
  assert.equal(m.call("can_move", 1544, -2496), 0);
  m.call("fire_game"); assert.equal(m.get("enemy_state") & 127, 20);
  m.call("rc_key",74,100); m.call("rc_key",74,0); m.call("game_tick");
  assert.equal(m.get("dynamic_open") & 1, 1, "a tap shorter than one frame still uses the door");
  m.call("dynamic_tick"); assert.equal(m.call("ray_clear",1600,-2496,0),0, "a tiny door gap blocks sight");
  for (let i=0; i<12; i++) m.call("dynamic_tick");
  assert.equal(m.get("dynamic_height"), 68);
  assert.equal(m.call("can_move", 1544, -2496), 1);
  m.wr(m.sym("shot_cd"), 0); m.call("fire_game"); assert.equal(m.get("enemy_state") & 127, 10);
  m.wr(m.sym("shot_cd"), 0); m.call("fire_game"); assert.equal(m.get("enemy_state") & 127, 0);
  assert.equal(m.get("kills"), 1); assert.equal(m.get("ammo"), 47); peak(m);
}
// An opaque wall blocks hitscan, and empty ammo never damages a target.
{
  const m = machine(); set(m, 1056, -3616, 0, 64); enemy(m, 1056, -2800);
  m.call("fire_game"); assert.equal(m.get("enemy_state") & 127, 20);
  enemy(m, 1056, -3496); m.wr(m.sym("ammo"),0); m.wr(m.sym("shot_cd"),0);
  m.call("fire_game"); assert.equal(m.get("enemy_state") & 127, 20); peak(m);
}
// Pickups are persistent and do not grant their payload twice.
{
  const m = machine();
  const data = p.far.find(s => s.addr === (m.get("map_hi",8)*65536 + m.get("map_lo",8))).words;
  const i = Array.from({length:50}, (_,i)=>i).find(i => data[(4+i)*3+2] === 7);
  set(m, data[(4+i)*3], data[(4+i)*3+1],0,0); m.wr(m.sym("pickup_bits") + (i>>4), 65535 & ~(1 << (i&15)));
  m.wr(m.sym("ammo"),0); m.call("pickup_tick"); assert.equal(m.get("ammo"),10);
  m.call("pickup_tick"); assert.equal(m.get("ammo"),10); peak(m);
}
// Enemy attacks can kill the player. Enter restarts all persistent state.
{
  const m = machine(); set(m,1056,-3616,0,64); enemy(m,1056,-3536);
  m.wr(m.sym("health"),8); m.call("game_tick"); assert.equal(m.get("game_mode"),1);
  assert.equal(m.get("health"),0);
  m.call("rc_key",23,100); m.call("rc_key",23,0); m.call("game_tick");
  assert.equal(m.get("game_mode"),0); assert.equal(m.get("health"),100); assert.equal(m.get("ammo"),50);
  assert(m.get("enemy_state") & 127); assert.equal(m.get("pickup_bits"),0); peak(m);
}
// A short fire tap is latched until the next game frame.
{
  const m = machine(); m.call("rc_key",72,100); m.call("rc_key",72,0); m.call("game_tick");
  assert.equal(m.get("ammo"),49); peak(m);
}
// The actual E1M1 exit switch ends the demo and Enter recovers to the start.
{
  const m = machine(); set(m,2960,-4768,-24,128); m.call("use_game");
  assert.equal(m.get("game_mode"),2); m.call("frame");
  m.call("rc_key",23,100); m.call("game_tick");
  assert.equal(m.get("game_mode"),0); assert.equal(m.get("px"),1056); peak(m);
}
assert(peakDepth <= 20, "call depth exceeds the hardware-characterized range");
console.log(JSON.stringify({peakDepth,writes,ram:p.ram_words,program:p.budget.program.used}));
