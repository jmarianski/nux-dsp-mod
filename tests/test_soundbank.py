"""Instruments added to the official soundbank. Set NEK100_FW and NEK100_SBANK (NEK100_SBANK_V1.0.4.bin) to run
the soundbank tests; NUX_TEST_SF2=/path/to/any.sf2 (e.g. a General MIDI SoundFont) adds a third-party file."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

from nuxdsp import container, fwmap, instrument, patcher, sf2, soundbank, web

FW, SBANK, SF2 = os.environ.get("NEK100_FW"), os.environ.get("NEK100_SBANK"), os.environ.get("NUX_TEST_SF2")
HERE = os.path.dirname(os.path.abspath(__file__))
# cat_piano on sound 500: the bank played on hardware (attack-trimmed Cat Piano, "cat3")
CAT_SHA = "c5d6fcad7bba3c3dad8f801367188e367d226bd56176cd9e7b5f62e6de658b72"


def cat():
    return sf2.load(instrument.bundled("cat_piano")).instrument(0)


class TestSf2(unittest.TestCase):
    def test_bundled(self):
        for n in instrument.bundled_names():
            sf = sf2.load(instrument.bundled(n))
            for k in ("INAM", "IENG", "ICOP", "ICMT"):
                self.assertTrue(sf.info.get(k), "%s.sf2 needs %s" % (n, k))
            for i, *_ in sf.presets:
                sf.instrument(i)

    def test_write_read(self):
        z = [sf2.Zone(0, 59, 48, -9, 44100, b"\1\0\2\0" * 50), sf2.Zone(60, 127, 72, 130, 22050, b"\3\0" * 80, (10, 70))]
        ins = sf2.SoundFont(sf2.write(sf2.Instrument("Test", z, {"IENG": "me"}))).instrument(0)
        self.assertEqual([(x.lo, x.hi, x.root, x.cents, x.rate, x.loop) for x in ins.zones],
                         [(0, 59, 48, -9, 44100, None), (60, 127, 72, 130, 22050, (10, 70))])
        self.assertEqual(ins.zones[0].pcm, z[0].pcm)
        self.assertEqual(ins.zones[1].pcm, z[1].pcm[:2 * 71])

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

    def test_cat_bank_as_on_hardware(self):
        out = soundbank.add(self.bank, self.img, self.map, [(cat(), 500)])
        self.assertEqual(container.sha256(out), CAT_SHA)

    def test_several(self):
        c = cat()
        out = soundbank.add(self.bank, self.img, self.map, [(c, 500), (c, 1), (c, 250)])
        self.assertGreater(len(out), len(self.bank))
        self.assertRaises(soundbank.BankError, soundbank.add, self.bank, self.img, self.map, [(c, 3)] * 2)
        self.assertRaises(soundbank.BankError, soundbank.add, self.img, self.img, self.map, [(c, 3)])

    def test_names_need_the_patch(self):
        plain, _ = patcher.build(self.img, self.map, patcher.resolve_patches(["version_tag"]))
        self.assertRaises(soundbank.BankError, soundbank.fill_names, plain, self.map, [(500, "Cat Piano", "")])

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_web_matches_cli(self):
        voices = [(500, "cat_piano", 0, "Cat Piano", "Kocie piano"), (2, "cat_piano", 0, "Meow", "")]
        if SF2:  # a third-party SoundFont: loops, other sample rates, stereo, layers
            sf = sf2.load(SF2)
            usable = []
            for i, *_ in sf.presets:
                try:
                    sf.instrument(i)
                    usable.append(i)
                except sf2.SF2Error:
                    pass
            voices += [(3, SF2, usable[0], "SF2 first", ""), (4, SF2, usable[len(usable) // 2], "SF2 mid", "")]
        names = patcher.defaults(self.map) + ["custom_voices"]
        cli, _ = patcher.build(self.img, self.map, patcher.resolve_patches(names))
        cli = soundbank.fill_names(cli, self.map, [(v, n, p) for v, _, _, n, p in voices])
        insts = [(sf2.load(k if k.endswith(".sf2") else instrument.bundled(k)).instrument(i), v) for v, k, i, *_ in voices]
        cli_bank = soundbank.add(self.bank, self.img, self.map, insts)
        with tempfile.TemporaryDirectory() as d:
            for f in ("index.html", "patcher.js"):
                shutil.copy(os.path.join(web.WEB_DIR, f), d)
            os.mkdir(os.path.join(d, "targets"))
            web.write_target(self.img, self.map, d)
            web.write_packs(d)
            sel = {n: {} for n in names}
            js = [{"voice": v, "pack": k, "preset": i, "name": n, "name_pl": p} for v, k, i, n, p in voices]
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
