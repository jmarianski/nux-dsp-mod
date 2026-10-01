"""Tests against the official firmware. Set NEK100_FW=/path/to/NEK100_DSP_V1.0.7.bin to run them."""
import os
import shutil
import subprocess
import tempfile
import unittest

from nek100mod import asm, container, disasm, extract, fwmap, patcher, web

FW = os.environ.get("NEK100_FW")
HERE = os.path.dirname(os.path.abspath(__file__))
# All bundled patches with default parameters. Code identical to the build tested on hardware
# (only the version string differs).
ALL_SHA = "c089c287f0ffd9be64ad3569267df096fcaa5cea3f833355a3c5e95e96cd782c"


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
            one, _ = patcher.build(self.img, self.map, [patcher.load(n)])
            ow = container.words(one)
            for a in range(len(ow) - 1):
                self.assertIn(ow[a], (orig[a], fw[a]), "%s @%#x" % (n, a))

    def test_refuses_other_input(self):
        bad = bytearray(self.img)
        bad[100] ^= 1
        with self.assertRaises(patcher.PatchError):
            patcher.build(bytes(bad), self.map, [patcher.load("boot_preset")])

    def test_extract_round_trip(self):
        out, _ = patcher.build(self.img, self.map, patcher.resolve_patches(patcher.available()))
        text = extract.extract(self.img, out, self.map)
        again, _ = patcher.build(self.img, self.map, [patcher.parse(text)])
        self.assertEqual(again, out)

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_web_page_matches_cli(self):
        with tempfile.TemporaryDirectory() as d:
            page = os.path.join(d, "p.html")
            with open(page, "w") as f:
                f.write(web.export(self.img, self.map, patcher.available()))
            cases = [({}, {}), ({"BOOT_PRESET": 4, "OFF_VELOCITY": 90}, {"boot_preset": {"BOOT_PRESET": 4},
                                                                        "touch_off": {"OFF_VELOCITY": 90}})]
            for params, sel in cases:
                names = list(sel) or patcher.available()
                sel = sel or {n: {} for n in names}
                cli, _ = patcher.build(self.img, self.map, patcher.resolve_patches(names), params)
                outp = os.path.join(d, "o.bin")
                import json
                subprocess.check_call(["node", os.path.join(HERE, "web_check.js"), page, FW, outp, json.dumps(sel)])
                with open(outp, "rb") as f:
                    self.assertEqual(f.read(), cli)


if __name__ == "__main__":
    unittest.main()
