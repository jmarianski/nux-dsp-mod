// node tests/web_check.js PAGE.html FW.bin OUT.bin 'SELECTION_JSON'  -> runs the page's own patch code
const fs = require("fs");
const [page, fw, outp, selJson] = process.argv.slice(2);
const html = fs.readFileSync(page, "utf8");
const script = html.slice(html.indexOf("<script>") + 8, html.indexOf("// --- UI ---"));
const api = new Function(script + "; return {DATA, applyPatches, sha256js};")();
const bytes = new Uint8Array(fs.readFileSync(fw));
const require_sha = require("crypto").createHash("sha256").update(bytes).digest("hex");
if (api.sha256js(bytes) !== require_sha) { console.error("sha256js mismatch"); process.exit(1); }
if (require_sha !== api.DATA.sha256) { console.error("not the official firmware"); process.exit(1); }
fs.writeFileSync(outp, api.applyPatches(bytes, JSON.parse(selJson)));
