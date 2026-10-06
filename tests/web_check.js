// node tests/web_check.js WEB_DIR FW.bin OUT.bin 'SELECTION_JSON' [SBANK.bin SBANK_OUT.bin 'VOICES_JSON']
//   -> runs the page's own patch code; VOICES_JSON: [{"voice": 500, "pack": "cat_piano", "name": ..., "name_pl": ...}]
const fs = require("fs"), path = require("path"), vm = require("vm");
const [webDir, fw, outp, selJson, sbank, sbOut, voicesJson] = process.argv.slice(2);
const ctx = vm.createContext({TextDecoder, TextEncoder, atob});
const html = fs.readFileSync(path.join(webDir, "index.html"), "utf8");
const run = f => vm.runInContext(fs.readFileSync(path.join(webDir, f), "utf8"), ctx, {filename: f});
for (const m of html.matchAll(/<script src="([^"]+)"><\/script>/g)) run(m[1]);
const api = vm.runInContext("({TARGETS, applyPatches, identify, sha256js, containerOk, parsePack, addInstruments, " +
                            "fillNames, packBytes})", ctx);
const bytes = new Uint8Array(fs.readFileSync(fw));
const sha = require("crypto").createHash("sha256").update(bytes).digest("hex");
if (api.sha256js(bytes) !== sha) { console.error("sha256js mismatch"); process.exit(1); }
api.identify(bytes).then(async id => {
  if (!id.target) { console.error("not a supported firmware: " + sha); process.exit(1); }
  const out = api.applyPatches(id.target, bytes, JSON.parse(selJson));
  if (!api.containerOk(out)) { console.error("output container invalid"); process.exit(1); }
  if (sbank) {
    const voices = JSON.parse(voicesJson);
    for (const v of voices) { run(`instruments/${v.pack}.js`); v.pack = api.parsePack(api.packBytes(v.pack)); }
    api.fillNames(id.target, out, voices);
    fs.writeFileSync(sbOut, await api.addInstruments(id.target, bytes, new Uint8Array(fs.readFileSync(sbank)), voices));
  }
  fs.writeFileSync(outp, out);
}).catch(e => { console.error(String(e)); process.exit(1); });
