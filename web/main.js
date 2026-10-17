/* Local development UI for the same compiled P16 program as the piano. */
"use strict";

const $ = (id) => document.getElementById(id);
const ctx = $("lcd").getContext("2d");
const img = ctx.createImageData(128, 64);
const ON = [0x1d, 0x26, 0x18], OFF = [0x9f, 0xb0, 0x8a];
let prog = null, m = null, paused = false, loading = false, t0 = 0, ticksDone = 0;
let navigation = null;
let midiOut = null, midiIn = null, midiAccess = null, musicNeedsRestart = false;
let frames = 0, steps = 0, statT = 0, busy = 0, loadGeneration = 0, request = null;
const held = new Map();                       // input source -> note; aliases may hold the same note

function log(s) {
  const el = $("log");
  el.textContent = (el.textContent + s + "\n").split("\n").slice(-200).join("\n");
  el.scrollTop = el.scrollHeight;
}

function status(s) { $("status").textContent = s; }

function synth(st, d1, d2) {
  if (!midiOut || midiOut.state === "disconnected") return;
  midiOut.send((st & 0xe0) === 0xc0 ? [st, d1] : [st, d1, d2]);
}

function allOff() {
  if (!midiOut) return;
  try {
    for (let c = 4; c < 16; c++) { midiOut.send([0xb0 | c, 123, 0]); midiOut.send([0xb0 | c, 120, 0]); }
  } catch (e) { log("MIDI: " + e.message); }
}

function key(source, note, vel) {
  if (vel) {
    if (!m || paused || loading || held.has(source)) return;
    const already = [...held.values()].includes(note);
    held.set(source, note);
    if (!already) m.call("rc_key", note, vel);
  } else {
    const old = held.get(source);
    held.delete(source);
    if (m && old !== undefined && ![...held.values()].includes(old)) m.call("rc_key", old, 0);
  }
}

function releaseKeys(prefix = "") {
  for (const [source, note] of [...held]) if (source.startsWith(prefix)) key(source, note, 0);
}

function setPaused(value) {
  paused = value;
  $("pause").textContent = paused ? "Wznów" : "Pauza";
  if (paused) { releaseKeys(); allOff(); }
  else {
    t0 = performance.now() - ticksDone * prog.tick_ms; statT = performance.now(); frames = steps = busy = 0;
    if (musicNeedsRestart) restartMusic();
  }
  status(paused ? "Pauza" : prog.label);
}

function crash(e) {
  log("BŁĄD: " + e.message);
  paused = true;
  held.clear(); allOff();                     // do not execute more instructions in a broken program
  $("pause").disabled = true;
  status("Błąd wykonania — popraw kod i przeładuj (R).");
}

async function load() {
  const generation = ++loadGeneration;
  if (request) request.abort();
  request = new AbortController();
  loading = true;
  releaseKeys(); allOff();
  m = null;
  navigation = null; $("navigation").hidden = true;
  $("pause").disabled = true;
  status("Kompilowanie i ładowanie…");
  const engine = $("engine").value;
  const url = new URL(location.href); url.searchParams.set("engine", engine); history.replaceState(null, "", url);
  try {
    const res = await fetch(engine === "ray" ? "build/ray.json" : "build/game.json", {
      cache: "no-store", signal: request.signal,
    });
    if (!res.ok) throw new Error("Kompilacja: HTTP " + res.status + "\n" + await res.text());
    const nextProg = await res.json();
    if (generation !== loadGeneration) return;
    const next = new P16(nextProg, rayNatives({
      trace: (v) => { if ((v & 0xff00) !== 0x400) log("marker 0x" + v.toString(16).padStart(4, "0")); },
      synth,
    }));
    next.wr(nextProg.mmio.dev_vol, +$("vol").value);
    next.call("__cc_init"); next.call("rc_start");
    prog = nextProg; m = next;
    if (prog.navigation) {
      navigation = new Navigation($("map"), prog); navigation.prepare(m);
      $("navigation").hidden = false;
    }
    musicNeedsRestart = false;
    paused = false;
    $("pause").textContent = "Pauza"; $("pause").disabled = false;
    t0 = statT = performance.now(); ticksDone = frames = steps = busy = 0;
    draw();
    status(prog.label);
    $("budget").textContent = prog.budget ? "RAM " + prog.budget.ram.used + "/" + prog.budget.ram.limit +
      " słów · kod i dane " + prog.budget.program.used + "/" + prog.budget.program.limit + " słów" : "";
    log("Załadowany: " + prog.name + ", RAM " + prog.ram_words + "/482 słów. " +
        (midiOut ? "Muzyka → " + midiOut.name : "Dźwięk: wybierz wyjście MIDI, aby słyszeć syntezator pianina."));
    $("lcd").focus({ preventScroll: true });
  } catch (e) {
    if (generation !== loadGeneration || e.name === "AbortError") return;
    allOff(); log(e.message);
    status("Nie udało się załadować — szczegóły w logu. Popraw kod i przeładuj (R).");
  } finally {
    if (generation === loadGeneration) loading = false;
  }
}

