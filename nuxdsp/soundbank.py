"""Add instruments (sf2.Instrument) to the official soundbank, in place of chosen sounds.

The soundbank (NEK100_SBANK_*.bin) is flashed from word 0x80000 on, so its pointers are flash word addresses
(byte offset / 2 + 0x80000). What we use of it (C: an instrument built this way plays on the NEK-100):
  - a directory at byte 0x252: per program (0..127) a pointer to a list of 4-byte entries
    (bank, page, address of the instrument), ended by ff ff ff ff;
  - an instrument: 4 header bytes (byte 2 = 0x80 | number of zones), then per zone 6 bytes
    (first-zone flag, low key, 0x7f, high key, zone address in the page), 0 0, then the zone records;
  - a zone record holds in-page pointers to its parts and a sample block with the sample's start, loop and
    end addresses (the loop runs L..E, sample E = sample L; one-shots loop over silence at the end; E is the
    last word of a 512-word block, as in ~95% of the vendor's samples, and L in the first half of a 1024-word
    block, as in all their long loops); the word
    before it is the tuning (V, 1/256 semitone, always even). A zone plays the keys above the previous zone's high key.
  - header fields: u32 at 8 and 0x9c = end of the data, at 0xa6 = end of the parameter data. New samples go at
    the end (before the "PackNameDate:" trailer), new instruments into the free rest of the parameter page.
A sound number maps to (bank, program) through the DSP's voice_banks table. The zone settings (envelope, filter,
...) come from a template zone of the target (soundbank line of target.map): one for one-shots, one for instruments
with loops (a sustaining one), one for pianos (GM programs 0..7, loops or not: C, 2026-10-18, SF2 pianos on
3.Bright Piano's zone sound much closer to the computer than on Shamisen's or Organ 10's, on 1.Grand Piano's
loudest layer closer still), except the volume envelope, which is the SF2's (envelope.py), and, when the target
gives them, the velocity modulators ("pianomods": a zone of a velocity layer reacts to velocity only across its
layer's range; C, 2026-10-18: the Grand's loudest layer with Bright Piano's volume modulator follows velocity, and
with the filter open at soft hits too sounds closest to the SoundFont); nothing of the vendor's is in an
instrument file.
A template zone may be stereo (a 22-byte sample block with the right channel's start X, entry flag b1 bit 7, as
1.Grand Piano's): the added instrument's zones then play their mono sample on both channels (X = S).

custom_voices (a DSP patch) shows the new names: fill_names() writes them into its table.
longer_sustain() makes an official sound (the target's "sustain" one: 1.Grand Piano) decay slower while held.
grander() makes "Grander Piano" of 1.Grand Piano: high zones that ring on while held, on another sound or in its place.
"""
import dataclasses
import math
import operator
import struct

from . import asm, container, envelope, patcher, sf2

FLASH_BASE_W = 0x80000
PAD = b"\xef\xad"                 # the bank compiler's filler word 0xadef
DIRECTORY = 0x252
K = -83.996                       # 12*log2(cycles per sample) + V/256 for zones that follow the keyboard
SR = 44100
CV_ENTRY, CV_NAME = 33, 16
BLOCK = 512                       # samples end on the last word of a block of this size, as all the vendor's
LOOP_HALF = 1024                  # a loop must start in the first half of a block of this size, as all the
                                  # vendor's long loops: one starting in the second half clicks after each pass
                                  # (C: 48 sines at random addresses, the click split exactly by L % 1024 < 512)


class BankError(Exception):
    pass


TEMPLATES = ("template", "template_loop", "template_piano")
STEREO = 0x80                     # entry b1: the zone's sample block is the 22-byte stereo one


def template_kind(inst, sb):
    """which template zone of the soundbank line an instrument copies"""
    if getattr(inst, "piano", False) and "template_piano" in sb:
        return "template_piano"
    return "template_loop" if any(z.loop for z in inst.zones) else "template"


def voice_banks(dsp_words, fwmap):
    r0 = fwmap.ramdata[0] + fwmap.symbols()["voice_banks"]
    out = []
    for i in range(0, 64, 2):
        b, n = dsp_words[r0 + i], dsp_words[r0 + i + 1]
        if n == 0:
            break
        out.append((b, n))
    return out


def voice_to_bank_prog(banks, v):
    v -= 1
    for b, n in banks:
        if 0 <= v < n:
            return b, v
        v -= n
    raise BankError("sound %d does not exist" % (v + 1))


def sound_names(dsp_words, fwmap):
    """The 500 sound names of the official DSP file ("1.Grand Piano", ...)."""
    r0, tab = fwmap.ramdata[0], fwmap.symbols()["sound_names"]
    names = []
    for i in range(500):
        a, s = dsp_words[r0 + tab + i], ""
        while dsp_words[r0 + a]:
            s += chr(dsp_words[r0 + a])
            a += 1
        names.append(s)
    return names


def _dir_entry(d, bank, prog):
    a = struct.unpack_from("<H", d, DIRECTORY + 2 * prog)[0] * 2
    while d[a:a + 4] != b"\xff" * 4:
        if d[a] == bank:
            return a
        a += 4
    raise BankError("no instrument for bank %d program %d" % (bank, prog))


def instrument_addr(d, bank, prog):
    a = _dir_entry(d, bank, prog)
    return ((d[a + 1] << 16) | struct.unpack_from("<H", d, a + 2)[0]) * 2


