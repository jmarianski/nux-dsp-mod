/* Actual C gameplay replay through hardware callbacks, with a per-callback work limit. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {P16,rayNatives} = require(require('node:path').resolve(process.argv[2]));
const p = JSON.parse(fs.readFileSync(process.argv[3]));
const path = JSON.parse(fs.readFileSync(process.argv[4]));
const m = new P16(p,rayNatives());
let frames=0, attempts=0, ticks=0;
m.writeGuard = a => assert((a>=0x6448&&a<0x6448+p.ram_words)||(a>=0x662a&&a<0x6a2a)||[0x6a50,0x145,0x6d78,0x6d79].includes(a),'RAM spill '+a.toString(16));
m.call('__cc_init');m.call('rc_start');m.call('start_game');
const s=v=>v&32768?v-65536:v;
const pos=()=>[s(m.get('px')),s(m.get('py'))];
function tick(n=1) {
 for(let i=0;i<n;i++) {
  const epoch=m.get('logic_epoch');let waited=0;
  while(m.get('logic_epoch')===epoch){
   assert(++waited<=4,'logic did not advance');
   const us=++ticks*10000;m.wr(p.mmio.clock_lo,us&65535);m.wr(p.mmio.clock_hi,Math.floor(us/65536)&65535);
   m.call('rc_tick');assert.equal(m.get('callback_stage'),0,'callback did not return');
  }
  frames++;assert.equal(m.get('game_mode'),0,'died at '+pos());
 }
}
function key(note,on){m.call('rc_key',note,on?100:0);}
function turn(a) {
 for(let i=0;m.get('pa')!==a;i++) {
  assert(i<65,'cannot turn');const d=(a-m.get('pa')+256)&255;const note=d<128?48:52;
  key(note,true);tick();key(note,false);
 }
}
function use() {key(74,true);tick();key(74,false);tick();}
function combat() {
 for(let retry=0;retry<4;retry++) {
  let best=-1, distance=641;
  for(let i=0;i<4;i++) if(m.get('enemy_state',i)&31) {
   const d=Math.abs(s(m.get('enemy_x',i))-pos()[0])+Math.abs(s(m.get('enemy_y',i))-pos()[1]);
   if(d<distance&&m.call('ray_clear',m.get('enemy_x',i),m.get('enemy_y',i),0)){best=i;distance=d;}
  }
  if(best<0)return;
  let a=Math.round(Math.atan2(s(m.get('enemy_y',best))-pos()[1],s(m.get('enemy_x',best))-pos()[0])*128/Math.PI/4)*4;
  a=(a+256)&255;turn(a);key(72,true);
  for(let k=0;k<70&&(m.get('enemy_state',best)&31);k++)tick();
  key(72,false);
 }
}
for(let i=1;i<path.length;i++) {
 const target=path[i];combat();
 for(let retry=0;pos()[0]!==target[0]||pos()[1]!==target[1];retry++) {
  assert(retry<8,'stuck at '+pos()+' target '+target+' health '+m.get('health'));
  const [x,y]=pos();const a=target[0]>x?0:target[0]<x?128:target[1]>y?64:192;turn(a);
  const before=pos();key(49,true);tick();key(49,false);attempts++;
  if(pos()[0]===before[0]&&pos()[1]===before[1]){use();tick(12);combat();}
 }
 if(i%80===0) console.log('walk',i,'/',path.length-1,'health',m.get('health'),'kills',m.get('kills'));
}
turn(128);key(74,true);
const epoch=m.get('logic_epoch');
while(m.get('logic_epoch')===epoch){const us=++ticks*10000;m.wr(p.mmio.clock_lo,us&65535);m.wr(p.mmio.clock_hi,Math.floor(us/65536)&65535);m.call('rc_tick');}
key(74,false);
assert.equal(m.get('game_mode'),2,'exit switch did not finish demo');
assert(m.get('health')>0);assert(m.maxCallDepth<=20);
const summary={result:'WIN',position:pos(),health:m.get('health'),ammo:m.get('ammo'),kills:m.get('kills'),gameFrames:frames,walkingAttempts:attempts,ramWords:p.ram_words,maxCallDepth:m.maxCallDepth,renderedFrames:m.get('nframe'),callbackPeaks:m.maxCallbackSteps};
fs.writeFileSync(require('node:path').join(require('node:path').dirname(process.argv[4]),'playthrough-result.json'),JSON.stringify(summary,null,2));
console.log(JSON.stringify(summary));
