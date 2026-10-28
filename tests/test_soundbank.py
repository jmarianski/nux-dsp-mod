"""Instruments added to the official soundbank. Set NEK100_FW and NEK100_SBANK (NEK100_SBANK_V1.0.4.bin) to run
the soundbank tests; NUX_TEST_SF2=/path/to/any.sf2 (e.g. a General MIDI SoundFont) adds a third-party file."""
import json
import os
import shutil
import struct
import subprocess
import tempfile
import unittest

from nuxdsp import container, envelope, fwmap, instrument, patcher, sf2, soundbank, web
from tests import slow

FW, SBANK, SF2 = os.environ.get("NEK100_FW"), os.environ.get("NEK100_SBANK"), os.environ.get("NUX_TEST_SF2")
HERE = os.path.dirname(os.path.abspath(__file__))
# cat_piano on sound 500 (attack-trimmed Cat Piano, samples ending on 256-word blocks, its SoundFont envelope)
CAT_SHA = "8be2ac96da8c9a5b0233b343bafef99abdc9d349f7d4a06ae85980048d9abc9e"   # on the Grand piano template, pianomods (C: 2026-10-18)


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
        out.append(soundbank.sample_block(bank, soundbank.find_sample_block(bank, z)))
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

    def test_loop_end_repeats_start(self):
        """a loop that ends on the sample's end gets the point after it (the device reads it, C: clicks)"""
        pcm = struct.pack("<100h", *range(100))
        got = sf2.SoundFont(sf2.write(sf2.Instrument("L", [sf2.Zone(0, 127, 60, 0, 44100, pcm, (40, 100))])))
        z = got.instrument(0).zones[0]
        self.assertEqual(struct.unpack("<101h", z.pcm)[100], 40)

    def test_envelope_bytes(self):
        for hexs in ("e31fe35f5a60", "e31f3c804a60", "c31fe35f4060"):    # Organ 7, Shamisen, an organ-like one
            segs = envelope.parse(bytes.fromhex("0000" + hexs), 0)
            self.assertEqual(envelope.encode(envelope.decode(segs)).hex(), "00" + hexs)
        self.assertIsNone(envelope.parse(bytes.fromhex("0000e31f"), 0))
        self.assertEqual(envelope.decode(envelope.parse(bytes.fromhex("007fc31f3c804a60"), 0), 0x7F).attack,
                         envelope.seconds(0xE3))                       # starts at full: no attack

    def test_envelope_sf2(self):
        env = envelope.Envelope(0.25, 1.5, -12.0, 0.4)
        z = sf2.Zone(0, 127, 60, 0, 44100, b"\1\0" * 100, None, None, env)
        got = sf2.SoundFont(sf2.write(sf2.Instrument("Env", [z]))).instrument(0).zones[0].env
        self.assertEqual(envelope.encode(got), envelope.encode(env))
        self.assertEqual(envelope.encode(envelope.from_sf2({})), envelope.encode(envelope.Envelope(0, 0, 0, 0)))
        self.assertIsNone(envelope.from_sf2({envelope.GEN_SUSTAIN: 1000}).sustain)

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
                self.assertEqual(E % 512, 511)                                # as all the vendor's loops
                if v == 499:                                                  # looped: L in the first half of
                    self.assertLess(L % 1024, 512)                            # its 1024-word block, or it clicks
                self.assertTrue(S < L < E)
        tz = {k: soundbank.zones(self.bank, soundbank.instrument_addr(self.bank, *soundbank.voice_to_bank_prog(
            soundbank.voice_banks(container.words(self.img), self.map), self.map.soundbank[k][0])))[
            self.map.soundbank[k][1]] for k in soundbank.TEMPLATES}
        banks = soundbank.voice_banks(container.words(self.img), self.map)
        for v, k in ((500, "template_piano"), (499, "template_loop")):
            z = soundbank.zones(out, soundbank.instrument_addr(out, *soundbank.voice_to_bank_prog(banks, v)))[0]
            self.assertEqual(len(soundbank.zone_record(out, z)[0]), len(soundbank.zone_record(self.bank, tz[k])[0]))
        self.assertEqual([V for _, V, *_ in sample_blocks(out, self.img, self.map, 499)],
                         [soundbank.tune_value(57, 4, 44100), soundbank.tune_value(64, -7, 22050)])

    def test_template_kind(self):
        sb = self.map.soundbank
        self.assertEqual(sb["template_piano"], (1, 223))
        self.assertEqual(sb["mods_piano"], (bytes.fromhex("803fffff"), bytes.fromhex("803f2dfd")))
        self.assertTrue(cat().piano)                                   # the cat preset: GM program 0
        self.assertEqual(soundbank.template_kind(cat(), sb), "template_piano")
        self.assertEqual(soundbank.template_kind(saw(), sb), "template_loop")     # not from a preset
        c = cat()
        c.program = 24                                                  # a guitar: a one-shot
        self.assertEqual(soundbank.template_kind(c, sb), "template")
        c.program, c.bank = 0, 1
        self.assertEqual(soundbank.template_kind(c, sb), "template")
        self.assertEqual(soundbank.template_kind(cat(), {k: v for k, v in sb.items() if k != "template_piano"}),
                         "template")

    def test_export_add(self):
        """an official sound exported to SoundFont and added back plays the same samples, tuning and envelope"""
        voice = self.map.soundbank["template"][0]
        ins = sf2.SoundFont(sf2.write(soundbank.export(self.bank, self.img, self.map, voice))).instrument(0)
        out = soundbank.add(self.bank, self.img, self.map, [(ins, 499)])
        a, b = sample_blocks(self.bank, self.img, self.map, voice), sample_blocks(out, self.img, self.map, 499)
        geo = lambda blocks: [(V, E - L) for _, V, S, L, E in blocks]     # flag: the template's; S: may move
        self.assertEqual(geo(a), geo(b))
        banks = soundbank.voice_banks(container.words(self.img), self.map)
        recs = [soundbank.zone_record(d, soundbank.zones(d, soundbank.instrument_addr(
            d, *soundbank.voice_to_bank_prog(banks, v)))[0]) for d, v in ((self.bank, voice), (out, 499))]
        (r0, _, _, sb0), (r1, _, _, sb1) = recs
        a0, a1 = envelope.amp_env_at(r0, sb0), envelope.amp_env_at(r1, sb1)
        self.assertEqual(r1[a1 + 2:a1 + 8], r0[a0 + 2:a0 + 8])
        self.assertEqual(r1[a1 + 1], 0)                            # starts from silence: the attack plays

    def test_several(self):
        c = cat()
        out = soundbank.add(self.bank, self.img, self.map, [(c, 500), (c, 1), (c, 250)])
        self.assertGreater(len(out), len(self.bank))
        self.assertRaises(soundbank.BankError, soundbank.add, self.bank, self.img, self.map, [(c, 3)] * 2)
        self.assertRaises(soundbank.BankError, soundbank.add, self.img, self.img, self.map, [(c, 3)])

    def test_longer_sustain(self):
        banks = soundbank.voice_banks(container.words(self.img), self.map)
        voice, floor = self.map.soundbank["sustain"]

        def falls(bank):
            inst = soundbank.instrument_addr(bank, *soundbank.voice_to_bank_prog(banks, voice))
            out = []
            for layer in soundbank.layers(bank, inst):
                segs = [envelope.parse(bank, envelope.amp_env_at(bank, soundbank.find_sample_block(bank, z)))
                        for z in layer]
                out.append([envelope.seconds(s[1][0]) for s in segs])
            return out
        out = soundbank.longer_sustain(self.bank, self.img, self.map, 3)
        self.assertEqual(len(out), len(self.bank))
        for a, b in zip(falls(self.bank), falls(out)):
            if len(a) == 1:
                self.assertEqual(a, b)                                  # the resonance layer: as it is
            else:
                for t0, t1 in zip(a, b):
                    self.assertAlmostEqual(t1 / max(t0, floor), 3, delta=0.3)
        self.assertRaises(soundbank.BankError, soundbank.longer_sustain, self.bank, self.img, self.map, 0)

    @slow
    def test_grander(self):
        banks = soundbank.voice_banks(container.words(self.img), self.map)
        src, key, _ = self.map.soundbank["grander"]
        at = lambda bank, v: soundbank.instrument_addr(bank, *soundbank.voice_to_bank_prog(banks, v))
        word = lambda bank, a: struct.unpack_from("<h", bank, (a - soundbank.FLASH_BASE_W) * 2)[0]

        def loops(bank, v):
            """per reshaped zone (not as in the vendor's piano): (S, L, E, X), checked as the vendor's loops are"""
            inst, out = at(bank, v), []
            for layer, keys in zip(soundbank.layers(bank, inst), soundbank._zone_keys(bank, inst)):
                for z, (lo, _) in zip(layer, keys):
                    o = soundbank.find_sample_block(bank, z)
                    _, _, S, L, E = soundbank.sample_block(bank, o)
                    X = soundbank._stereo_x(bank, o)
                    if len(layer) > 1 and lo >= key and (S, L, E) not in vendor:
                        self.assertEqual(E % 512, 511)
                        self.assertLess(L % 1024, 512)
                        self.assertEqual((X - S) % 1024, 0)
                        self.assertEqual(word(bank, E), word(bank, L))          # sample E = sample L
                        self.assertEqual(word(bank, X + E - S), word(bank, X + L - S))
                        out.append((S, L, E, X))
            return out
        vendor = {soundbank.sample_block(self.bank, soundbank.find_sample_block(self.bank, z))[2:]
                  for z in soundbank.zones(self.bank, at(self.bank, src))}
        copy = soundbank.grander(self.bank, self.img, self.map, 2)
        self.assertGreater(len(loops(copy, 2)), 80)                            # (zones; 45 samples)
        g = at(self.bank, src)
        self.assertEqual(at(copy, src), g)                                     # 1.Grand Piano as the vendor's
        self.assertEqual(copy[g:g + 0x8000], self.bank[g:g + 0x8000])
        self.assertEqual([len(x) for x in soundbank.layers(copy, at(copy, 2))], [len(x) for x in soundbank.layers(copy, g)])
        in_place = soundbank.grander(self.bank, self.img, self.map, src)
        self.assertEqual(len(in_place), len(self.bank))
        here = set(loops(in_place, src))
        self.assertEqual(len(here), len(set(loops(copy, 2))))
        self.assertTrue({x[0] for x in here} <= {x[0] for x in vendor})        # the vendor's samples, reshaped
        self.assertEqual(at(in_place, 2), at(self.bank, 2))
        self.assertEqual(soundbank.grander_fall_table(self.bank, self.img, self.map), self.map.soundbank["grander_fall"])
        small = fwmap.load()
        small.soundbank = dict(small.soundbank, end=struct.unpack_from("<I", self.bank, 8)[0] + 0x100000)
        self.assertRaises(soundbank.BankError, soundbank.grander, self.bank, self.img, small, 2)
        self.assertEqual(len(soundbank.grander(self.bank, self.img, small, src)), len(self.bank))   # takes no room

    def test_names_need_the_patch(self):
        plain, _ = patcher.build(self.img, self.map, patcher.resolve_patches(["version_tag"]))
        self.assertRaises(soundbank.BankError, soundbank.fill_names, plain, self.map, [(500, "Cat Piano", "")])

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    @slow
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
        added = soundbank.add(self.bank, self.img, self.map, insts)
        cli_bank = soundbank.longer_sustain(soundbank.grander(added, self.img, self.map, 7), self.img, self.map, 3)
        in_place = soundbank.grander(added, self.img, self.map, 1)
        with tempfile.TemporaryDirectory() as d:
            for f in ("index.html", "patcher.js"):
                shutil.copy(os.path.join(web.WEB_DIR, f), d)
            os.mkdir(os.path.join(d, "targets"))
            with open(os.path.join(d, "targets", self.map.id + ".js"), "w", encoding="utf-8") as f:
                f.write(web.current_target_js(self.img, self.map))
            web.update_index(d)
            web.write_packs(d)
            sel = {n: {} for n in names}
            js = [{"voice": v, "pack": k, "preset": i, "name": n, "name_pl": p} for v, k, i, n, p in voices]
            o, ob = os.path.join(d, "o.bin"), os.path.join(d, "b.bin")
            for sustain, grander, want in (("3", "7", cli_bank), ("0", "1", in_place)):
                subprocess.check_call(["node", os.path.join(HERE, "web_check.js"), d, FW, o, json.dumps(sel),
                                       SBANK, ob, json.dumps(js), sustain, grander])
                with open(o, "rb") as f:
                    self.assertEqual(f.read(), cli)
                with open(ob, "rb") as f:
                    self.assertTrue(f.read() == want, "web and CLI banks differ (Grander Piano on %s)" % grander)

    def test_committed_packs_are_current(self):
        for n in instrument.bundled_names():
            with open(os.path.join(web.WEB_DIR, "instruments", n + ".js"), encoding="utf-8") as f:
                self.assertEqual(f.read(), web.pack_js(n), "run: python3 -m nuxdsp web")
        with open(os.path.join(web.WEB_DIR, "instruments", "index.js"), encoding="utf-8") as f:
            self.assertEqual(f.read(), web.packs_index_js(), "run: python3 -m nuxdsp web")


if __name__ == "__main__":
    unittest.main()
