"""Instruments to add to a soundbank: SoundFont 2 files (sf2.py), the bundled ones in instruments/.

instruments/index.json adds what a SoundFont has no field for: {"cat_piano": {"name_pl": "Kocie piano"}}.
`nuxdsp pack` makes a SoundFont from a directory of samples, one per root key.
"""
import json
import os
import re
import wave

from . import sf2

PACK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "instruments")
MAX_NAME = 11      # "500." + name must fit the 15 characters custom_voices draws


class PackError(Exception):
    pass


def bundled_names():
    if not os.path.isdir(PACK_DIR):
        return []
    return sorted(f[:-4] for f in os.listdir(PACK_DIR) if f.endswith(".sf2"))


def bundled(name):
    if name not in bundled_names():
        raise PackError("no bundled instrument %r (have: %s)" % (name, ", ".join(bundled_names()) or "none"))
    return os.path.join(PACK_DIR, name + ".sf2")


def bundled_meta(name):
    path = os.path.join(PACK_DIR, "index.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f).get(name, {})


def parse_spec(spec):
    """'FILE.sf2' or a bundled name, optionally '@PRESET' (index in the file's preset list, or its name)
    -> (Instrument, Polish name of a bundled one or "")"""
    path, _, preset = spec.partition("@")
    meta = {}
    if not path.endswith(".sf2"):
        meta, path = bundled_meta(path), bundled(path)
    sf = sf2.load(path)
    presets = sf.presets
    if not preset:
        if len(presets) > 1:
            raise PackError("%s has %d presets, choose one with @: %s" % (
                path, len(presets), "; ".join("%d=%s" % (n, p[3]) for n, p in enumerate(presets))))
        pick = presets[0]
    elif preset.isdigit() and int(preset) < len(presets):
        pick = presets[int(preset)]
    else:
        pick = next((p for p in presets if p[3] == preset), None)
        if pick is None:
            raise PackError("%s: no preset %r" % (path, preset))
    return sf.instrument(pick[0]), meta.get("name_pl", "")


def _read_sample(path):
    if path.endswith(".raw"):
        with open(path, "rb") as f:
            return f.read()
    with wave.open(path, "rb") as w:
        if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (1, 2, 44100):
            raise PackError("%s: needs mono 16-bit 44.1 kHz" % path)
        return w.readframes(w.getnframes())


def make(sample_dir, name, cents=0, info=None):
    """An Instrument from SAMPLE_DIR/r<midi>.wav (or .raw: s16le mono 44.1 kHz), each pitched to its root key;
    each sample plays from its root key up to the key below the next one."""
    files = {}
    for f in os.listdir(sample_dir):
        m = re.fullmatch(r"r0*(\d+)\.(wav|raw)", f)
        if m:
            files[int(m.group(1))] = os.path.join(sample_dir, f)
    if not files:
        raise PackError("no r<midi>.wav / r<midi>.raw samples in %s" % sample_dir)
    roots = sorted(files)
    zones = [sf2.Zone(0 if i == 0 else r, 127 if i == len(roots) - 1 else roots[i + 1] - 1, r, cents, 44100,
                      _read_sample(files[r])) for i, r in enumerate(roots)]
    return sf2.Instrument(name, zones, info)
