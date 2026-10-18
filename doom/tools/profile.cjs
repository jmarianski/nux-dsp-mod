/* Where the instructions go, in the emulator (its timing matched the piano: 1.3 fps both).

   node tools/profile.cjs [--seconds 10] [--frames] [PROGRAM.json]

   Default: N seconds of real callbacks (rc_tick every 10 ms, as the firmware calls it) while walking and turning,
   reported as instructions per second by stage (music / logic / render) and by C function (self instructions),
   the worst tick, firmware calls (farcopy, synth) and frames per second.
   --frames: whole frames from a few fixed E1M1 views instead (the renderer alone). */
const fs = require('node:fs');
const path = require('node:path');
const {P16, rayNatives} = require(path.join(__dirname, '..', 'web', 'p16.js'));

const args = process.argv.slice(2);
const opt = k => { const i = args.indexOf(k); if (i < 0) return null; const v = args[i + 1]; args.splice(i, 2); return v; };
const seconds = +(opt('--seconds') || 10);
const framesMode = args.includes('--frames') && args.splice(args.indexOf('--frames'), 1);
const file = args[0] || path.join(__dirname, '..', 'web', 'build', 'game.json');
const p = JSON.parse(fs.readFileSync(file));

const natives = rayNatives();
const fw = {farcopy: 0, farWords: 0, synth: 0};
const nf = natives.farcopy, ns = natives.synth;
natives.farcopy = m => { fw.farcopy++; fw.farWords += m.get('fr_n'); nf(m); };
natives.synth = m => { fw.synth++; ns(m); };
const m = new P16(p, natives);
m.wr(0x145, 10);
m.call('__cc_init'); m.call('rc_start');m.call('start_game');
if (p.callback_limits) p.callback_limits.rc_tick = 1e9;     /* measure, do not stop */
m.profile = new Uint32Array(p.code.op.length);

const fns = Object.entries(p.functions).filter(([k]) => !k.startsWith('game.')).sort((a, b) => a[1] - b[1]);
function bySelf(profile) {
  const self = {};
  let k = 0;
  for (let i = 0; i < profile.length; i++) {
    if (!profile[i]) continue;
    const pc = p.code.start + i;
    while (k + 1 < fns.length && fns[k + 1][1] <= pc) k++;
    self[fns[k][0]] = (self[fns[k][0]] || 0) + profile[i];
  }
  return self;
}
const calls = f => m.profile[p.functions[f] - p.code.start] || 0;
const table = (self, total, div, unit) => {
  for (const [f, n] of Object.entries(self).sort((a, b) => b[1] - a[1]).slice(0, 25)) {
    const c = calls(f);
    console.log('  ' + f.padEnd(20), String(Math.round(n / div)).padStart(9), unit,
                (100 * n / total).toFixed(1).padStart(5) + '%', c ? ('calls ' + Math.round(c / div) + ', ' + Math.round(n / c) + ' each') : '');
  }
};

/* Calls of the costly helpers by calling function: the execution count of each call instruction. */
function callSites(div, unit) {
  const CALL = p.ops.indexOf('call');
  const owner = pc => { let f = fns[0][0]; for (const [n, a] of fns) { if (a > pc) break; f = n; } return f; };
  for (const callee of ['muldiv', 'screen_y', 'fmul', 'smul32', 'readmap']) {
    const at = p.functions[callee], sites = {};
    if (at === undefined) continue;
    for (let i = 0; i < p.code.op.length; i++)
      if (p.code.op[i] === CALL && p.code.b[i] === at && m.profile[i]) {
        const o = owner(p.code.start + i);
        sites[o] = (sites[o] || 0) + m.profile[i];
      }
    console.log('calls of ' + callee + ':', Object.entries(sites).sort((a, b) => b[1] - a[1])
      .map(([f, n]) => f + ' ' + Math.round(n / div)).join(', '), unit);
  }
}

if (framesMode) {
  const views = [[m.get('px'), m.get('py'), m.get('pa')], [1056, -3400, 64], [1200, -3200, 0], [2000, -2900, 128]];
  const s0 = m.steps;
  for (const [x, y, a] of views) {
    m.wr(m.sym('px'), x & 0xffff); m.wr(m.sym('py'), y & 0xffff); m.wr(m.sym('pa'), a);
    m.call('frame');
  }
  const total = m.steps - s0;
  console.log('renderer alone:', Math.round(total / views.length), 'instructions a frame');
  table(bySelf(m.profile), total, views.length, '/frame');
  callSites(views.length, '/frame');
  process.exit(0);
}

/* Real callbacks: walk forward with a turn now and then, as a player would. */
const stage = {music: 0, 'logic tick': 0, 'render tick': 0};   /* a logic tick renders too, with what the logic left */
let worst = 0, worstKind = '', t = 0;
const ticks = seconds * 100, f0 = m.get('nframe'), s0 = m.steps;
const key = (n, on) => m.call('rc_key', n, on ? 100 : 0);
for (; t < ticks; t++) {
  if (t % 300 === 0) key(49, true);                         /* forward */
  if (t % 300 === 200) { key(49, false); key(52, true); }   /* turn */
  if (t % 300 === 260) key(52, false);
  const us = (t + 1) * 10000;
  m.wr(p.mmio.clock_lo, us & 0xffff); m.wr(p.mmio.clock_hi, Math.floor(us / 65536) & 0xffff);
  const epoch = m.get('logic_epoch'), before = m.steps;
  const mus0 = m.profile.slice(0);   /* cheap enough at 1000 ticks */
  m.call('rc_tick');
  const n = m.steps - before;
  const kind = m.get('logic_epoch') !== epoch ? 'logic tick' : 'render tick';
  /* music share of this tick: instructions inside the music functions */
  let mus = 0;
  for (const f of ['mu_clock', 'mu_tick', 'mword', 'mu_volumes', 'mu_scale']) {
    if (p.functions[f] === undefined) continue;
    const lo = p.functions[f] - p.code.start;
    const nxt = fns.find(([, a]) => a > p.functions[f]);
    const hi = (nxt ? nxt[1] : p.code.start + m.profile.length) - p.code.start;
    for (let i = lo; i < hi; i++) mus += m.profile[i] - mus0[i];
  }
  stage.music += mus; stage[kind] += n - mus;
  if (n > worst) { worst = n; worstKind = kind; }
}
const total = m.steps - s0;
console.log(`${seconds} s of callbacks: ${Math.round(total / seconds)} instructions/s, ` +
            `${((m.get('nframe') - f0) / seconds).toFixed(2)} fps, worst tick ${worst} (${worstKind})`);
for (const k in stage) console.log('  ' + k.padEnd(12), String(Math.round(stage[k] / seconds)).padStart(9), '/s',
                                    (100 * stage[k] / total).toFixed(1).padStart(5) + '%');
console.log(`  firmware: farcopy ${Math.round(fw.farcopy / seconds)}/s (${Math.round(fw.farWords / seconds)} words), ` +
            `synth ${Math.round(fw.synth / seconds)}/s - their own cost on the piano is not counted here`);
console.log('by function (self):');
table(bySelf(m.profile), total, seconds, '/s');
callSites(seconds, '/s');
