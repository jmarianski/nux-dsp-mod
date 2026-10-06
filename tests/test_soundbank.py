"""Instruments added to the official soundbank. Set NEK100_FW and NEK100_SBANK (NEK100_SBANK_V1.0.4.bin) to run."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

from nuxdsp import container, fwmap, instrument, patcher, soundbank, web

FW, SBANK = os.environ.get("NEK100_FW"), os.environ.get("NEK100_SBANK")
HERE = os.path.dirname(os.path.abspath(__file__))
# cat_piano on sound 500: the bank played on hardware (attack-trimmed Cat Piano, "cat3")
CAT_SHA = "c5d6fcad7bba3c3dad8f801367188e367d226bd56176cd9e7b5f62e6de658b72"


class TestPack(unittest.TestCase):
    def test_bundled_round_trip(self):
        for n in instrument.bundled_names():
            with open(instrument.bundled(n), "rb") as f:
                data = f.read()
            p = instrument.from_bytes(data)
            self.assertEqual(p.to_bytes(), data)
            for k in ("author", "source", "license"):
                self.assertTrue(p.header.get(k), "%s: pack needs %s" % (n, k))

    def test_name_checks(self):
        self.assertEqual(len(soundbank.name_words(500, "Cat Piano")), 16)
        self.assertRaises(soundbank.BankError, soundbank.name_words, 500, "Twelve chars")
        self.assertRaises(soundbank.BankError, soundbank.name_words, 1, "Kocie piąno")
        soundbank.name_words(1, "Kocie piąno", polish=True)


@unittest.skipUnless(FW and SBANK and os.path.exists(FW) and os.path.exists(SBANK),
                     "set NEK100_FW and NEK100_SBANK to the official files")
class TestSoundbank(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FW, "rb") as f:
            cls.img = f.read()
        with open(SBANK, "rb") as f:
            cls.bank = f.read()
        cls.map = fwmap.load()
        cls.cat = instrument.load(instrument.bundled("cat_piano"))

    def test_cat_bank_as_on_hardware(self):
        out = soundbank.add(self.bank, self.img, self.map, [(self.cat, 500)])
        self.assertEqual(container.sha256(out), CAT_SHA)

    def test_several(self):
        out = soundbank.add(self.bank, self.img, self.map, [(self.cat, 500), (self.cat, 1), (self.cat, 250)])
        self.assertGreater(len(out), len(self.bank))
        self.assertRaises(soundbank.BankError, soundbank.add, self.bank, self.img, self.map, [(self.cat, 3)] * 2)
        self.assertRaises(soundbank.BankError, soundbank.add, self.img, self.img, self.map, [(self.cat, 3)])

    def test_names_need_the_patch(self):
        plain, _ = patcher.build(self.img, self.map, patcher.resolve_patches(["version_tag"]))
        self.assertRaises(soundbank.BankError, soundbank.fill_names, plain, self.map, [(500, "Cat Piano", "")])

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_web_matches_cli(self):
        voices = [(500, "cat_piano", "Cat Piano", "Kocie piano"), (2, "cat_piano", "Meow", "")]
        names = patcher.defaults(self.map) + ["custom_voices"]
        cli, _ = patcher.build(self.img, self.map, patcher.resolve_patches(names))
        cli = soundbank.fill_names(cli, self.map, [(v, n, p) for v, _, n, p in voices])
        cli_bank = soundbank.add(self.bank, self.img, self.map, [(self.cat, v) for v, *_ in voices])
        with tempfile.TemporaryDirectory() as d:
            for f in ("index.html", "patcher.js"):
                shutil.copy(os.path.join(web.WEB_DIR, f), d)
            os.mkdir(os.path.join(d, "targets"))
            web.write_target(self.img, self.map, d)
            web.write_packs(d)
            sel = {n: {} for n in names}
            js = [{"voice": v, "pack": k, "name": n, "name_pl": p} for v, k, n, p in voices]
            o, ob = os.path.join(d, "o.bin"), os.path.join(d, "b.bin")
            subprocess.check_call(["node", os.path.join(HERE, "web_check.js"), d, FW, o, json.dumps(sel),
                                   SBANK, ob, json.dumps(js)])
            with open(o, "rb") as f:
                self.assertEqual(f.read(), cli)
            with open(ob, "rb") as f:
                self.assertEqual(f.read(), cli_bank)

    def test_committed_packs_are_current(self):
        for n in instrument.bundled_names():
            with open(os.path.join(web.WEB_DIR, "instruments", n + ".js"), encoding="utf-8") as f:
                self.assertEqual(f.read(), web.pack_js(n), "run: python3 -m nuxdsp web")
        with open(os.path.join(web.WEB_DIR, "instruments", "index.js"), encoding="utf-8") as f:
            self.assertEqual(f.read(), web.packs_index_js(), "run: python3 -m nuxdsp web")


if __name__ == "__main__":
    unittest.main()
