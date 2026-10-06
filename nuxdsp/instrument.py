"""Instrument packs (.nxi): samples and names of one instrument to add to a soundbank.

Layout: b"NXI1", u32 LE length of the JSON header, the header (UTF-8), then the samples one after another,
16-bit signed little-endian mono, 44.1 kHz. Header:
    {"name": "Cat Piano", "name_pl": "Kocie piano", "cents": -9,
     "author": "...", "source": "...", "license": "CC0",
     "zones": [{"root": 24, "samples": 32193}, ...]}
Each zone is one sample recorded (or pitched) at its root key (MIDI note), played on the keys between its
neighbours' roots. cents tunes the whole instrument. Packs hold no vendor data: the zone settings (envelope,
filter, ...) are copied from the user's own soundbank at build time (soundbank.py).
"""
import json
import os
import re
import struct
import wave

MAGIC = b"NXI1"
PACK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "instruments")
MAX_NAME = 11      # "500." + name must fit the 15 characters custom_voices draws


class PackError(Exception):
    pass


class Pack:
    def __init__(self, header, pcm):
        self.header, self.pcm = header, pcm          # pcm: list of bytes, one per zone
        if len(pcm) != len(header["zones"]):
            raise PackError("zone count mismatch")
        roots = [z["root"] for z in header["zones"]]
        if roots != sorted(set(roots)) or not all(0 <= r <= 127 for r in roots):
            raise PackError("zone roots must be increasing MIDI notes")
        for n in ("name", "name_pl"):
            if len(header.get(n, "")) > MAX_NAME:
                raise PackError("%s longer than %d characters" % (n, MAX_NAME))
        if not header.get("name"):
            raise PackError("the pack needs a name")

    @property
    def name(self):
        return self.header["name"]

    @property
    def roots(self):
        return [z["root"] for z in self.header["zones"]]

    def to_bytes(self):
        h = json.dumps(self.header, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return MAGIC + struct.pack("<I", len(h)) + h + b"".join(self.pcm)


def from_bytes(data):
    if data[:4] != MAGIC:
        raise PackError("not an instrument pack (.nxi)")
    n = struct.unpack_from("<I", data, 4)[0]
    header = json.loads(data[8:8 + n].decode("utf-8"))
    pcm, o = [], 8 + n
    for z in header["zones"]:
        pcm.append(bytes(data[o:o + 2 * z["samples"]]))
        o += 2 * z["samples"]
    if o != len(data):
        raise PackError("pack size does not match its zones")
    return Pack(header, pcm)


def load(path):
    with open(path, "rb") as f:
        return from_bytes(f.read())


def _read_sample(path):
    if path.endswith(".raw"):
        with open(path, "rb") as f:
            return f.read()
    with wave.open(path, "rb") as w:
        if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (1, 2, 44100):
            raise PackError("%s: needs mono 16-bit 44.1 kHz" % path)
        return w.readframes(w.getnframes())


def make(sample_dir, name, name_pl="", cents=0, **info):
    """A pack from SAMPLE_DIR/r<midi>.wav (or .raw: s16le mono 44.1 kHz), each pitched to its root key."""
    files = {}
    for f in os.listdir(sample_dir):
        m = re.fullmatch(r"r0*(\d+)\.(wav|raw)", f)
        if m:
            files[int(m.group(1))] = os.path.join(sample_dir, f)
    if not files:
        raise PackError("no r<midi>.wav / r<midi>.raw samples in %s" % sample_dir)
    pcm = [_read_sample(files[r]) for r in sorted(files)]
    header = {"name": name, "name_pl": name_pl, "cents": cents}
    header.update({k: v for k, v in info.items() if v})
    header["zones"] = [{"root": r, "samples": len(p) // 2} for r, p in zip(sorted(files), pcm)]
    return Pack(header, pcm)


def bundled_names():
    if not os.path.isdir(PACK_DIR):
        return []
    return sorted(f[:-4] for f in os.listdir(PACK_DIR) if f.endswith(".nxi"))


def bundled(name):
    if name not in bundled_names():
        raise PackError("no bundled instrument pack %r (have: %s)" % (name, ", ".join(bundled_names()) or "none"))
    return os.path.join(PACK_DIR, name + ".nxi")
