// node tests/web_check.js WEB_DIR FW.bin OUT.bin 'SELECTION_JSON'  -> runs the page's own patch code
const fs = require("fs"), path = require("path"), vm = require("vm");
const [webDir, fw, outp, selJson] = process.argv.slice(2);
const ctx = vm.createContext({});
const html = fs.readFileSync(path.join(webDir, "index.html"), "utf8");
for (const m of html.matchAll(/<script src="([^"]+)"><\/script>/g))
  vm.runInContext(fs.readFileSync(path.join(webDir, m[1]), "utf8"), ctx, {filename: m[1]});
const api = vm.runInContext("({TARGETS, applyPatches, identify, sha256js, containerOk})", ctx);
const bytes = new Uint8Array(fs.readFileSync(fw));
const sha = require("crypto").createHash("sha256").update(bytes).digest("hex");
if (api.sha256js(bytes) !== sha) { console.error("sha256js mismatch"); process.exit(1); }
api.identify(bytes).then(id => {
  if (!id.target) { console.error("not a supported firmware: " + sha); process.exit(1); }
  const out = api.applyPatches(id.target, bytes, JSON.parse(selJson));
  if (!api.containerOk(out)) { console.error("output container invalid"); process.exit(1); }
  fs.writeFileSync(outp, out);
});
