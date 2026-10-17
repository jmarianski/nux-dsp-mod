/* Optional real-browser regression check. Start tools/webserve.py first.
 * Needs Playwright (PLAYWRIGHT_MODULE can point to an existing installation).
 * MIDI is mocked: this check sends nothing to the actual piano.
 */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const page = await browser.newPage({ viewport: { width: 900, height: 1000 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.addInitScript(() => {
    const sent = [];
    const output = { id: "out", name: "NEK-100 mock", state: "connected", send: (data) => sent.push([...data]) };
    const input = { id: "in", name: "NEK-100 mock", state: "connected", onmidimessage: null };
    const access = { inputs: new Map([[input.id, input]]), outputs: new Map([[output.id, output]]) };
    Object.defineProperty(navigator, "requestMIDIAccess", { value: async () => access });
    window.testMidi = { sent, output, input, access };
  });
  const ready = (name = "doom") => page.waitForFunction((name) =>
    !loading && m && prog.name === name && !paused && !document.querySelector("#pause").disabled, name);
  const snap = () => page.evaluate(() => ({ held: m.get("held"), x: m.get("px"), y: m.get("py"),
    angle: m.get("pa"), frames: m.get("nframe") }));
  const focusGame = () => page.evaluate(() => document.activeElement.blur());
  try {
    await page.goto(process.argv[2] || "http://localhost:8017/");
    await ready();
    await page.waitForFunction(() => /[1-9]\d* klatek/.test(document.querySelector("#stats").textContent));
    assert(await page.evaluate(() => prog.ram_words <= 482), "compiled engine fits target RAM");
    const before = await snap();
    await page.keyboard.down("ArrowUp"); await page.waitForTimeout(200); await page.keyboard.up("ArrowUp");
    const moved = await snap();
    assert(before.x !== moved.x || before.y !== moved.y, "movement must change the player position");

    await page.keyboard.down("w"); await page.keyboard.down("ArrowUp"); await page.keyboard.up("w");
    assert((await snap()).held & 4, "releasing one alias must leave the other held");
    await page.keyboard.up("ArrowUp"); assert.equal((await snap()).held, 0);
    await page.keyboard.down("ArrowLeft");
    await page.evaluate(() => dispatchEvent(new Event("blur")));
    assert.equal((await snap()).held, 0, "losing focus must release keys");
    await page.keyboard.up("ArrowLeft");

    await page.click("#pause");
    const frozen = await snap();
    await focusGame();
    await page.keyboard.down("ArrowUp"); await page.waitForTimeout(100); await page.keyboard.up("ArrowUp");
    assert.deepEqual(await snap(), frozen, "pause must freeze the game and reject movement");
    await page.click("#reload"); await ready();
    assert.equal((await snap()).held, 0, "reload recovers from pause with no held keys");
    const ammoBefore = await page.evaluate(() => m.get("ammo"));
    await page.keyboard.down("Space"); await page.waitForTimeout(160); await page.keyboard.up("Space");
    assert(await page.evaluate((before) => m.get("ammo") < before, ammoBefore), "Space fires the weapon");
    await page.evaluate(() => m.call("damage", 250));
    await page.waitForFunction(() => m.get("game_mode") === 1);
    await page.keyboard.press("Enter");
    await page.waitForFunction(() => m.get("game_mode") === 0 && m.get("health") === 100);
    assert.match(await page.textContent("#budget"), /RAM \d+\/482/);

    await page.click("#midi");
    await page.waitForFunction(() => testMidi.sent.some((v) => (v[0] & 0xf0) === 0xc0));
    assert(await page.evaluate(() => testMidi.sent.every((v) =>
      v[0] >= 0x80 && v[0] < 0xf0 && v.slice(1).every((n) => n >= 0 && n <= 127))), "valid MIDI messages");
    await page.evaluate(() => testMidi.input.onmidimessage({ data: [0x90, 48, 100] }));
    assert((await snap()).held & 2, "piano note controls movement");
    await page.selectOption("#min", "");
    assert.equal((await snap()).held, 0, "changing MIDI input releases its notes");
    await page.selectOption("#mout", "");
    assert(await page.evaluate(() => testMidi.sent.slice(-24).every((v) => v[1] === 123 || v[1] === 120)),
      "changing MIDI output silences old channels");
    await page.evaluate(() => testMidi.access.onstatechange());
    assert.equal(await page.inputValue("#mout"), "", "refresh respects an explicitly disabled output");

    // Build errors and corrupt instructions must be recoverable without refreshing the whole page.
    await page.route("**/build/game.json", (route) => route.fulfill({ status: 500, body: "test build failure" }));
    await page.click("#reload");
    await page.waitForFunction(() => !loading && !m);
    assert.match(await page.textContent("#log"), /test build failure/);
    await page.unroute("**/build/game.json");
    await page.click("#reload"); await ready();
    await page.evaluate(() => { m.op[prog.entry.rc_tick - m.start] = 0; });
    await page.waitForFunction(() => document.querySelector("#status").textContent.startsWith("Błąd wykonania"));
    await page.click("#reload"); await ready();

    // A slower previous build must not replace the engine selected later.
    await page.route("**/build/game.json", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 350));
      try { await route.continue(); } catch (_) { /* load aborted this request */ }
    });
    await page.click("#reload");
    await page.selectOption("#engine", "ray"); await ready("ray");
    await page.waitForTimeout(400);
    assert.equal(await page.evaluate(() => prog.name), "ray");
    await page.unroute("**/build/game.json");
    await page.waitForFunction(() => m.get("stage") === 2);
    assert(await page.isHidden("#navigation"), "navigation is only available for the E1M1 map");
    assert.equal(await page.evaluate(() => m.get("st_ok")), 1, "ray self-test still passes");
    await page.selectOption("#engine", "doom"); await ready();
    await page.waitForTimeout(1200);
    const out = path.join(__dirname, "..", "build"); fs.mkdirSync(out, { recursive: true });
    await page.screenshot({ path: path.join(out, "webcheck.png"), fullPage: true });
    await page.keyboard.press("m");
    assert(await page.evaluate(() => document.querySelector("#navigation").open), "M opens navigation");
    await page.screenshot({ path: path.join(out, "webcheck-map.png"), fullPage: true });
    await page.keyboard.press("m");
    assert(!await page.evaluate(() => document.querySelector("#navigation").open), "M closes navigation");
    // Visual door fixture. Use the actual F binding and wait for the shared engine to raise it.
    await page.evaluate(() => {
      setPaused(true);
      for (const [key, value] of Object.entries({px:1440, py:-2496, pa:0, pz:0})) m.wr(m.sym(key), value);
      m.call("frame"); draw();
    });
    await page.screenshot({ path: path.join(out, "webcheck-door.png"), fullPage: true });
    await page.evaluate(() => setPaused(false));
    await page.keyboard.down("ArrowUp");
    await page.waitForFunction(() => m.get("px") >= 1480);
    await page.keyboard.up("ArrowUp");
    await page.keyboard.press("f");
    await page.waitForFunction(() => m.get("dynamic_height") >= 16);
    await page.evaluate(() => { setPaused(true); m.call("frame"); draw(); });
    await page.screenshot({ path: path.join(out, "webcheck-door-open.png"), fullPage: true });
    // A deterministic visual fixture for the original imp spawn, separate from the walking replay.
    const spritePixels = await page.evaluate(() => {
      setPaused(true);
      m.wr(m.sym("px"), 3376); m.wr(m.sym("py"), -3472); m.wr(m.sym("pa"), 0);
      m.call("read_sector", m.call("sector_at", 3376, -3472)); m.wr(m.sym("pz"), m.get("buf"));
      m.call("frame"); draw();
      const start=prog.mmio.framebuffer, before=Array.from(m.ram.slice(start,start+1024)), state=m.get("enemy_state");
      m.wr(m.sym("enemy_state"),0);m.call("frame");
      const changed=before.filter((v,i)=>v!==m.ram[start+i]).length;
      m.wr(m.sym("enemy_state"),state);m.call("frame");draw();
      return changed;
    });
    assert(spritePixels > 8, "the imp silhouette must actually reach the framebuffer");
    await page.screenshot({ path: path.join(out, "webcheck-combat.png"), fullPage: true });
    assert.deepEqual(errors, [], "no uncaught browser errors");
    console.log("PASS: E1M1, navigation M, textured door/F, movement, fire, death/Enter restart, aliases, blur, pause, reload, mocked MIDI, build/runtime recovery, load race, ray fallback");
    console.log(await page.textContent("#stats"));
    console.log("Screenshot: build/webcheck.png");
  } finally { await browser.close(); }
})().catch((e) => { console.error(e); process.exitCode = 1; });
