/* The page around the emulator: the 10 ms tick with the us clock, the LCD, keys, WebMIDI out (the piano's synth)
 * and in (its keys), VOL. */
"use strict";

const $ = (id) => document.getElementById(id);
const ctx = $("lcd").getContext("2d");
const img = ctx.createImageData(128, 64);
const ON = [0x1d, 0x26, 0x18], OFF = [0x9f, 0xb0, 0x8a];

let prog = null, m = null, paused = false, t0 = 0, ticksDone = 0, midiOut = null, midiIn = null;
let frames = 0, steps = 0, statT = 0, busy = 0;
const held = new Set();

function log(s) {
  const el = $("log");
  el.textContent = (el.textContent + s + "\n").split("\n").slice(-200).join("\n");
  el.scrollTop = el.scrollHeight;
}

function synth(st, d1, d2) {
  if (!midiOut) return;
  midiOut.send((st & 0xe0) === 0xc0 ? [st, d1] : [st, d1, d2]);
}

function allOff() {
  if (!midiOut) return;
  for (let c = 4; c < 16; c++) { midiOut.send([0xb0 | c, 123, 0]); midiOut.send([0xb0 | c, 120, 0]); }
}

async function load() {
  if (m) { try { m.call("mu_stop"); } catch (e) { /* an old build */ } }
  allOff();
  const res = await fetch("build/game.json", { cache: "no-store" });
  if (!res.ok) { log("build/game.json: " + res.status + "\n" + (await res.text())); return; }
  prog = await res.json();
  m = new P16(prog, rayNatives({
    trace: (v) => { if ((v & 0xff00) !== 0x400) log("marker 0x" + v.toString(16).padStart(4, "0")); },
    synth,
  }));
  m.wr(prog.mmio.dev_vol, +$("vol").value);
  m.call("__cc_init");
  m.call("rc_start");
  for (const n of held) m.call("rc_key", n, 100);
  t0 = performance.now();
  ticksDone = 0;
  log("załadowany: " + prog.name + ", " + prog.code.op.length + " słów kodu");
}

function draw() {
  const fb = prog.mmio.framebuffer;
  for (let y = 0; y < 64; y++)
    for (let x = 0; x < 128; x++) {
      const on = (m.ram[fb + (y >> 3) * 128 + x] >> (y & 7)) & 1;
      const c = on ? ON : OFF, i = (y * 128 + x) * 4;
      img.data[i] = c[0]; img.data[i + 1] = c[1]; img.data[i + 2] = c[2]; img.data[i + 3] = 255;
    }
  ctx.putImageData(img, 0, 0);
}

function tick() {
  const us = Math.floor((performance.now() - t0) * 1000);
  m.wr(prog.mmio.clock_lo, us & 0xffff);
  m.wr(prog.mmio.clock_hi, Math.floor(us / 65536) & 0xffff);
  m.wr(prog.mmio.dev_vol, +$("vol").value);
  const s0 = m.steps, a = performance.now();
  m.call("rc_tick");
  busy += performance.now() - a;
  steps += m.steps - s0;
  const f = prog.mmio.lcd_flag;
  if (m.rd(f) & 1) { m.wr(f, m.rd(f) & ~1); draw(); frames++; }
}

function loop() {
  if (m && !paused) {
    const due = Math.floor((performance.now() - t0) / prog.tick_ms);
    if (due - ticksDone > 10) ticksDone = due - 10;     /* far behind (a background tab): skip */
    try {
      while (ticksDone < due) { tick(); ticksDone++; }
    } catch (e) {
      log("CRASH: " + e.message);
      paused = true;
      allOff();
    }
    const now = performance.now();
    if (now - statT >= 1000) {
      $("stats").textContent = frames + " klatek/s · " + Math.round(steps / 1000) + " tys. instr./s · JS " +
        Math.round(busy / (now - statT) * 100) + "% czasu";
      frames = 0; steps = 0; busy = 0; statT = now;
    }
  }
  requestAnimationFrame(loop);
}

const KEYS = { ArrowLeft: "left", KeyA: "left", ArrowRight: "right", KeyD: "right", ArrowUp: "forward",
               KeyW: "forward", ArrowDown: "back", KeyS: "back", KeyQ: "strafe_left", KeyE: "strafe_right" };

function key(note, vel) {
  if (vel) held.add(note); else held.delete(note);
  if (m) m.call("rc_key", note, vel);
}

addEventListener("keydown", (e) => {
  if (e.code === "KeyR" && !e.repeat) { load(); return; }
  const k = KEYS[e.code];
  if (!k || !prog) return;
  e.preventDefault();
  if (!e.repeat) key(prog.keys[k], 100);
});
addEventListener("keyup", (e) => {
  const k = KEYS[e.code];
  if (k && prog) key(prog.keys[k], 0);
});
addEventListener("blur", () => { for (const n of [...held]) key(n, 0); });

$("reload").onclick = load;
$("pause").onclick = () => {
  paused = !paused;
  $("pause").textContent = paused ? "Wznów" : "Pauza";
  if (paused) allOff(); else { t0 = performance.now() - ticksDone * prog.tick_ms; }
};

$("midi").onclick = async () => {
  if (!navigator.requestMIDIAccess) { log("ta przeglądarka nie ma WebMIDI (Chrome/Edge/Firefox ma)"); return; }
  let access;
  try { access = await navigator.requestMIDIAccess(); } catch (e) { log("MIDI: " + e.message); return; }
  const fill = (sel, ports) => {
    const cur = sel.value;
    sel.innerHTML = '<option value="">—</option>';
    for (const p of ports.values()) sel.add(new Option(p.name, p.id));
    const nek = [...ports.values()].find((p) => /nek/i.test(p.name));
    sel.value = cur || (nek ? nek.id : "");
  };
  const refresh = () => {
    fill($("mout"), access.outputs);
    fill($("min"), access.inputs);
    $("mout").onchange();
    $("min").onchange();
  };
  $("mout").onchange = () => { allOff(); midiOut = access.outputs.get($("mout").value) || null; };
  $("min").onchange = () => {
    if (midiIn) midiIn.onmidimessage = null;
    midiIn = access.inputs.get($("min").value) || null;
    if (midiIn) midiIn.onmidimessage = (ev) => {
      const [st, n, v] = ev.data;
      if ((st & 0xf0) === 0x90) key(n, v);
      else if ((st & 0xf0) === 0x80) key(n, 0);
    };
  };
  access.onstatechange = refresh;
  refresh();
  log("MIDI: wyjście " + (midiOut ? midiOut.name : "brak") + ", wejście " + (midiIn ? midiIn.name : "brak"));
};

addEventListener("pagehide", allOff);
load().then(() => requestAnimationFrame(loop));