function draw() {
  const fb = prog.mmio.framebuffer;
  for (let y = 0; y < 64; y++) for (let x = 0; x < 128; x++) {
    const on = (m.ram[fb + (y >> 3) * 128 + x] >> (y & 7)) & 1;
    const c = on ? ON : OFF, i = (y * 128 + x) * 4;
    img.data[i] = c[0]; img.data[i + 1] = c[1]; img.data[i + 2] = c[2]; img.data[i + 3] = 255;
  }
  ctx.putImageData(img, 0, 0);
  if (navigation && $("navigation").open) navigation.draw(m);
}

function tick() {
  const us = (ticksDone + 1) * prog.tick_ms * 1000;
  m.wr(prog.mmio.clock_lo, us & 0xffff);
  m.wr(prog.mmio.clock_hi, Math.floor(us / 65536) & 0xffff);
  m.wr(prog.mmio.dev_vol, +$("vol").value);
  const s0 = m.steps, a = performance.now();
  m.call("rc_tick");
  busy += performance.now() - a; steps += m.steps - s0;
  const f = prog.mmio.lcd_flag;
  if (m.rd(f) & 1) { m.wr(f, m.rd(f) & ~1); draw(); frames++; }
}

function loop() {
  if (m && !paused && !loading) {
    let due = Math.floor((performance.now() - t0) / prog.tick_ms);
    // Bound catch-up work without jumping the 16-bit music clock or starving input events.
    if (due - ticksDone > 10) { t0 += (due - ticksDone - 10) * prog.tick_ms; due = ticksDone + 10; }
    const deadline = performance.now() + 12;
    try {
      while (ticksDone < due && performance.now() < deadline) { tick(); ticksDone++; }
    } catch (e) { crash(e); }
    const now = performance.now();
    if (now - statT >= 1000) {
      const seconds = (now - statT) / 1000;
      $("stats").textContent = Math.round(frames / seconds) + " klatek/s · " + Math.round(steps / seconds / 1000) +
        " tys. instr./s · JS " + Math.round(busy / (now - statT) * 100) + "% czasu" +
        (prog.callback_limits ? " · tick P16 maks. " + (m.maxCallbackSteps.rc_tick || 0) + "/" + prog.callback_limits.rc_tick : "");
      frames = steps = busy = 0; statT = now;
    }
  }
  requestAnimationFrame(loop);
}

const KEYS = { ArrowLeft: "left", KeyA: "left", ArrowRight: "right", KeyD: "right", ArrowUp: "forward",
  KeyW: "forward", ArrowDown: "back", KeyS: "back", KeyQ: "strafe_left", KeyE: "strafe_right",
  Space: "fire", KeyF: "use", Enter: "restart", ShiftLeft: "run", ShiftRight: "run" };

