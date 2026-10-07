"""The volume envelope of a soundbank zone, and its SoundFont 2 counterpart.

In a zone record the volume envelope follows the sample block's "0e 7f" and a 4-byte "06 .." block:
    00 SS  (rate, level) (rate, level) ...       SS: start level 0..127 (H: 0x7f = starts at full, no attack —
                                                  C: attack rates made no difference under Shamisen's 7f)
each pair one segment, the last one with level bit 0x20 (C: grammar holds for 1674 vendor zones):
    rate:  bit 7 = rising, low 7 bits 0..99 (C: 5090 of 5136 vendor rates; 99 = fastest, decimal values
           like 60, 70, 90, 95 typed by hand)
    level: bits 0..4 = target level 0..31, 0x40 = hold here while the key is held, 0x80 = fall to silence
           (no sustain: plucked, percussive), 0x60 = release (to silence), the end
Vendor patterns: (rise, 0x40 hold, release) 1016 zones, (rise, 0x80 fall, release) 385 — e.g. Organ 7
"e3 1f e3 5f 5a 60", Shamisen "e3 1f 3c 80 4a 60", Pad Warm "c2 1f c6 5b 41 60".

Times and levels (C: fitted to a recording of rates 80/60/45/32 rising and 90/74/60/40 falling):
    a segment at rate r takes T(r) = T99 * 2 ** ((99 - r) / D) seconds,
    rising: linear in amplitude from silence to full in T, T99 = 64 ms, D = 8.68 (measured 80: 0.3 s, 60: 1.45 s,
    45: 4.3 s, 32: about 14 s; 99 sounds instant). A softer key aims lower and gets there sooner: the rise has
    a fixed slope, not a fixed time;
    falling: exponential, 60 dB in T, T99 = 70 ms, D = 8.03 (measured 90: about 0.15 s, 74: 0.8 s, 60: 1.1 s,
    40: about 15 s — the room and a turned knob blur these, the fit is within a factor of 2);
    level l is (l - 31) * 1.5 dB.
Only these constants change when they are measured.
"""
import math

RISE_T99, RISE_D = 0.064, 8.68
FALL_T99, FALL_D = 0.070, 8.03
DB_STEP = 1.5
FULL = 31
HOLD, FALL, END = 0x40, 0x80, 0x60


class Envelope:
    """SoundFont-style volume envelope: attack, decay (seconds over the full range), sustain (dB below full,
    None = falls to silence while held), release (seconds)."""

    def __init__(self, attack=0.002, decay=0.0, sustain=0.0, release=0.03):
        self.attack, self.decay, self.sustain, self.release = attack, decay, sustain, release

    def __repr__(self):
        return "Envelope(attack=%.3f, decay=%.3f, sustain=%s, release=%.3f)" % (
            self.attack, self.decay, "None" if self.sustain is None else "%.1f" % self.sustain, self.release)


def seconds(rate):
    """rate byte -> seconds of the segment"""
    t99, dd = (RISE_T99, RISE_D) if rate & 0x80 else (FALL_T99, FALL_D)
    return t99 * 2 ** ((99 - min(rate & 0x7F, 99)) / dd)


def rate(sec, rising):
    t99, dd = (RISE_T99, RISE_D) if rising else (FALL_T99, FALL_D)
    r = 99 - round(dd * math.log2(max(sec, 1e-6) / t99))
    return max(0, min(99, r)) | (0x80 if rising else 0)


def level(db):
    return max(0, min(FULL, FULL + round(db / DB_STEP)))


def parse(rec, at):
    """the segments of the envelope starting at rec[at] (the 00 byte) -> [(rate, level)], or None"""
    if rec[at] != 0:
        return None
    segs, p = [], at + 2
    while p + 1 < len(rec) and len(segs) < 12:
        segs.append((rec[p], rec[p + 1]))
        p += 2
        if rec[p - 1] & 0x20:
            return segs
    return None


def decode(segs, start=0):
    """3 segments (rise, hold or fall, release) after start level START -> Envelope; None for other shapes"""
    if len(segs) != 3 or segs[2][1] & 0xE0 != END:
        return None
    (ra, la), (rm, lm), (rr, _) = segs
    if start >= 0x7F:
        ra = 0xE3                                         # starts at full: no attack
    if lm & 0xE0 == FALL:
        return Envelope(seconds(ra), seconds(rm), None, seconds(rr))
    if lm & 0xE0 != HOLD:
        return None
    lv = lm & 0x1F
    decay = 0.0 if lv >= (la & 0x1F) else seconds(rm)
    return Envelope(seconds(ra), decay, (lv - FULL) * DB_STEP, seconds(rr))


def encode(env):
    """Envelope -> start level and 3 segments as bytes (from silence rise to full; hold at the sustain level or
    fall to silence; release)"""
    out = [(rate(env.attack, True), FULL)]
    if env.sustain is None or level(env.sustain) == 0:
        out.append((rate(env.decay, False), FALL))
    elif level(env.sustain) >= FULL or env.decay <= 0:
        out.append((rate(0, True), HOLD | level(env.sustain)))
    else:
        out.append((rate(env.decay, False), HOLD | level(env.sustain)))
    out.append((rate(env.release, False), END))
    return bytes([0]) + bytes(b for s in out for b in s)


def amp_env_at(rec, sb_off):
    """offset in a zone record of its volume envelope (the 00 byte): after the sample block's 0e 7f and 06 .."""
    at = sb_off + 18
    if rec[at:at + 2] != b"\x0e\x7f" or rec[at + 2] != 0x06:
        return None
    return at + 6


# SoundFont 2 generators (timecents, centibels)
GEN_ATTACK, GEN_DECAY, GEN_SUSTAIN, GEN_RELEASE = 34, 36, 37, 38
SF2_DEFAULT = {GEN_ATTACK: -12000, GEN_DECAY: -12000, GEN_SUSTAIN: 0, GEN_RELEASE: -12000}
SILENT_CB = 960        # sustain attenuation from which a SoundFont envelope counts as falling to silence


def from_sf2(gens):
    """generator values (already summed over preset and instrument, missing ones absent) -> Envelope"""
    tc = lambda op: 2 ** (gens.get(op, SF2_DEFAULT[op]) / 1200)
    sus = gens.get(GEN_SUSTAIN, 0)
    return Envelope(tc(GEN_ATTACK), tc(GEN_DECAY), None if sus >= SILENT_CB else -sus / 10, tc(GEN_RELEASE))


def to_sf2(env):
    """Envelope -> [(generator, value)] for an instrument zone"""
    tc = lambda s: max(-12000, min(8000, round(1200 * math.log2(max(s, 0.001)))))
    sus = 1440 if env.sustain is None else max(0, min(1440, round(-env.sustain * 10)))
    out = [(GEN_ATTACK, tc(env.attack)), (GEN_DECAY, tc(env.decay) if env.decay > 0 else -12000),
           (GEN_SUSTAIN, sus), (GEN_RELEASE, tc(env.release))]
    return [(g, v & 0xFFFF) for g, v in out]
