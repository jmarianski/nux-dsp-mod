"""SoundFont 2 (.sf2): read a preset as an Instrument for soundbank.py, and write one (`nuxdsp pack`).

What carries over to the instrument (one sample per key range, played by the template zone of the target):
key ranges, root keys, tuning (coarse, fine, the sample's pitch correction), sample rate, loops (sampleModes
1/3: the loop plays while the key is held; otherwise one-shot). Of several velocity layers the one sounding at
VELOCITY is taken; of layers over the same keys, the first one of each key; linked stereo samples are mixed to mono; zones at the same pitch on every key (noise layers)
are left out, presets made only of such (drum kits, effects) refused. Envelopes, filters, modulators, effects: not
(the template zone's settings apply). The JavaScript in web/patcher.js mirrors this file.
"""
import struct

VELOCITY = 100
GEN_KEYRANGE, GEN_VELRANGE, GEN_INSTRUMENT, GEN_SAMPLE = 43, 44, 41, 53
GEN_COARSE, GEN_FINE, GEN_MODES, GEN_ROOT, GEN_SCALE = 51, 52, 54, 58, 56
RANGES = (GEN_KEYRANGE, GEN_VELRANGE)
DRUM_BANKS = (120, 128)  # percussion: SF2 bank 128, GM2 rhythm bank 120


class SF2Error(Exception):
    pass


class Zone:
    """lo..hi: MIDI keys (inclusive); pcm: s16le mono; loop: (start, end) in samples, SF2 style
    (pcm[end] is the point after the loop, equal to pcm[start]) or None for one-shot."""

    def __init__(self, lo, hi, root, cents, rate, pcm, loop=None, key=None):
        self.lo, self.hi, self.root, self.cents, self.rate, self.pcm, self.loop = lo, hi, root, cents, rate, pcm, loop
        self.key = key  # same key = same sample data (stored once)


class Instrument:
    def __init__(self, name, zones, info=None):
        self.name, self.zones, self.info = name, zones, dict(info or {})

    @property
    def size(self):
        return sum(len(z.pcm) for z in {z.key or id(z): z for z in self.zones}.values())


def _chunks(data, o, end):
    while o + 8 <= end:
        cid, n = data[o:o + 4], struct.unpack_from("<I", data, o + 4)[0]
        yield cid, o + 8, n
        o += 8 + n + (n & 1)


def _str(b):
    return b.split(b"\0", 1)[0].decode("latin-1").strip()


