#!/usr/bin/env python3
"""DOOM1.WAD (kept local in wad/, not in git): lumps, and MUS music as an event stream for the piano's synthesizer.

Music stream: two words per event, played by the tick (10 ms):
    w0 = wait << 8 | status    wait = ticks after this event (0..255), status = MIDI status | channel (0: no event)
    w1 = d1 << 8 | d2          as synth_send takes it
and a final w0 = 0x00ff: start over.
"""
import os
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
WAD = os.path.join(HERE, "..", "wad", "DOOM1.WAD")

MUS_CTRL = {1: 0, 2: 1, 3: 7, 4: 10, 5: 11, 6: 91, 7: 93, 8: 64, 9: 67}   # MUS controller -> MIDI CC (0 = program)
FREE = [4, 5, 6, 7, 8, 10, 11, 12, 13, 14, 15]  # melodic channels: 0..3 are the keyboard's parts, 9 percussion
MUS_SYS = {10: 120, 11: 123, 12: 126, 13: 127, 14: 121}


class Wad:
    def __init__(self, path=WAD):
        self.data = open(path, "rb").read()
        n, off = struct.unpack("<4xII", self.data[:12])
        self.lumps = []
        for i in range(n):
            o, s, name = struct.unpack("<II8s", self.data[off + 16 * i:off + 16 * i + 16])
            self.lumps.append((name.rstrip(b"\0").decode("ascii"), o, s))

    def lump(self, name, after=None):
        start = 0
        if after:
            start = [k for k, l in enumerate(self.lumps) if l[0] == after][0]
        for nm, o, s in self.lumps[start:]:
            if nm == name:
                return self.data[o:o + s]
        raise KeyError(name)


def mus_events(mus):
    """MUS -> [(time in 1/140 s, status, d1, d2)]."""
    assert mus[:4] == b"MUS\x1a"
    length, start = struct.unpack("<HH", mus[4:8])
    p, t, out = start, 0, []
    vol = [127] * 16
    while True:
        b = mus[p]; p += 1
        last, kind, ch = b >> 7, b >> 4 & 7, b & 15
        mch = 9 if ch == 15 else FREE[ch % len(FREE)]     # MUS 15 = percussion = MIDI 9
        if kind == 0:
            out.append((t, 0x80 | mch, mus[p] & 127, 0)); p += 1
        elif kind == 1:
            n = mus[p]; p += 1
            if n & 128:
                vol[ch] = mus[p] & 127; p += 1
            out.append((t, 0x90 | mch, n & 127, vol[ch]))
        elif kind == 2:
            v = mus[p] << 6; p += 1
            out.append((t, 0xe0 | mch, v & 127, v >> 7 & 127))
        elif kind == 3:
            c = mus[p]; p += 1
            if c in MUS_SYS:
                out.append((t, 0xb0 | mch, MUS_SYS[c], 0))
        elif kind == 4:
            c, v = mus[p], mus[p + 1] & 127; p += 2
            if c == 0:
                out.append((t, 0xc0 | mch, v, 0))
            elif c in MUS_CTRL:
                out.append((t, 0xb0 | mch, MUS_CTRL[c], v))
        elif kind == 6:
            return out
        if last:
            d = 0
            while True:
                b = mus[p]; p += 1
                d = d << 7 | b & 127
                if not b & 128:
                    break
            t += d


def mus_stream(mus, hz=100):
    """MUS -> the piano's music stream (words)."""
    ev = mus_events(mus)
    words = []
    for k, (t, st, d1, d2) in enumerate(ev):
        now = t * hz // 140
        nxt = ev[k + 1][0] * hz // 140 if k + 1 < len(ev) else now
        wait = nxt - now
        words += [min(wait, 255) << 8 | st, d1 << 8 | d2]
        wait -= min(wait, 255)
        while wait:
            words += [min(wait, 255) << 8, 0]
            wait -= min(wait, 255)
    return words + [0x00ff, 0]


if __name__ == "__main__":
    w = Wad()
    for name in ("D_E1M1", "D_INTRO"):
        try:
            s = mus_stream(w.lump(name))
        except KeyError:
            continue
        ev = mus_events(w.lump(name))
        print(name, "events", len(ev), "words", len(s), "seconds %.1f" % (ev[-1][0] / 140),
              "programs", sorted({(e[1] & 15, e[2]) for e in ev if e[1] & 0xf0 == 0xc0}))
