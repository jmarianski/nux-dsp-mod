"""Tests against the official NEK-100 firmware. Set NEK100_FW=/path/to/NEK100_DSP_V1.0.7.bin to run them."""
import os
import re
import shutil
import json
import subprocess
import tempfile
import unittest

from nuxdsp import asm, container, disasm, extract, fwmap, patcher, web

FW = os.environ.get("NEK100_FW")
HERE = os.path.dirname(os.path.abspath(__file__))
# All bundled patches with default parameters. Same code as tested on hardware (TEST8..10, 1.0.7B),
# relocated, plus custom_voices (empty name table), boot_preset's preset labels (confirmed on hardware too), polish_font's small font
# mapping and the full lang_pl translation (all confirmed on hardware); battery_percent (number, %, standing icon:
# shown on hardware at a high level; lower fill levels and charging not yet seen) and extra_menu's functions moved
# above 0xffff (run on hardware with it).
ALL_SHA = "fcb4022c674503854cb311af233a3ad18aa2ec0e03c3135ff9a76b8ec67b9e59"


def padded(w, n):
    """Words of an image as if grown to n words (0xffff filler; the old checksum word becomes filler too)."""
    return w if len(w) >= n else w[:-1] + [0xFFFF] * (n - len(w) + 1)


@unittest.skipUnless(FW and os.path.exists(FW), "set NEK100_FW to the official firmware file")
class TestFirmware(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FW, "rb") as f:
            cls.img = f.read()
        cls.map = fwmap.load()

    def test_official(self):
        self.assertEqual(container.sha256(self.img), self.map.sha256)
        self.assertEqual(container.validate(self.img), [])

    def test_disasm_asm_identical(self):
        src = disasm.Listing(self.img, self.map).render()
        words, _ = asm.assemble(src.splitlines())
        w = container.words(self.img)
        self.assertEqual([a for a, v in words.items() if w[a] != v], [])

    def test_build_all(self):
        out, _ = patcher.build(self.img, self.map, patcher.resolve_patches(patcher.available()))
        self.assertEqual(container.sha256(out), ALL_SHA)

    def test_subsets_use_canonical_layout(self):
        full, _ = patcher.build(self.img, self.map, patcher.resolve_patches(patcher.available()))
        orig, fw = container.words(self.img), container.words(full)
        for n in patcher.available():
            p = patcher.load(n)
            one, _ = patcher.build(self.img, self.map, [patcher.load(r) for r in p.requires] + [p])
            ow = container.words(one)
            # .weak entry points: as in a build without the patches that define them
            weak = {name for name, _ in p.weaks}
            rest = [m for m in patcher.available()
                    if not weak & set(re.findall(r"^(\w+):", "\n".join(patcher.load(m).code), re.M))]
            part, _ = patcher.build(self.img, self.map, patcher.resolve_patches(rest))
            pw = padded(container.words(part), len(ow))
            orig, fw = padded(orig, len(ow)), padded(fw, len(ow))
            alone = {h.addr + i for h in p.hooks if h.unless for i in range(len(h.expect))}  # hooks of its own
            for a in range(3, len(ow) - 1):   # 1, 2: the file length
                if a not in alone:
                    self.assertIn(ow[a], (orig[a], fw[a], pw[a]), "%s @%#x" % (n, a))

    def test_telemetry_is_opt_in(self):
        # the usage log is its own patch, not a default; without it extra_menu has no trace of it, and it works
        # without extra_menu (its own hooks where extra_menu would call it)
        self.assertNotIn("telemetry", patcher.defaults(self.map))
        self.assertEqual(patcher.load("telemetry", self.map).requires, [])
        alone, _ = patcher.build(self.img, self.map, patcher.resolve_patches(["telemetry"]))
        both, _ = patcher.build(self.img, self.map, patcher.resolve_patches(["extra_menu", "telemetry"]))
        em, _ = patcher.build(self.img, self.map, patcher.resolve_patches(["extra_menu"]))
        aw, bw, ew = container.words(alone), container.words(both), container.words(em)
        for a in (0x830, 0x2602, 0x9a2, 0x9ad, 0x3860, 0x391b, 0xd6d3):
            self.assertNotEqual(aw[a:a + 2], container.words(self.img)[a:a + 2], "@%#x" % a)
            self.assertEqual(bw[a:a + 2], ew[a:a + 2], "@%#x" % a)   # with extra_menu, its hooks stay
        names = [n for n in patcher.available(self.map) if n != "telemetry"]
        out, _ = patcher.build(self.img, self.map, patcher.resolve_patches(names))
        ow = container.words(out)
        orig = padded(container.words(self.img), len(ow))
        self.assertEqual(ow[0xc1c:0xc1e], orig[0xc1c:0xc1e])   # low battery: the stock power_off
        for a in range(len(ow) - 1):   # no load or store of the log's RAM (0x6330..0x638f)
            if ow[a] != orig[a] and (ow[a] & 0xf8ef) == 0xf880:   # ld / st [abs] that we wrote
                self.assertFalse(0x6330 <= ow[a + 1] < 0x6390, "@%#x" % a)

    def test_extra_menu_detects_patches(self):
        # the Patches screen of extra_menu finds each patch by one word; check that word against the patch
        import re
        path = os.path.join(self.map.patch_dir, "extra_menu.patch")
        with open(path) as f:
            rows = re.findall(r"\.dw\s+(\d), (0x[0-9a-f]+), (0x[0-9a-f]+), pp_n\d+, pp_p\d+\s+; (\w+)", f.read())
        # short_welcome only changes an initial RAM value (a counter that runs down to 0): nothing to look at later
        listed = [n for n in patcher.available(self.map) if n != "short_welcome"]
        self.assertEqual(sorted(r[3] for r in rows), sorted(listed))
        r0 = self.map.ramdata[0]
        for kind, addr, stock, name in rows:
            if kind == "2":
                continue
            a = int(addr, 16)
            if kind == "1":   # RAM: glyphs and images are copied to 0x3a2a.. (file - 0xf2cd), the rest from ramdata
                a += 0xf2cd if 0x3a2a <= a < 0x662a else r0
            for names in ([name] + patcher.load(name, self.map).requires, patcher.available(self.map)):
                out, _ = patcher.build(self.img, self.map, patcher.resolve_patches(names))
                self.assertNotEqual(container.words(out)[a], int(stock, 16), name)
            others = [n for n in listed if n != name and name not in patcher.load(n, self.map).requires]
            out, _ = patcher.build(self.img, self.map, patcher.resolve_patches(others))
            self.assertEqual(container.words(out)[a], int(stock, 16), name)

    def test_version_tag_uses_small_font_glyphs(self):
        # the info screen draws with the small font; lowercase there maps to big-font glyphs
        w = container.words(self.img)
        small = self.map.symbols()["font_small_chars"]
        for old, new in patcher.load("version_tag").strings:
            for c in new:
                self.assertTrue(0x90 <= w[small + ord(c)] <= 0xbb, c)

    def test_refuses_other_input(self):
        bad = bytearray(self.img)
        bad[100] ^= 1
        with self.assertRaises(patcher.PatchError):
            patcher.build(bytes(bad), self.map, [patcher.load("boot_preset")])

    def test_extract_round_trip(self):
        # one pool in use: the extracted patch rebuilds the identical image
        names = ["boot_preset", "touch_off", "sustain_in_preset", "version_tag"]
        image = patcher.parse('.patch img\n.draw 0x26 at 2 1 30 7\n    1 "ZAPISZ"\n.end\n')
        out, _ = patcher.build(self.img, self.map, patcher.resolve_patches(names) + [image])
        text = extract.extract(self.img, out, self.map)
        self.assertIn(".bitmap 0x26", text)
        again, _ = patcher.build(self.img, self.map, [patcher.parse(text)])
        self.assertEqual(again, out)

    def test_extract_everything_builds(self):
        # code from several pools is merged into one relocatable block
        out, _ = patcher.build(self.img, self.map, patcher.resolve_patches(patcher.available()))
        text = extract.extract(self.img, out, self.map)
        again, _ = patcher.build(self.img, self.map, [patcher.parse(text)])
        self.assertEqual(len(again), len(out))

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_web_page_matches_cli(self):
        with tempfile.TemporaryDirectory() as d:
            shutil.copy(os.path.join(web.WEB_DIR, "index.html"), d)
            shutil.copy(os.path.join(web.WEB_DIR, "patcher.js"), d)
            os.mkdir(os.path.join(d, "targets"))
            web.write_target(self.img, self.map, d)
            web.write_packs(d)
            cases = [({}, {}), ({"BOOT_PRESET": 4, "PRESET_LABELS": 2, "OFF_VELOCITY": 90},
                                {"boot_preset": {"BOOT_PRESET": 4, "PRESET_LABELS": 2},
                                 "touch_off": {"OFF_VELOCITY": 90}}),
                     ({}, {"version_tag": {}, "polish_font": {}, "lang_pl": {}}),
                     ({}, {"extra_menu": {}, "telemetry": {}}), ({}, {"extra_menu": {}}), ({}, {"telemetry": {}})]
            for params, sel in cases:
                names = list(sel) or patcher.available()
                sel = sel or {n: {} for n in names}
                cli, _ = patcher.build(self.img, self.map, patcher.resolve_patches(names), params)
                outp = os.path.join(d, "o.bin")
                subprocess.check_call(["node", os.path.join(HERE, "web_check.js"), d, FW, outp, json.dumps(sel)])
                with open(outp, "rb") as f:
                    self.assertEqual(f.read(), cli)

    FAR = (".patch far_test\n.title \"far call test\"\n"
           ".hook 0x00ccb expect 0xd7c8 0x5bb3\n    call fa_a\n.end\n"
           ".code 0x19720\nfa_a:\n    ccall 0x5bb3\n    call fa_b\n    ret\n.end\n"
           ".code 0x1a280\nfa_b:\n    mov r7, #0x58\n    st [0x2826], r7\n    ret\n.end\n")

    def test_far_code_grows_the_file(self):
        out, report = patcher.build(self.img, self.map, [patcher.parse(self.FAR)])
        w = container.words(out)
        self.assertEqual(len(w), 0x1a2c0)
        self.assertEqual(container.validate(out), [])
        self.assertEqual((w[1], w[2]), (0xa2c0, 1))
        self.assertEqual(w[0x00ccb:0x00ccd], [0xd6c9, 0x9720])
        self.assertEqual(w[0x19722:0x19724], [0xd6c9, 0xa280])
        self.assertEqual(w[0x1a27f], 0xffff)  # the old checksum word
        self.assertIn("file grows to 0x1a2c0 words", report)
        near, _ = patcher.build(self.img, self.map, [patcher.parse(self.FAR.replace(".code 0x1a280", ".code"))])
        self.assertEqual(len(near), len(self.img))  # far pools are never chosen automatically

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_web_page_grows_the_file_too(self):
        with tempfile.TemporaryDirectory() as d:
            shutil.copy(os.path.join(web.WEB_DIR, "index.html"), d)
            shutil.copy(os.path.join(web.WEB_DIR, "patcher.js"), d)
            os.mkdir(os.path.join(d, "targets"))
            far = os.path.join(d, "far_test.patch")
            with open(far, "w") as f:
                f.write(self.FAR)
            web.write_target(self.img, self.map, d, names=[far])
            web.write_packs(d)
            outp = os.path.join(d, "o.bin")
            subprocess.check_call(["node", os.path.join(HERE, "web_check.js"), d, FW, outp, '{"far_test": {}}'])
            cli, _ = patcher.build(self.img, self.map, [patcher.parse(self.FAR)])
            with open(outp, "rb") as f:
                self.assertEqual(f.read(), cli)

    def test_committed_web_data_is_current(self):
        path = os.path.join(web.WEB_DIR, "targets", self.map.id + ".js")
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), web.target_js(self.img, self.map),
                             "run: python3 -m nuxdsp web %s" % self.map.input)

    def test_detected_by_sha(self):
        self.assertEqual(fwmap.find(container.sha256(self.img)).id, self.map.id)


if __name__ == "__main__":
    unittest.main()
