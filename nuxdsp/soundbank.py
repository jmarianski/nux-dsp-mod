"""Add instruments (sf2.Instrument) to the official soundbank, in place of chosen sounds.

The soundbank (NEK100_SBANK_*.bin) is flashed from word 0x80000 on, so its pointers are flash word addresses
(byte offset / 2 + 0x80000). What we use of it (C: an instrument built this way plays on the NEK-100):
  - a directory at byte 0x252: per program (0..127) a pointer to a list of 4-byte entries
    (bank, page, address of the instrument), ended by ff ff ff ff;
  - an instrument: 4 header bytes (byte 2 = 0x80 | number of zones), then per zone 6 bytes
    (first-zone flag, low key, 0x7f, high key, zone address in the page), 0 0, then the zone records;
  - a zone record holds in-page pointers to its parts and a sample block with the sample's start, loop and
    end addresses (the loop runs L..E, sample E = sample L; one-shots loop over silence at the end; E is the
    last word of a 256-word block, as in ~95% of the vendor's samples); the word
    before it is the tuning (V, 1/256 semitone, always even). A zone plays the keys above the previous zone's high key.
  - header fields: u32 at 8 and 0x9c = end of the data, at 0xa6 = end of the parameter data. New samples go at
    the end (before the "PackNameDate:" trailer), new instruments into the free rest of the parameter page.
A sound number maps to (bank, program) through the DSP's voice_banks table. The zone settings (envelope, filter,
...) come from a template zone of the target (soundbank line of target.map): one for one-shots, one for instruments
with loops (a sustaining one); nothing of the vendor's is in an instrument file, and an SF2's envelope is not used.

custom_voices (a DSP patch) shows the new names: fill_names() writes them into its table.
"""
import math
import struct

from . import asm, container, patcher

FLASH_BASE_W = 0x80000
PAD = b"\xef\xad"                 # the bank compiler's filler word 0xadef
DIRECTORY = 0x252
K = -83.996                       # 12*log2(cycles per sample) + V/256 for zones that follow the keyboard
SR = 44100
CV_ENTRY, CV_NAME = 33, 16
BLOCK = 256                       # samples end on the last word of a block of this size, as the vendor's


class BankError(Exception):
    pass


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


def zones(d, inst):
    """byte offsets of the zone records of an instrument."""
    page = (inst // 2) & ~0xFFFF
    o, out = inst + 4, []
    while True:
        out.append((page | struct.unpack_from("<H", d, o + 4)[0]) * 2)
        if d[o + 3] == 0xFF:
            return out
        o += 6


def find_sample_block(d, zone):
    """the 'fl 0/1 A A 01 f 00 00 Z 00 C C X X Y 00 E E 0e 7f' block inside a zone record."""
    for o in range(zone, zone + 0x60):
        b = d[o:o + 20]
        if b[1] in (0, 1) and b[4] == 1 and b[6:8] == b"\0\0" and b[9] == 0 and b[15] == 0 and b[18:20] == b"\x0e\x7f":
            return o
    raise BankError("no sample block in zone at %#x" % zone)


def set_addrs(rec, S, L, E):
    hi = S >> 24
    if L >> 24 != hi or E >> 24 != hi:
        raise BankError("sample crosses a 16M-word boundary")
    rec[0] = (rec[0] & 0x3F) | ((hi & 3) << 6)
    rec[1] = hi >> 2
    struct.pack_into("<H", rec, 2, (L >> 8) & 0xFFFF)
    rec[5] = L & 0xFF
    rec[8] = S & 0xFF
    struct.pack_into("<H", rec, 10, (S >> 8) & 0xFFFF)
    rec[14] = E & 0xFF
    struct.pack_into("<H", rec, 16, (E >> 8) & 0xFFFF)


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
    for kind in ("template", "template_loop"):               # one-shots, and instruments with loops
        tvoice, tzone = sb.get(kind, sb["template"])
        tinst = instrument_addr(d, *voice_to_bank_prog(banks, tvoice))
        tz = zones(d, tinst)[tzone]
        templates[kind] = (tz, d[tinst:tinst + 4]) + zone_record(d, tz)

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
            end = z.loop[1] if z.loop else len(z.pcm) // 2 + 63   # E - S
            S = FLASH_BASE_W + (len(body) + 4) // 2           # two zero guard words, then the audio
            body += PAD * ((BLOCK - 1 - (S + end)) % BLOCK)   # E on the last word of a block, as the vendor's
            S = FLASH_BASE_W + (len(body) + 4) // 2
            if z.loop:
                body += b"\0\0\0\0" + z.pcm
                a = (S, S + z.loop[0], S + z.loop[1])
            else:
                body += b"\0\0\0\0" + z.pcm + b"\0" * 128   # 64 zero words: the silent loop of a one-shot
                E = FLASH_BASE_W + (len(body) - 2) // 2
                a = (S, E - 43, E)
            assert a[2] % BLOCK == BLOCK - 1
            addrs.append(a)
            if z.key is not None:
                seen[z.key] = a
        placed.append(addrs)
    while len(body) % 0x800:
        body += PAD
    end_w = FLASH_BASE_W + len(body) // 2
    struct.pack_into("<I", body, 8, end_w)
    struct.pack_into("<I", body, 0x9C, end_w)

    for (inst, voice), addrs in zip(items, placed):           # instruments: in the free rest of the parameter page
        base = (struct.unpack_from("<I", body, 0xA6)[0] - FLASH_BASE_W) * 2 + 0x10
        page = base // 2 >> 16
        n = len(inst.zones)
        if not 1 <= n <= 127:
            raise BankError("%s: %d zones (1..127)" % (inst.name, n))
        tz, hdr, rec, ptr_offs, page_b, sb_off = templates[
            "template_loop" if any(z.loop for z in inst.zones) else "template"]
        head = bytearray(hdr)
        head[2] = 0x80 | n
        zone_at = base + 4 + 6 * n + 2
        blob, hi = bytearray(), 0
        for i, z in enumerate(inst.zones):
            zstart = zone_at + len(blob)
            lo = hi                                           # a zone plays the keys above the previous one's
            hi = 0xFF if i == n - 1 else z.hi
            head += bytes([0x80 if i == 0 else 0x00, lo, 0x7F, hi]) + struct.pack("<H", (zstart + 2) // 2 & 0xFFFF)
            r = bytearray(rec)
            for o in ptr_offs:                                # rebase the in-page pointers
                new = struct.unpack_from("<H", rec, o)[0] * 2 + page_b - (tz - 2) + zstart
                if new // 2 >> 16 != page:
                    raise BankError("instrument crosses a page")
                struct.pack_into("<H", r, o, new // 2 & 0xFFFF)
            blk = bytearray(r[sb_off:sb_off + 18])
            set_addrs(blk, *addrs[i])
            r[sb_off:sb_off + 18] = blk
            struct.pack_into("<h", r, sb_off - 2, tune_value(z.root, z.cents, z.rate))
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