class SoundFont:
    def __init__(self, data):
        if data[:4] != b"RIFF" or data[8:12] != b"sfbk":
            raise SF2Error("not a SoundFont 2 file (.sf2)")
        self.data, self.info, lists = data, {}, {}
        for cid, o, n in _chunks(data, 12, len(data)):
            if cid == b"LIST":
                lists[data[o:o + 4]] = (o + 4, o + n)
        if not all(k in lists for k in (b"INFO", b"sdta", b"pdta")):
            raise SF2Error("incomplete SoundFont")
        for cid, o, n in _chunks(data, *lists[b"INFO"]):
            if cid != b"ifil":
                self.info[cid.decode("latin-1")] = _str(data[o:o + n])
        self.smpl = None
        for cid, o, n in _chunks(data, *lists[b"sdta"]):
            if cid == b"smpl":
                self.smpl = (o, n // 2)
        if self.smpl is None:
            raise SF2Error("no samples (sdta/smpl) in the SoundFont")
        p = {cid.decode(): (o, n) for cid, o, n in _chunks(data, *lists[b"pdta"])}

        def recs(name, size, fmt):
            o, n = p[name]
            return [struct.unpack_from(fmt, data, o + i * size) for i in range(n // size)]
        self.phdr = [(_str(r[0]), r[1], r[2], r[3]) for r in recs("phdr", 38, "<20sHHH")]
        self.pbag = recs("pbag", 4, "<HH")
        self.pgen = recs("pgen", 4, "<HH")
        self.inst = [(_str(r[0]), r[1]) for r in recs("inst", 22, "<20sH")]
        self.ibag = recs("ibag", 4, "<HH")
        self.igen = recs("igen", 4, "<HH")
        self.shdr = [(_str(r[0]),) + r[1:] for r in recs("shdr", 46, "<20sIIIIIBbHH")]

    @property
    def presets(self):
        """[(index, bank, program, name)] (the terminal record left out)"""
        return sorted(((i, b, prg, n) for i, (n, prg, b, _) in enumerate(self.phdr[:-1])), key=lambda x: (x[1], x[2]))

    def _zones(self, bags, gens, first, last):
        """generator dicts of the zones in bags[first:last]; a leading zone without the terminal
        generator (instrument / sampleID) is the global one, returned apart."""
        zs = []
        for b in range(first, last):
            g = {}
            for k in range(bags[b][0], bags[b + 1][0]):
                op, amt = gens[k]
                g[op] = amt
            zs.append(g)
        term = GEN_INSTRUMENT if gens is self.pgen else GEN_SAMPLE
        glob = zs.pop(0) if zs and term not in zs[0] else {}
        return glob, [z for z in zs if term in z]

    def instrument(self, preset, velocity=VELOCITY):
        """the preset (index into phdr) -> Instrument"""
        name = self.phdr[preset][0]
        if self.phdr[preset][2] in DRUM_BANKS:
            raise SF2Error("drum kit (bank %d): not supported, the sound follows the keyboard" % self.phdr[preset][2])
        pg, pz = self._zones(self.pbag, self.pgen, self.phdr[preset][3], self.phdr[preset + 1][3])
        regions = []
        for z in pz:
            pzone = {**pg, **z}
            i = pzone[GEN_INSTRUMENT]
            ig, iz = self._zones(self.ibag, self.igen, self.inst[i][1], self.inst[i + 1][1])
            for z2 in iz:
                izone = {**ig, **z2}
                key = _isect(_range(pzone, GEN_KEYRANGE), _range(izone, GEN_KEYRANGE))
                vel = _isect(_range(pzone, GEN_VELRANGE), _range(izone, GEN_VELRANGE))
                if key and vel and vel[0] <= velocity <= vel[1]:
                    regions.append((key, izone, pzone))
        if not regions:
            raise SF2Error("preset %r has no samples at velocity %d" % (name, velocity))
        # zones at the same pitch on every key (breath or key noise layers, drum kits): left out
        regions = [r for r in regions if _s16(r[1].get(GEN_SCALE, 100)) == 100]
        if not regions:
            raise SF2Error("same pitch on every key (drum kits, effects): not supported, the sound follows the keyboard")
        zones, done = [], set()
        for n, (key, iz, pz) in enumerate(regions):  # one sample per key range: stereo pairs mixed
            if n in done:
                continue
            done.add(n)
            sid = iz[GEN_SAMPLE]
            pair = None
            if self.shdr[sid][9] & 6:  # right / left sample: mix with its linked one
                pair = next((m for m, (k2, iz2, _) in enumerate(regions) if m not in done and k2 == key
                             and iz2[GEN_SAMPLE] == self.shdr[sid][8]), None)
                if pair is not None:
                    done.add(pair)
            zones.append(self._zone(key, iz, pz, None if pair is None else regions[pair][1]))
        # layers (zones over the same keys, e.g. a second one an octave up): each key gets the zone of the
        # first layer that has it, in the file's order, so neighbouring keys stay in one layer
        owner = [next((z for z in zones if z.lo <= k <= z.hi), None) for k in range(128)]
        out = []
        for k, z in enumerate(owner):
            if z is None:
                continue
            if out and owner[k - 1] is z:
                out[-1].hi = k
            else:
                out.append(Zone(k, k, z.root, z.cents, z.rate, z.pcm, z.loop, z.key))
        return Instrument(name, out, self.info)

    def _sample(self, iz):
        sid = iz[GEN_SAMPLE]
        if sid >= len(self.shdr) - 1:
            raise SF2Error("bad sample index")
        _, start, end, ls, le, rate, pitch, corr, link, typ = self.shdr[sid]
        if typ & 0x8000:
            raise SF2Error("ROM samples are not supported")
        g = lambda op: _s16(iz.get(op, 0))
        start += g(0) + 32768 * g(4)
        end += g(1) + 32768 * g(12)
        ls += g(2) + 32768 * g(45)
        le += g(3) + 32768 * g(50)
        if not 0 <= start < end <= self.smpl[1]:
            raise SF2Error("sample %r outside the sample data" % self.shdr[sid][0])
        o = self.smpl[0] + 2 * start
        return self.data[o:o + 2 * (end - start)], start, end, ls, le, rate, pitch, corr

    def _zone(self, key, iz, pz, iz2):
        pcm, start, end, ls, le, rate, pitch, corr = self._sample(iz)
        skey = (iz[GEN_SAMPLE], start, end)
        if iz2 is not None:
            pcm2 = self._sample(iz2)[0]
            n = min(len(pcm), len(pcm2)) // 2
            a, b = struct.unpack("<%dh" % n, pcm[:2 * n]), struct.unpack("<%dh" % n, pcm2[:2 * n])
            pcm = struct.pack("<%dh" % n, *((x + y) >> 1 for x, y in zip(a, b)))
            skey += (iz2[GEN_SAMPLE],)
        root = _s16(iz.get(GEN_ROOT, -1))
        root = pitch if root < 0 else root
        cents = 100 * (_s16(iz.get(GEN_COARSE, 0)) + _s16(pz.get(GEN_COARSE, 0))) + \
            _s16(iz.get(GEN_FINE, 0)) + _s16(pz.get(GEN_FINE, 0)) + corr
        loop = None
        if iz.get(GEN_MODES, 0) & 1 and start <= ls < le <= end:
            loop = (ls - start, le - start)
            pcm = pcm[:2 * (le - start + 1)]  # nothing after the loop is ever played
            skey += ("loop", ls, le)
        return Zone(key[0], key[1], root, cents, rate, pcm, loop, skey)


def _s16(v):
    return v - 0x10000 if v & 0x8000 else v


def _range(z, op):
    v = z.get(op)
    return (0, 127) if v is None else (v & 0xFF, v >> 8)


def _isect(a, b):
    lo, hi = max(a[0], b[0]), min(a[1], b[1])
    return (lo, hi) if lo <= hi else None


def load(path):
    with open(path, "rb") as f:
        return SoundFont(f.read())


# --- writing (one preset, one instrument, mono samples) ---
def _chunk(cid, body):
    return cid + struct.pack("<I", len(body)) + body + (b"\0" if len(body) & 1 else b"")


def _list(kind, body):
    return _chunk(b"LIST", kind + body)


def _zstr(s, n=None):
    b = s.encode("latin-1", "replace")
    if n:
        return b[:n - 1].ljust(n, b"\0")
    b += b"\0"
    return b + (b"\0" if len(b) & 1 else b"")


def write(inst):
    """Instrument -> .sf2 bytes. info keys: INAM (bank name), IENG (author), ICOP (license), ICMT (source...)."""
    smpl, shdr, igen, ibag = b"", b"", b"", b""
    for n, z in enumerate(inst.zones):
        start = len(smpl) // 2
        smpl += z.pcm + b"\0" * 92                       # 46 zero points after each sample (SF2 rule)
        end = start + len(z.pcm) // 2
        ls, le = (start + z.loop[0], start + z.loop[1]) if z.loop else (start, end)
        c = round(z.cents)
        whole, frac = (c // 100, c % 100) if c >= 0 else (-(-c // 100), -(-c % 100))
        shdr += struct.pack("<20sIIIIIBbHH", _zstr("%s %d" % (inst.name[:14], z.root), 20), start, end, ls, le,
                            z.rate, z.root, 0, 0, 1)
        ibag += struct.pack("<HH", len(igen) // 4, 0)
        gens = [(GEN_KEYRANGE, z.lo | z.hi << 8)]
        if whole:
            gens.append((GEN_COARSE, whole & 0xFFFF))
        if frac:
            gens.append((GEN_FINE, frac & 0xFFFF))
        if z.loop:
            gens.append((GEN_MODES, 1))
        gens.append((GEN_SAMPLE, n))
        igen += b"".join(struct.pack("<HH", *g) for g in gens)
    shdr += struct.pack("<20sIIIIIBbHH", _zstr("EOS", 20), 0, 0, 0, 0, 0, 0, 0, 0, 0)
    ibag += struct.pack("<HH", len(igen) // 4, 0)
    igen += struct.pack("<HH", 0, 0)
    pdta = (_chunk(b"phdr", struct.pack("<20sHHHIII", _zstr(inst.name, 20), 0, 0, 0, 0, 0, 0) +
                   struct.pack("<20sHHHIII", _zstr("EOP", 20), 0, 0, 1, 0, 0, 0)) +
            _chunk(b"pbag", struct.pack("<HHHH", 0, 0, 1, 0)) +
            _chunk(b"pmod", b"\0" * 10) +
            _chunk(b"pgen", struct.pack("<HHHH", GEN_INSTRUMENT, 0, 0, 0)) +
            _chunk(b"inst", struct.pack("<20sH", _zstr(inst.name, 20), 0) + struct.pack("<20sH", _zstr("EOI", 20),
                                                                                         len(inst.zones))) +
            _chunk(b"ibag", ibag) + _chunk(b"imod", b"\0" * 10) + _chunk(b"igen", igen) + _chunk(b"shdr", shdr))
    info = _chunk(b"ifil", struct.pack("<HH", 2, 1)) + _chunk(b"isng", _zstr("EMU8000"))
    info += _chunk(b"INAM", _zstr(inst.info.get("INAM", inst.name)))
    for k in ("IENG", "ICOP", "ICMT", "ISFT"):
        if inst.info.get(k):
            info += _chunk(k.encode(), _zstr(inst.info[k]))
    body = b"sfbk" + _list(b"INFO", info) + _list(b"sdta", _chunk(b"smpl", smpl)) + _list(b"pdta", pdta)
    return b"RIFF" + struct.pack("<I", len(body)) + body
