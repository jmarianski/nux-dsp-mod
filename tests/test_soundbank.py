"""Instruments added to the official soundbank. Set NEK100_FW and NEK100_SBANK (NEK100_SBANK_V1.0.4.bin) to run
the soundbank tests; NUX_TEST_SF2=/path/to/any.sf2 (e.g. a General MIDI SoundFont) adds a third-party file."""
import json
import os
import shutil
import struct
import subprocess
import tempfile
import unittest

from nuxdsp import container, fwmap, instrument, patcher, sf2, soundbank, web

FW, SBANK, SF2 = os.environ.get("NEK100_FW"), os.environ.get("NEK100_SBANK"), os.environ.get("NUX_TEST_SF2")
HERE = os.path.dirname(os.path.abspath(__file__))
# cat_piano on sound 500: the bank played on hardware (attack-trimmed Cat Piano, samples ending on 256-word blocks)
CAT_SHA = "6dfc7711d0753ed8a6b2c1dddee5c61965d5e2deed5a6fcd6b187b2c2c53cbcc"


def cat():
    return sf2.load(instrument.bundled("cat_piano")).instrument(0)


def saw(period=200):
    """a looped instrument: one cycle of a saw (period 200 gave an odd tuning before tunings were made even)"""
    s = [int(20000 * (i / period * 2 - 1)) for i in range(period)] * 3
    return sf2.Instrument("Saw", [sf2.Zone(0, 59, 57, 4, 44100, struct.pack("<%dh" % (len(s) + 1), *s, s[0]),
                                           (2 * period, 3 * period)),
                                  sf2.Zone(60, 127, 64, -7, 22050, struct.pack("<%dh" % (len(s) + 1), *s, s[0]),
                                           (period, 3 * period))])


def sample_blocks(bank, img, fwmap_, voice):
    """(flag, V, S, L, E) of each zone of the instrument now playing VOICE"""
    banks = soundbank.voice_banks(container.words(img), fwmap_)
    out = []
    for z in soundbank.zones(bank, soundbank.instrument_addr(bank, *soundbank.voice_to_bank_prog(banks, voice))):
        o = soundbank.find_sample_block(bank, z)
        b = bank[o:o + 18]
        hi = ((b[0] >> 6) & 3) | (b[1] << 2)
        a = [(hi << 24) | (struct.unpack_from("<H", b, w)[0] << 8) | b[lo] for w, lo in ((10, 8), (2, 5), (16, 14))]
        out.append((bank[o - 4], struct.unpack_from("<h", bank, o - 2)[0], *a))
    return out


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

    def test_vendor_conventions(self):
        out = soundbank.add(self.bank, self.img, self.map, [(cat(), 500), (saw(), 499)])
        for v in (500, 499):
            for flag, V, S, L, E in sample_blocks(out, self.img, self.map, v):
                self.assertEqual(V % 2, 0, "odd tuning on sound %d" % v)     # breaks the synth (C)
                self.assertEqual(E % soundbank.BLOCK, soundbank.BLOCK - 1)
                self.assertTrue(S < L < E)
        tz = {k: soundbank.zones(self.bank, soundbank.instrument_addr(self.bank, *soundbank.voice_to_bank_prog(
            soundbank.voice_banks(container.words(self.img), self.map), self.map.soundbank[k][0])))[
            self.map.soundbank[k][1]] for k in ("template", "template_loop")}
        banks = soundbank.voice_banks(container.words(self.img), self.map)
        for v, k in ((500, "template"), (499, "template_loop")):
            z = soundbank.zones(out, soundbank.instrument_addr(out, *soundbank.voice_to_bank_prog(banks, v)))[0]
            self.assertEqual(len(soundbank.zone_record(out, z)[0]), len(soundbank.zone_record(self.bank, tz[k])[0]))
        self.assertEqual([V for _, V, *_ in sample_blocks(out, self.img, self.map, 499)],
                         [soundbank.tune_value(57, 4, 44100), soundbank.tune_value(64, -7, 22050)])

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
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        saw_sf2 = os.path.join(tmp.name, "saw.sf2")
        with open(saw_sf2, "wb") as f:
            f.write(sf2.write(saw()))
        voices = [(500, "cat_piano", 0, "Cat Piano", "Kocie piano"), (2, saw_sf2, 0, "Saw", "Piła")]
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
