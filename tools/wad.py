#!/usr/bin/env python3
"""The game's WAD: lumps, and MUS music as an event stream for the piano's synthesizer.

Default: Freedoom Phase 1 (wad/freedoom1.wad, BSD licensed: https://freedoom.github.io), so builds can be shared;
PIANODOOM_WAD=path picks another one (e.g. your shareware DOOM1.WAD, whose builds stay private).
The map is our own, maps/hangar.wad (tools/makemap.py); PIANODOOM_MAP=path reads E1M1 from another WAD.
The build tools take the same as --wad / --map (use()).

Music stream: two words per event, played by the tick (10 ms):
    w0 = wait << 8 | status    wait = ticks after this event (0..255), status = MIDI status | channel (0: no event)
    w1 = d1 << 8 | d2          as synth_send takes it
and a final w0 = 0x00ff: start over.
"""
import os
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
WAD = os.environ.get("PIANODOOM_WAD") or os.path.join(HERE, "..", "wad", "freedoom1.wad")
MAP = os.environ.get("PIANODOOM_MAP") or os.path.join(HERE, "..", "maps", "hangar.wad")

MUS_CTRL = {1: 0, 2: 1, 3: 7, 4: 10, 5: 11, 6: 91, 7: 93, 8: 64, 9: 67}   # MUS controller -> MIDI CC (0 = program)
FREE = [4, 5, 6, 7, 8, 10, 11, 12, 13, 14, 15]  # melodic channels: 0..3 are the keyboard's parts, 9 percussion
MIDI_FREE = [4, 5, 6, 10, 11, 12, 13, 14, 15]   # a MIDI song's: also clear of the effects (7) and the style's drums (8)
MUS_SYS = {10: 120, 11: 123, 12: 126, 13: 127, 14: 121}


def use(wad=None, map=None):
    """Pick the WAD and the map's WAD for this run and the commands it starts (PIANODOOM_WAD / PIANODOOM_MAP)."""
    global WAD, MAP
    if wad:
        WAD = os.environ["PIANODOOM_WAD"] = os.path.abspath(wad)
    if map:
        MAP = os.environ["PIANODOOM_MAP"] = os.path.abspath(map)
    for path in (WAD, MAP):
        if not os.path.isfile(path):
            raise FileNotFoundError(path)


def shareable():
    """Whether builds may be shared: Freedoom's assets and our own map."""
    ours = os.path.abspath(os.path.join(HERE, "..", "maps"))
    return any(n == "FREEDOOM" for n, _, _ in Wad().lumps) and os.path.dirname(os.path.abspath(MAP)) == ours


class Wad:
    def __init__(self, path=None):
        self.data = open(path or WAD, "rb").read()
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


def midi_events(mid):
    """Standard MIDI file (Freedoom's music) -> the same events as mus_events: the tracks merged over the tempo
    map, the melodic channels in use moved onto MIDI_FREE in order (MIDI 9 stays percussion)."""
    fmt, ntracks, division = struct.unpack(">HHH", mid[8:14])
    assert not division & 0x8000, "SMPTE time"
    p, raw = 8 + struct.unpack(">I", mid[4:8])[0], []
    for track in range(ntracks):
        assert mid[p:p + 4] == b"MTrk"
        end = p + 8 + struct.unpack(">I", mid[p + 4:p + 8])[0]
        p, tick, status = p + 8, 0, 0

        def var():
            nonlocal p
            v = 0
            while True:
                b = mid[p]; p += 1
                v = v << 7 | b & 127
                if not b & 128:
                    return v
        while p < end:
            tick += var()
            if mid[p] & 128:
                status = mid[p]; p += 1
            if status == 0xff:
                kind = mid[p]; p += 1
                n = var()
                if kind == 0x51:
                    raw.append((tick, track, -1, int.from_bytes(mid[p:p + 3], "big"), 0))
                p += n
            elif status in (0xf0, 0xf7):
                p += var()
            else:
                n = 1 if status & 0xf0 in (0xc0, 0xd0) else 2
                d = mid[p:p + n]; p += n
                raw.append((tick, track, status, d[0], d[1] if n == 2 else 0))
        p = end
    raw.sort(key=lambda e: (e[0], e[2] != -1))  # stable: each track keeps its order, tempo first at a tick
    melodic = sorted({e[2] & 15 for e in raw if e[2] & 0xf0 == 0x90 and e[2] & 15 != 9})   # channels with notes
    assert len(melodic) <= len(MIDI_FREE), "more melodic channels than the piano has free"
    moved = {**dict(zip(melodic, MIDI_FREE)), 9: 9}
    out, last, us, tempo = [], 0, 0, 500000
    for tick, _track, st, d1, d2 in raw:
        us += (tick - last) * tempo / division; last = tick
        if st == -1:
            tempo = d1; continue
        kind, ch = st & 0xf0, st & 15
        if ch not in moved:
            continue
        mch = moved[ch]
        if kind == 0x90 and d2 == 0:
            kind = 0x80
        if kind in (0x80, 0x90, 0xe0, 0xc0) or kind == 0xb0 and d1 in set(MUS_CTRL.values()) | set(MUS_SYS.values()):
            out.append((round(us * 140 / 1e6), kind | mch, d1, 0 if kind in (0x80, 0xc0) else d2))
    return out


def mus_events(mus):
    """MUS -> [(time in 1/140 s, status, d1, d2)]."""
    if mus[:4] == b"MThd":
        return midi_events(mus)
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