def layers(d, inst):
    """byte offsets of the zone records of an instrument, per layer.
    Header: format, number of layers, [u16 if format & 4: the instrument-level block of 0x44], u16 per layer
    (0x80 | number of its zones); then 6 bytes per zone."""
    page = (inst // 2) & ~0xFFFF
    fmt, nl = d[inst], d[inst + 1]
    o = inst + 2 + (2 if fmt & 4 else 0)
    counts = [struct.unpack_from("<H", d, o + 2 * i)[0] & 0x7F for i in range(nl)]
    o += 2 * nl
    out = []
    for n in counts:
        out.append([(page | struct.unpack_from("<H", d, o + 6 * i + 4)[0]) * 2 for i in range(n)])
        o += 6 * n
    return out


def zones(d, inst):
    """byte offsets of the zone records of an instrument, of all its layers in order."""
    return [z for layer in layers(d, inst) for z in layer]


def find_sample_block(d, zone):
    """the 'fl 0/1 A A 01 f 00 00 Z 00 C C X X Y 00 E E 0e 7f' block inside a zone record, or its stereo
    variant with 4 more bytes at +12 (the right channel's start X: X & 0xff == S & 0xff)."""
    for o in range(zone, zone + 0x80):
        b = d[o:o + 24]
        if b[1] in (0, 1) and b[4] == 1 and b[6:8] == b"\0\0" and b[9] == 0 and (
                b[15] == 0 and b[18:20] == b"\x0e\x7f" or b[12] == b[8] and b[19] == 0 and b[22:24] == b"\x0e\x7f"):
            return o
    raise BankError("no sample block in zone at %#x" % zone)


def block_len(d, o):
    """18, or 22 for the stereo sample block at byte offset o"""
    return 18 if d[o + 15] == 0 and d[o + 18:o + 20] == b"\x0e\x7f" else 22


def set_addrs(rec, S, L, E):
    """rec: an 18- or 22-byte sample block; a stereo one gets X = S (a mono sample on both channels)"""
    hi = S >> 24
    if L >> 24 != hi or E >> 24 != hi:
        raise BankError("sample crosses a 16M-word boundary (on the NEK-100: past the end of the soundbank partition, the instruments do not fit)")
    k = 12 if len(rec) == 18 else 16
    rec[0] = (rec[0] & 0x3F) | ((hi & 3) << 6)
    rec[1] = hi >> 2
    struct.pack_into("<H", rec, 2, (L >> 8) & 0xFFFF)
    rec[5] = L & 0xFF
    rec[8] = S & 0xFF
    struct.pack_into("<H", rec, 10, (S >> 8) & 0xFFFF)
    if k == 16:
        rec[12], rec[13] = S & 0xFF, hi
        struct.pack_into("<H", rec, 14, (S >> 8) & 0xFFFF)
    rec[k + 2] = E & 0xFF
    struct.pack_into("<H", rec, k + 4, (E >> 8) & 0xFFFF)


def vel_mods(rec):
    """offsets in a zone record of its two velocity modulators (filter G1M, volume G2M; 4 bytes each:
    velocity low, velocity high / 2 (low 6 bits), then two values: C, 2026-10-18 on the volume one, 72 ff does not
    follow velocity, 2d fd does; on the filter one, the first value sets the soft hits (1a dark, ff open: C) and
    the second has no audible effect between ff and e0), None where absent"""
    o, out = rec.index(b"\xf0\xb5") + 2, []
    for _ in range(2):
        F, S, V0 = rec[o:o + 3]
        o += 4 + (2 if F & 0x41 else 0)
        out.append(o if S & 0x10 and V0 & 0x08 else None)
        o += 4 if out[-1] is not None else 0
    return out


def tune_value(midi, cents, rate=SR):
    """even: the vendor's tunings all are (1277 of 1277), and an odd one breaks the synth until power-off
    (C: squeal, wrong velocity and octave in other sounds, crashes) — bit 0 is not part of the tuning."""
    f = 440 * 2 ** ((midi - 69) / 12) * 2 ** (cents / 1200)
    return 2 * round(128 * (K - 12 * math.log2(f / rate)))


def zone_record(d, z):
    """template zone: record bytes [z-2, end), offsets of its in-page pointer words, offset of its sample block."""
    page_b = (z // 2 & ~0xFFFF) * 2
    sb = find_sample_block(d, z)
    marker = d.index(b"\xf0\xb5", z)
    ptr_offs = [0] + list(range(4, marker - z + 2, 2))      # word at z-2, then z+2 .. before f0 b5
    ptrs = [struct.unpack_from("<H", d, z - 2 + o)[0] * 2 + page_b for o in ptr_offs]
    if d[max(ptrs) + 2:max(ptrs) + 4] != b"\x03\x04":
        raise BankError("unexpected template zone layout")
    end = max(ptrs) + 26
    rec = bytes(d[z - 2:end])
    if not all(z - 2 <= p < end for p in ptrs):
        raise BankError("template zone points outside itself")
    if rec[sb - z + 2 - 4] & 0x40:
        raise BankError("template zone does not follow the keyboard")
    return rec, ptr_offs, page_b, sb - (z - 2)


def add(bank, dsp_image, fwmap, items, check_sha=True):
    """items: [(sf2.Instrument, sound number 1..500)] -> new soundbank bytes."""
    sb = fwmap.soundbank
    if not sb:
        raise BankError("this target has no soundbank description")
    if check_sha and container.sha256(bank) != sb["sha256"]:
        raise BankError("not the official %s (SHA-256 mismatch) — refusing to patch" % sb["name"])
    voices = [v for _, v in items]
    if len(set(voices)) != len(voices):
        raise BankError("two instruments for the same sound")
    banks = voice_banks(container.words(dsp_image), fwmap)
    d = bytes(bank)
    templates = {}
    for kind in TEMPLATES:                                   # one-shots, instruments with loops, pianos
        tvoice, tzone = sb.get(kind, sb["template"])
        tinst = instrument_addr(d, *voice_to_bank_prog(banks, tvoice))
        tz = zones(d, tinst)[tzone]
        rec, ptr_offs, page_b, sb_off = zone_record(d, tz)
        mods = sb.get("mods" + kind[len("template"):])
        if mods:                                             # the target's velocity modulators
            rec = bytearray(rec)
            for at, mod in zip(vel_mods(rec), mods):
                if at is None:
                    raise BankError("%s: no velocity modulator to replace" % kind)
                rec[at:at + 4] = mod
            rec = bytes(rec)
        # format 0x44 -> 0x40: without the 0x44 instrument-level block (what it holds is not known)
        templates[kind] = (tz, d[tinst] & ~4, rec, ptr_offs, page_b, sb_off)

    tail = d.index(b"PackNameDate:")
    body, trailer = bytearray(d[:tail]), d[tail:]
    placed = []
    for inst, voice in items:                                 # samples: appended at the end of the data
        while len(body) % 0x800:
            body += PAD
        addrs, seen = [], {}
        for z in inst.zones:
            if z.key is not None and z.key in seen:          # the same sample in several zones: stored once
                addrs.append(seen[z.key])
                continue
            pcm, loop = z.pcm, z.loop
            end = loop[1] if loop else len(pcm) // 2 + 63       # E - S
            S = FLASH_BASE_W + (len(body) + 4) // 2           # two zero guard words, then the audio
            body += PAD * ((BLOCK - 1 - (S + end)) % BLOCK)   # E on the last word of a block, as the vendor's
            S = FLASH_BASE_W + (len(body) + 4) // 2
            if loop and (S + loop[0]) % LOOP_HALF >= LOOP_HALF // 2:
                body += PAD * BLOCK                               # L into the first half of its block
                S += BLOCK
            if loop:
                body += b"\0\0\0\0" + pcm
                a = (S, S + loop[0], S + loop[1])
            else:
                body += b"\0\0\0\0" + pcm + b"\0" * 128   # 64 zero words: the silent loop of a one-shot
                E = FLASH_BASE_W + (len(body) - 2) // 2
                a = (S, E - 43, E)
            assert a[2] % BLOCK == BLOCK - 1 and not (loop and a[1] % LOOP_HALF >= LOOP_HALF // 2)
            addrs.append(a)
            if z.key is not None:
                seen[z.key] = a
        placed.append(addrs)
    while len(body) % 0x800:
        body += PAD
    end_w = FLASH_BASE_W + len(body) // 2
    if end_w > sb.get("end", end_w):
        raise BankError("the soundbank would end %.1f MB past its partition" % ((end_w - sb["end"]) * 2 / 2 ** 20))
    struct.pack_into("<I", body, 8, end_w)
    struct.pack_into("<I", body, 0x9C, end_w)

    for (inst, voice), addrs in zip(items, placed):           # instruments: in the free rest of the parameter page
        base = (struct.unpack_from("<I", body, 0xA6)[0] - FLASH_BASE_W) * 2 + 0x10
        page = base // 2 >> 16
        n = len(inst.zones)
        if not 1 <= n <= 127:
            raise BankError("%s: %d zones (1..127)" % (inst.name, n))
        tz, fmt, rec, ptr_offs, page_b, sb_off = templates[template_kind(inst, sb)]
        n_b = block_len(rec, sb_off)
        head = bytearray([fmt, 1, 0x80 | n, 0])              # one layer
        zone_at = base + 4 + 6 * n + 2
        blob, hi = bytearray(), 0
        for i, z in enumerate(inst.zones):
            zstart = zone_at + len(blob)
            lo = hi                                           # a zone plays the keys above the previous one's
            hi = 0xFF if i == n - 1 else z.hi
            head += bytes([0x80 if i == 0 else 0x00, lo | (STEREO if n_b == 22 else 0), 0x7F, hi]) + \
                struct.pack("<H", (zstart + 2) // 2 & 0xFFFF)
            r = bytearray(rec)
            for o in ptr_offs:                                # rebase the in-page pointers
                new = struct.unpack_from("<H", rec, o)[0] * 2 + page_b - (tz - 2) + zstart
                if new // 2 >> 16 != page:
                    raise BankError("instrument crosses a page")
                struct.pack_into("<H", r, o, new // 2 & 0xFFFF)
            blk = bytearray(r[sb_off:sb_off + n_b])
            set_addrs(blk, *addrs[i])
            r[sb_off:sb_off + n_b] = blk
            struct.pack_into("<h", r, sb_off - 2, tune_value(z.root, z.cents, z.rate))
            if z.env is not None:                             # the instrument's volume envelope (envelope.py)
                at = envelope.amp_env_at(r, sb_off)
                if at is None or len(envelope.parse(r, at) or ()) != 3:
                    raise BankError("the template zone's volume envelope is not rise, hold/fall, release")
                r[at + 1:at + 8] = envelope.encode(z.env)
            blob += r
        inst_b = head + b"\0\0" + blob
        free = body[base - 0x10:base + len(inst_b)]
        if base + len(inst_b) > (page + 1) << 17 or any(b not in (0x5E, 0xD0) for b in free):
            raise BankError("no free room for the instrument in the parameter page")
        body[base:base + len(inst_b)] = inst_b
        struct.pack_into("<I", body, 0xA6, FLASH_BASE_W + (base + len(inst_b) + 1) // 2)
        a = _dir_entry(body, *voice_to_bank_prog(banks, voice))  # the sound now plays this instrument
        body[a + 1] = page
        struct.pack_into("<H", body, a + 2, base // 2 & 0xFFFF)
    return bytes(body + trailer)


def _cv_code(fwmap):
    p = patcher.load("custom_voices", fwmap)
    origin = patcher.canonical_layout(fwmap)[p.name]
    return asm.assemble(p.code, fwmap.symbols(), origin=origin, label_prefix=p.name) + (p.hooks[0].addr,)


def table_addr(fwmap):
    """Program address of custom_voices' name table (the canonical layout fixes it)."""
    return _cv_code(fwmap)[1]["cv_tab"]


PL_LETTERS = "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"     # what polish_font adds (lang_pl needs it)


def name_words(voice, name, polish=False):
    s = "%d.%s" % (voice, name) if name else ""
    bad = [c for c in s if not (" " <= c <= "~" or polish and c in PL_LETTERS)]
    if bad:
        raise BankError("name %r: the display has no %s" % (name, "".join(bad)))
    if len(s) >= CV_NAME:
        raise BankError("name %r too long (%d characters with the number, at most %d)" % (s, len(s), CV_NAME - 1))
    return [ord(c) for c in s] + [0] * (CV_NAME - len(s))


def fill_names(dsp_image, fwmap, entries):
    """entries: [(sound number, name, Polish name or "")] -> DSP image (built with custom_voices) with them."""
    w = container.words(dsp_image)
    code, labels, hook = _cv_code(fwmap)
    t = labels["cv_tab"]
    if len(entries) > 4:
        raise BankError("at most 4 added instruments")
    if any(w[a] != v for a, v in code.items()) or labels["cv_name"] not in w[hook:hook + 3]:
        raise BankError("the DSP file needs the custom_voices patch, with its table still empty")
    for i, (voice, name, name_pl) in enumerate(entries):
        e = t + i * CV_ENTRY
        w[e:e + CV_ENTRY] = [voice - 1] + name_words(voice, name) + name_words(voice, name_pl, True)
    out = container.pack(container.fix_checksum(w))
    if container.validate(out):
        raise BankError("internal error: DSP container invalid")
    return out


def longer_sustain(bank, dsp_image, fwmap, factor):
    """bank with the target's sustain sound (soundbank line of target.map: sustain VOICE FLOOR) decaying FACTOR
    times slower while held: the fall of its volume envelopes, zones falling faster than FLOOR s first set to
    FLOOR (1.Grand Piano: the high keys of its velocity 75-84 layer fall in 2-3 s, its other zones in 9-25 s).
    Layers of one zone stay as they are (the Grand's resonance layer). The release (key up) does not change.
    C (2026-10-18, by ear): 3 times is better than the vendor's."""
    voice, floor = fwmap.soundbank["sustain"]
    if not 1 <= factor <= 10:
        raise BankError("sustain factor: 1..10")
    b = bytearray(bank)
    _slow(b, instrument_addr(b, *voice_to_bank_prog(voice_banks(container.words(dsp_image), fwmap), voice)),
          floor, factor)
    return bytes(b)


def _slow(b, inst, floor, factor):
    for layer in layers(b, inst):
        if len(layer) < 2:
            continue
        for z in layer:
            at = envelope.amp_env_at(b, find_sample_block(b, z))
            segs = envelope.parse(b, at) if at is not None else None
            if not segs or len(segs) != 3 or segs[1][1] & 0xE0 != envelope.FALL:
                continue                                      # holds while the key is held: nothing to slow
            t = max(envelope.seconds(segs[1][0]), floor)
            b[at + 4] = envelope.rate(t * factor, False)


def sample_block(d, o):
    """(flag, tuning V, S, L, E) of the (18- or 22-byte) sample block at byte offset o"""
    b = d[o:o + 22]
    k = block_len(d, o) - 2
    hi = ((b[0] >> 6) & 3) | (b[1] << 2)
    S, L, E = ((hi << 24) | (struct.unpack_from("<H", b, w)[0] << 8) | b[lo] for w, lo in ((10, 8), (2, 5), (k, k - 2)))
    return d[o - 4], struct.unpack_from("<h", d, o - 2)[0], S, L, E


def root_of(V, rate=SR):
    """inverse of tune_value: (root key, cents)"""
    f = rate * 2 ** ((K - V / 256) / 12)
    m = 69 + 12 * math.log2(f / 440)
    return round(m), round((m - round(m)) * 100)


def export(bank, dsp_image, fwmap, voice):
    """an official sound -> sf2.Instrument (samples, key ranges, tuning, loops, volume envelope as far as
    envelope.py reads it). For your own tests: the result is the vendor's data, keep it to yourself."""
    banks = voice_banks(container.words(dsp_image), fwmap)
    d = bytes(bank)
    inst = instrument_addr(d, *voice_to_bank_prog(banks, voice))
    if d[inst] != 0x40:
        raise BankError("sound %d: instrument format %#x not supported (velocity layers or a drum kit)" % (voice, d[inst]))
    page = (inst // 2) & ~0xFFFF
    zones_out, o, n = [], inst + 4, d[inst + 2] & 0x7F
    for i in range(n):
        e = d[o + 6 * i:o + 6 * i + 6]                       # a zone plays the keys above the previous one's
        lo, hi_k = (0 if i == 0 else (e[1] & 0x7F) + 1), (127 if e[3] == 0xFF else e[3])
        z = (page | struct.unpack_from("<H", e, 4)[0]) * 2
        try:
            sb_o = find_sample_block(d, z)
        except BankError:
            continue                                          # a zone without a sample of its own
        flag, V, S, L, E = sample_block(d, sb_o)
        w = lambda a: (a - FLASH_BASE_W) * 2
        pcm = d[w(S):w(E) + 2]
        loop = (L - S, E - S) if S < L < E else None             # L = S - 2: no loop (flags 0x81, 0x82 both loop)
        rec_at = sb_o - 4
        at = envelope.amp_env_at(d[sb_o - 4:sb_o + 80], 4)
        env = envelope.decode(envelope.parse(d[rec_at:rec_at + 80], at) or [], d[rec_at + at + 1]) \
            if at is not None else None
        root, cents = root_of(V)
        zones_out.append(sf2.Zone(lo, min(hi_k, 127), root, cents, SR, pcm, loop, ("x", S, E), env))
    if not zones_out:
        raise BankError("sound %d: no zones with samples" % voice)
    return sf2.Instrument(sound_names(container.words(dsp_image), fwmap)[voice - 1].split(".", 1)[1], zones_out,
                          {"ICMT": "exported from the NUX soundbank for local tests only; not for distribution"})


# grander(): the target's "grander" piano (1.Grand Piano) with its high zones ringing on while held. From the
# grander key (F#4) up the vendor's samples are one-shots that fall 30 dB within 0.1-1 s (C, 2026-10-19: they
# fade unnaturally fast next to the low keys). Each gets a loop of 0.6 s starting about 1 s after the hit, its end
# crossfaded into what precedes the loop start, the level before the loop raised towards a level falling with
# pitch, and a gain ramp (even in dB) inside the loop so that the level before its end equals the level after its start (no
# step at the wrap). C, 2026-10-19: early or short loops (9-64 ms, at -18 dB) are heard as repeats from F#4 up;
# these are not. All of it uses + - * / and sqrt only, in a fixed order, so web/patcher.js gets the same bytes.
GRANDER_SUSTAIN = 3                      # and its zones decay as longer_sustain(3) makes them
G_FLAT = 4.0                            # the loop's level evened out by at most 6 dB
G_HOP, G_XF, G_WIN = 441, 8820, 4410     # level curve step, crossfade, the windows compared at the wrap (samples)
G_LOOP, G_MIN_LOOP = 26460, 13230        # loop length (0.6 s: what fits the partition), the shortest one taken
G_START, G_LAST_START = 44100, 66150     # the loop starts 1 s after the hit (earlier in short samples), by 1.5 s
G_LIFT = 1000.0                          # at most +30 dB (energy ratio)
G_PHASE = 256                            # the windows compared for the loop start's phase


def grander_levels(fwmap):
    """per low key from the grander key up: the energy (ratio to the sample's peak) its zone rings at, -24 dB at
    the grander key down to -32 dB at C8"""
    key = fwmap.soundbank["grander"][1]
    return [10 ** ((-24 - 8 * (k - key) / (108 - key)) / 10) for k in range(key, 128)]


def _energy(x, i, j):
    e = 0
    for v in x[i:j]:
        e += v * v
    return e


def _powers(x):
    """x ** (j / 64) for j = 0..64, from square roots"""
    r = [x]
    for _ in range(6):
        r.append(math.sqrt(r[-1]))
    out = []
    for j in range(65):
        v = 1.0
        for m in range(7):
            if j & (64 >> m):
                v *= r[m]
        out.append(v)
    return out


def _along(p, i, n):
    """x ** (i / n) from _powers(x): even in dB, straight between its 65 points"""
    j = i * 64 // n
    return p[j] if j == 64 else p[j] + (p[j + 1] - p[j]) * ((i * 64 - j * n) / n)


def _dot(x, i, y, j, n):
    return sum(map(operator.mul, x[i:i + n], y[j:j + n]))


def _in_phase(c0, c1, s, a, z):
    """the loop start from a on (by at most 1024 words, L still in the first half of its block) whose sound, in the
    middle of the crossfade, is most alike (normalised correlation of both channels over G_PHASE samples) to the
    sound before E it is mixed with: crossfaded out of phase a piano's partials cancel, and each pass of the loop
    pulses (C, 2026-10-20: the earliest start, regardless of phase, sounded unfinished next to the prototype's)
    -> (that start, its correlation)"""
    m = min(G_XF, (z - a) // 3) // 2 + G_PHASE // 2
    e = z - m
    ee = _dot(c0, e, c0, e, G_PHASE) + _dot(c1, e, c1, e, G_PHASE)
    best, out = None, a
    for t in range(a, a + LOOP_HALF):
        if (s + t) % LOOP_HALF >= LOOP_HALF // 2 or t > G_LAST_START or z - t < G_MIN_LOOP:
            continue
        tt = _dot(c0, t - m, c0, t - m, G_PHASE) + _dot(c1, t - m, c1, t - m, G_PHASE)
        if not tt or not ee:
            continue
        r = (_dot(c0, e, c0, t - m, G_PHASE) + _dot(c1, e, c1, t - m, G_PHASE)) / math.sqrt(ee * tt)
        if best is None or r > best:
            best, out = r, t
    return out, best or 0.0


def _reshape(c0, c1, s, level, boost=1.0):
    """left, right channel (ints) of a one-shot starting at a flash word = s mod 1024, the level it should ring at,
    a gain for all of it -> (loop start, loop end (E - S), left, right (ints, E - S + 1 each)), or None if it is too short"""
    n = len(c0)
    a = max(G_XF, min(G_START, n - G_MIN_LOOP - LOOP_HALF))
    while (s + a) % LOOP_HALF >= LOOP_HALF // 2:            # L in the first half of its 1024-word block
        a += 1
    z = min(a + G_LOOP, n - 1)
    z -= (s + z + 1) % BLOCK                                 # E on the last word of a 512-word block
    if a > G_LAST_START or z - a < G_MIN_LOOP:
        return None
    a, r = _in_phase(c0, c1, s, a, z)
    r = max(0.0, min(1.0, r))
    k = a // G_HOP                                            # levels: both channels' energy (their sum cancels
    en = lambda i, j: _energy(c0, i, j) + _energy(c1, i, j)    # in places: C, E5's loop 15 dB too loud)
    p = [en(i * G_HOP, (i + 2) * G_HOP) for i in range(k + 1)]
    top = p.index(max(p))
    peak = p[top]
    if not peak:
        return None
    q, cur = [], peak                                         # the level, never rising again after the peak
    for i, e in enumerate(p):
        if i > top:
            cur = min(cur, e)
        q.append(cur)
    w = min(G_WIN, (z - a) // 4)
    at_l = en(a, a + w) * (2 * G_HOP) / w                     # the level where the loop starts, not the lowest one
    lift = math.sqrt(min(G_LIFT, max(1.0, level * peak / at_l))) if at_l else math.sqrt(G_LIFT)
    fall, up = _powers(q[k] / peak), _powers(lift)
    g = []                                                    # per hop: raised by the share of the fall at L
    for e in q:                                               # its level has fallen by (in dB, in 1/64)
        j = 0
        while j < 64 and fall[j + 1] >= e / peak:
            j += 1
        g.append(up[j])
    ee = en(z - w, z)
    rp = _powers(math.sqrt(en(a, a + w) / ee) if ee else 1.0)
    gain = []
    for t in range(a):
        i = t // G_HOP
        gain.append(g[i] if i >= k else g[i] + (g[i + 1] - g[i]) * ((t - i * G_HOP) / G_HOP))
    fl, H = [], G_HOP                                         # inside the loop, per 20 ms: back to its first
    for i in range((z + 1 - a) // H - 1):                     # window's level, by at most G_FLAT (energy): a slice
        e, ra = en(a + i * H, a + (i + 2) * H), _along(rp, (i + 1) * H, z - a)   # of strings beating, repeated,
        if not fl:                                            # pulses (C, 2026-10-20: D#5, A5 swell 5 dB a pass)
            e0, r0 = e, ra
        fl.append(math.sqrt(max(1 / G_FLAT, min(G_FLAT, e0 * r0 * r0 / (e * ra * ra)))) if e and e0 else 1.0)
    for t in range(a, z + 1):
        u = t - a - H
        i = u // H if u > 0 else 0
        f = fl[0] if u <= 0 else fl[-1] if i >= len(fl) - 1 else fl[i] + (fl[i + 1] - fl[i]) * ((u - i * H) / H)
        gain.append(lift * _along(rp, t - a, z - a) * f)
    ys = [[c[t] * gain[t] * boost for t in range(z + 1)] for c in (c0, c1)]
    xf = min(G_XF, (z - a) // 3)
    for y in ys:                                              # crossfade into what precedes L, its power kept for
        for j in range(xf + 1):                               # sounds as alike as R: equal-power ones swell in phase
            u = j / xf                                        # (C, 2026-10-20: +3 dB each pass, G4 "faluje")
            v = 1 - u
            y[z - xf + j] = (y[z - xf + j] * v + y[a - xf + j] * u) / math.sqrt(v * v + u * u + 2 * r * v * u)
    out = []                                                  # (no further level fix: it scaled the loop's end
    for y in ys:                                              # but not its start, a step heard at each wrap: C)
        y[z] = y[a]                                           # sample E = sample L
        out.append([max(-32768, min(32767, math.floor(v + 0.5))) for v in y])
    return a, z, out[0], out[1]


G_ATTACK, G_MAX_BOOST = 1323, 2.0       # attack: the first 30 ms; changed by at most 3 dB (energy)


def _attack_boosts(d, inst):
    """{(S, L, E): gain} for the samples whose attack (both channels' energy over G_ATTACK) is quieter than the
    median of the five zones around it in its layer (the first layer that has it): raised to it, by at most
    G_MAX_BOOST in energy and short of clipping (their peaks are near full scale: about 1 dB), and the louder
    ones lowered to it, by at most as much. C (2026-10-20): 1.Grand Piano's C6 sounds quieter than the B below
    and the D above; its zone and the next (D#6) dip 2-4 dB below the zones around them."""
    w = lambda a: (a - FLASH_BASE_W) * 2
    out = {}
    for layer in layers(d, inst):
        if len(layer) < 3:
            continue
        info = []
        for z in layer:
            o = find_sample_block(d, z)
            S, L, E = sample_block(d, o)[2:]
            chs = (S, _stereo_x(d, o)) if block_len(d, o) == 22 else (S, S)
            n = min(G_ATTACK, E - S + 1)
            e = sum(_energy(struct.unpack_from("<%dh" % n, d, w(q)), 0, n) for q in chs)
            info.append(((S, L, E), e * G_ATTACK // n, chs, E - S + 1))
        for i, (key, e, chs, n) in enumerate(info):
            if key in out:
                continue
            out[key] = 1.0
            near = sorted(x[1] for x in info[max(0, i - 2):i + 3])
            med = near[len(near) // 2]
            if 0 < e < med:
                top = max(max(abs(v) for v in struct.unpack_from("<%dh" % n, d, w(q))) for q in chs)
                out[key] = max(1.0, min(math.sqrt(min(G_MAX_BOOST, med / e)), 32767 / max(top, 1)))
            elif e > med:
                out[key] = math.sqrt(max(1 / G_MAX_BOOST, med / e))
    return out


def _zone_keys(d, inst):
    """per layer, per zone: (low key, high key); a zone plays the keys above the previous one's"""
    nl = d[inst + 1]
    o = inst + 2 + (2 if d[inst] & 4 else 0) + 2 * nl
    out = []
    for layer in layers(d, inst):
        row, prev = [], -1
        for _ in layer:
            hi = 127 if d[o + 3] == 0xFF else d[o + 3]
            row.append((prev + 1, hi))
            prev, o = hi, o + 6
        out.append(row)
    return out


def _stereo_x(d, o):
    """the right channel's start of the 22-byte sample block at o"""
    return (d[o + 13] << 24) | (struct.unpack_from("<H", d, o + 14)[0] << 8) | d[o + 12]


def _record_ptrs(d, z):
    """offsets in a zone record (from z - 2) of its in-page pointer words, their targets, the record's end"""
    page_b = (z // 2 & ~0xFFFF) * 2
    offs = [0] + list(range(4, d.index(b"\xf0\xb5", z) - z + 2, 2))
    ptrs = [struct.unpack_from("<H", d, z - 2 + o)[0] * 2 + page_b for o in offs]
    end = max(ptrs) + 26
    if d[max(ptrs) + 2:max(ptrs) + 4] != b"\x03\x04" or not all(z - 2 <= p < end for p in ptrs):
        raise BankError("unexpected zone layout at %#x" % z)
    return offs, ptrs, end


def _clone(b, gi, blk_len):
    """copy of the instrument at gi (format 0x44: header, zone entries, its velocity-layer block, zone records) into
    the free rest of the parameter page, its in-page pointers rebased -> the copy's address"""
    nl = b[gi + 1]
    hdr = 4 + 2 * nl
    nz = sum(struct.unpack_from("<H", b, gi + 4 + 2 * i)[0] & 0x7F for i in range(nl))
    page_b = (gi // 2 & ~0xFFFF) * 2
    blk0 = page_b + struct.unpack_from("<H", b, gi + 2)[0] * 2
    base = (struct.unpack_from("<I", b, 0xA6)[0] - FLASH_BASE_W) * 2 + 0x10
    page = base // 2 >> 16
    blk_at = base + hdr + 6 * nz + 2
    inst_b = bytearray(b[gi:gi + hdr + 6 * nz]) + b"\0\0"
    struct.pack_into("<H", inst_b, 2, blk_at // 2 & 0xFFFF)
    blk = bytearray(b[blk0:blk0 + blk_len])
    for o in (4, 8, 12, 16):
        p = page_b + struct.unpack_from("<H", blk, o)[0] * 2
        if not blk0 <= p < blk0 + blk_len:
            raise BankError("the velocity-layer block points outside itself")
        struct.pack_into("<H", blk, o, (p - blk0 + blk_at) // 2 & 0xFFFF)
    inst_b += blk
    recs = {}
    for i, z in enumerate(zones(b, gi)):
        if z not in recs:
            offs, ptrs, end = _record_ptrs(b, z)
            r, at = bytearray(b[z - 2:end]), base + len(inst_b)
            for o, p in zip(offs, ptrs):
                struct.pack_into("<H", r, o, (p - (z - 2) + at) // 2 & 0xFFFF)
            recs[z] = at
            inst_b += r
        struct.pack_into("<H", inst_b, hdr + 6 * i + 4, (recs[z] + 2) // 2 & 0xFFFF)
    if base + len(inst_b) > (page + 1) << 17 or any(x not in (0x5E, 0xD0) for x in b[base - 0x10:base + len(inst_b)]):
        raise BankError("no free room for the copy of the piano in the parameter page")
    b[base:base + len(inst_b)] = inst_b
    struct.pack_into("<I", b, 0xA6, FLASH_BASE_W + (base + len(inst_b) + 1) // 2)
    return base


def grander(bank, dsp_image, fwmap, voice, factor=GRANDER_SUSTAIN):
    """bank with "Grander Piano" on sound VOICE: the target's grander piano (soundbank line of target.map:
    grander VOICE KEY BLOCKLEN) with its zones from KEY up reshaped (above), decaying FACTOR times slower while
    held (longer_sustain). On the piano's own sound its samples are reshaped in place (no room taken; the vendor's
    version is gone from this bank); on another sound a copy of the piano plays reshaped copies of them, appended
    at the end (+14 MB), and the piano stays as the vendor's."""
    sb = fwmap.soundbank or {}
    if "grander" not in sb:
        raise BankError("this target has no piano for grander()")
    src, key, blk_len = sb["grander"]
    banks = voice_banks(container.words(dsp_image), fwmap)
    b = bytearray(bank)
    gi = instrument_addr(b, *voice_to_bank_prog(banks, src))
    if b[gi] != 0x44:
        raise BankError("sound %d: not the piano grander() knows" % src)
    levels = grander_levels(fwmap)
    boosts = _attack_boosts(b, gi)
    w = lambda a: (a - FLASH_BASE_W) * 2
    pcm = lambda a, n: list(struct.unpack_from("<%dh" % n, b, w(a)))
    shaped = {}                                               # (S, L, E) -> (S', L', E', X'), new or in place
    tail = b.index(b"PackNameDate:")
    body, trailer = (b, b"") if voice == src else (b[:tail], b[tail:])
    for layer, keys in zip(layers(b, gi), _zone_keys(b, gi)):
        if len(layer) < 2:                                    # the resonance layer: as it is
            continue
        for z, (lo, _) in zip(layer, keys):
            o = find_sample_block(b, z)
            _, _, S, L, E = sample_block(b, o)
            orig = (S, L, E)
            if lo < key or orig in shaped:
                continue
            if block_len(b, o) != 22:
                raise BankError("zone at %#x: not stereo" % z)
            X = _stereo_x(b, o)
            r = _reshape(pcm(S, E - S + 1), pcm(X, E - S + 1), S % LOOP_HALF, levels[lo - key], boosts[orig])
            if r is None:                                     # too short for a loop: as it is
                shaped[orig] = None
                continue
            a, e, y0, y1 = r
            if voice != src:                                  # left at S', right at X' = S' + k * 1024
                while len(body) % 0x800:
                    body += PAD
                Sn = FLASH_BASE_W + (len(body) + 4) // 2
                pad = (S - Sn) % LOOP_HALF                     # S' = S (mod 1024): the same alignment of L, E
                body += PAD * pad + b"\0\0\0\0"
                Sn += pad
                off = -(-(e + 1 + 64) // LOOP_HALF) * LOOP_HALF
                body += struct.pack("<%dh" % (e + 1), *y0)
                body += PAD * (Sn + off - (FLASH_BASE_W + (len(body) + 4) // 2)) + b"\0\0\0\0"
                body += struct.pack("<%dh" % (e + 1), *y1)
                S, X = Sn, Sn + off
            else:
                body[w(S):w(S) + 2 * (e + 1)] = struct.pack("<%dh" % (e + 1), *y0)
                body[w(X):w(X) + 2 * (e + 1)] = struct.pack("<%dh" % (e + 1), *y1)
            shaped[orig] = (S, S + a, S + e, X)
    if voice != src:
        while len(body) % 0x800:
            body += PAD
        end_w = FLASH_BASE_W + len(body) // 2
        if end_w > sb.get("end", end_w):
            raise BankError("the soundbank would end %.1f MB past its partition" % ((end_w - sb["end"]) * 2 / 2 ** 20))
        struct.pack_into("<I", body, 8, end_w)
        struct.pack_into("<I", body, 0x9C, end_w)
        b = body + trailer
        inst = _clone(b, gi, blk_len)
        a = _dir_entry(b, *voice_to_bank_prog(banks, voice))   # the sound now plays the copy
        b[a + 1] = inst // 2 >> 16
        struct.pack_into("<H", b, a + 2, inst // 2 & 0xFFFF)
    else:
        inst = gi
    for z in zones(b, inst):
        o = find_sample_block(b, z)
        new = shaped.get(sample_block(b, o)[2:])
        if new:
            blk = bytearray(b[o:o + 22])
            set_addrs(blk, *new[:3])
            blk[12], blk[13] = new[3] & 0xFF, new[3] >> 24
            struct.pack_into("<H", blk, 14, (new[3] >> 8) & 0xFFFF)
            b[o:o + 22] = blk
    _slow(b, inst, sb.get("sustain", (0, 0))[1], factor)
    _stretch(b, inst, sb.get("grander_fall", {}))
    return bytes(b)


def _stretch(b, inst, table):
    """table {(layer, zone): factor}: those zones' volume envelopes fall that many times slower"""
    for (li, zi), f in sorted(table.items()):
        o = find_sample_block(b, layers(b, inst)[li][zi])
        at = envelope.amp_env_at(b, o)
        b[at + 4] = envelope.rate(envelope.seconds(b[at + 4]) * f, False)


def grander_fall_table(bank, dsp_image, fwmap, low=48, step=0.1, most=5.0):
    """what target.map's granderfall holds (for a new target, or after changing grander()): the zones of the
    grander piano's layers between key LOW (its zone as it is) and the grander key whose sound fades faster than a
    straight line between LOW's and the grander key's, and how many times slower their envelopes must fall for
    it (in STEP, at most MOST; never faster). Times from a model: the sample's level until the loop, then the
    loop's, minus the envelope's fall (60 dB in its time); a sound ends 50 dB below its hit. Needs the bank."""
    src, key, _ = fwmap.soundbank["grander"]
    sb = dict(fwmap.soundbank)
    sb.pop("grander_fall", None)
    b = grander(bank, dsp_image, dataclasses.replace(fwmap, soundbank=sb), src)
    inst = instrument_addr(b, *voice_to_bank_prog(voice_banks(container.words(dsp_image), fwmap), src))
    w = lambda a: (a - FLASH_BASE_W) * 2
    H = 2205

    def model(o):
        _, _, S, L, E = sample_block(b, o)
        X, n = _stereo_x(b, o), E - S + 1
        ch = [struct.unpack_from("<%dh" % n, b, w(q)) for q in (S, X)]
        en = lambda i, j: sum(v * v for c in ch for v in c[i:j]) / (2 * (j - i)) + 1e-3
        lv = [en(i, i + H) for i in range(0, n - H, H)]
        peak = max(lv)
        db = [10 * math.log10(v / peak) for v in lv]
        loop = 10 * math.log10(en(L - S, n) / peak)
        return db, loop, (L - S) // H

    def t50(db, loop, la, T):
        for i in range(4000):
            if (db[i] if i < la else loop) - 60 * i * H / SR / T < -50:
                return i * H / SR
        return 4000 * H / SR

    out = {}
    for li, (layer, keys) in enumerate(zip(layers(b, inst), _zone_keys(b, inst))):
        if len(layer) < 2:
            continue
        info = []
        for zi, (z, (lo, hi)) in enumerate(zip(layer, keys)):
            o = find_sample_block(b, z)
            T = envelope.seconds(b[envelope.amp_env_at(b, o) + 4])
            info.append((zi, lo, hi, o, T))
        at = lambda k: next(x for x in info if x[1] <= k <= x[2])
        ends = [t50(*model(at(k)[3]), at(k)[4]) for k in (low, key)]
        for zi, lo, hi, o, T in info:
            if lo <= low or lo >= key:
                continue
            want = ends[0] + (ends[1] - ends[0]) * ((lo + hi) / 2 - low) / (key - low)
            mdl, f = model(o), 1.0
            while t50(*mdl, T * f) < want and f < most:
                f = round(f + step, 6)
            if f > 1:
                out[(li, zi)] = f
    return out