addEventListener("keydown", (e) => {
  if (e.target.matches("input, select, textarea, button")) return;
  if (e.code === "KeyR" && !e.repeat) { load(); return; }
  if (e.code === "KeyM" && navigation) {
    e.preventDefault();
    if (!e.repeat) $("navigation").open = !$("navigation").open;
    return;
  }
  const action = KEYS[e.code];
  if (!action || !m || prog.keys[action] === undefined) return;
  e.preventDefault();
  if (!e.repeat) { try { key("pc:" + e.code, prog.keys[action], 100); } catch (err) { crash(err); } }
});
addEventListener("keyup", (e) => { try { key("pc:" + e.code, 0, 0); } catch (err) { crash(err); } });
addEventListener("blur", () => releaseKeys());
document.addEventListener("visibilitychange", () => { if (document.hidden && m && !paused) setPaused(true); });

$("reload").onclick = load;
$("engine").onchange = load;
$("pause").onclick = () => { if (m) setPaused(!paused); $("lcd").focus({ preventScroll: true }); };
$("lcd").onpointerdown = () => $("lcd").focus({ preventScroll: true });
$("navigation").ontoggle = () => { if (navigation && m && $("navigation").open) navigation.draw(m); };

function restartMusic() {
  if (!m || paused || loading) return;
  m.call(prog.entry.audio_restart === undefined ? "mu_restart" : "audio_restart");
  m.wr(prog.symbols.mu_last, m.rd(prog.mmio.clock_lo));
  m.wr(prog.symbols.mu_us, 0);
  musicNeedsRestart = false;
}

function refreshMidi() {
  const fill = (sel, ports) => {
    const first = !sel.dataset.initialized, old = sel.value;
    const connected = [...ports.values()].filter((p) => p.state !== "disconnected");
    sel.replaceChildren(new Option("—", ""));
    for (const p of connected) sel.add(new Option(p.name, p.id));
    const preferred = connected.find((p) => /nek/i.test(p.name));
    sel.value = first && preferred ? preferred.id : old;
    sel.dataset.initialized = "yes";
  };
  fill($("mout"), midiAccess.outputs); fill($("min"), midiAccess.inputs);
  $("mout").onchange(); $("min").onchange();
}

$("mout").onchange = () => {
  const next = midiAccess.outputs.get($("mout").value) || null;
  if (next === midiOut) return;
  allOff(); midiOut = next;
  musicNeedsRestart = !!midiOut;
  try { restartMusic(); } catch (e) { crash(e); }
  log("Dźwięk: " + (midiOut ? midiOut.name : "wyłączony"));
};
$("min").onchange = () => {
  const next = midiAccess.inputs.get($("min").value) || null;
  if (next === midiIn) return;
  releaseKeys("midi:");
  if (midiIn) midiIn.onmidimessage = null;
  midiIn = next;
  if (midiIn) midiIn.onmidimessage = (ev) => {
    const [st, note, vel] = ev.data;
    const source = "midi:" + (st & 15) + ":" + note;
    try {
      if ((st & 0xf0) === 0x90) key(source, note, vel);
      else if ((st & 0xf0) === 0x80) key(source, note, 0);
    } catch (e) { crash(e); }
  };
};

$("midi").onclick = async () => {
  if (!navigator.requestMIDIAccess) { log("Ta przeglądarka nie udostępnia WebMIDI. Możesz grać klawiaturą komputera."); return; }
  try {
    if (!midiAccess) midiAccess = await navigator.requestMIDIAccess();
    midiAccess.onstatechange = refreshMidi;
    refreshMidi();
    $("midi").textContent = "Odśwież MIDI";
    log("MIDI: wejście " + (midiIn ? midiIn.name : "brak") + ", wyjście " + (midiOut ? midiOut.name : "brak"));
    $("lcd").focus({ preventScroll: true });
  } catch (e) { log("MIDI: " + e.message); }
};

addEventListener("pagehide", () => { releaseKeys(); allOff(); });
const initialEngine = new URL(location.href).searchParams.get("engine");
if (initialEngine === "ray") $("engine").value = initialEngine;
load();
requestAnimationFrame(loop);
