"""Tests against the official NEK-100 firmware. Set NEK100_FW=/path/to/NEK100_DSP_V1.0.7.bin to run them."""
import os
import shutil
import json
import subprocess
import tempfile
import unittest

from nuxdsp import asm, container, disasm, extract, fwmap, patcher, web

FW = os.environ.get("NEK100_FW")
HERE = os.path.dirname(os.path.abspath(__file__))
# All bundled patches with default parameters. Same code as tested on hardware (TEST8..10, 1.0.7B),
# relocated, plus boot_preset's DEFAULT_LABEL (confirmed on hardware too), polish_font's small font
# mapping and the full lang_pl translation (not yet tested on hardware).
ALL_SHA = "22bedbbe7b4b7eec1cbd1e1d5c481c219c4a6d1ca738e08e204ce690338a8d02"


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
            for a in range(len(ow) - 1):
                self.assertIn(ow[a], (orig[a], fw[a]), "%s @%#x" % (n, a))

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
            cases = [({}, {}), ({"BOOT_PRESET": 4, "DEFAULT_LABEL": 0, "OFF_VELOCITY": 90},
                                {"boot_preset": {"BOOT_PRESET": 4, "DEFAULT_LABEL": 0},
                                 "touch_off": {"OFF_VELOCITY": 90}}),
                     ({}, {"version_tag": {}, "polish_font": {}, "lang_pl": {}})]
            for params, sel in cases:
                names = list(sel) or patcher.available()
                sel = sel or {n: {} for n in names}
                cli, _ = patcher.build(self.img, self.map, patcher.resolve_patches(names), params)
                outp = os.path.join(d, "o.bin")
                subprocess.check_call(["node", os.path.join(HERE, "web_check.js"), d, FW, outp, json.dumps(sel)])
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
