"""NEK-100 DSP firmware container ("rd").

Reverse engineered layout, 16-bit little-endian words:
  w[0]     0x6472 'rd' magic (the NUX updater checks this and the size only)
  w[1..2]  total length in words (u32, lo/hi)
  w[-1]    checksum word: sum(all words) == 0 (mod 2**16)
"""
import hashlib
import struct

MAGIC = 0x6472


def words(data):
    if len(data) % 2:
        raise ValueError("odd length")
    return list(struct.unpack("<%dH" % (len(data) // 2), data))


def pack(w):
    return struct.pack("<%dH" % len(w), *w)


def fix_checksum(w):
    w = list(w)
    w[-1] = (-sum(w[:-1])) & 0xFFFF
    return w


def validate(data):
    """Return a list of problems; an empty list means the container is consistent."""
    probs = []
    w = words(data)
    if w[0] != MAGIC:
        probs.append("bad magic %04x" % w[0])
    n = w[1] | (w[2] << 16)
    if n != len(w):
        probs.append("length field %#x != file words %#x" % (n, len(w)))
    if sum(w) & 0xFFFF:
        probs.append("checksum sum=%#06x (expected 0)" % (sum(w) & 0xFFFF))
    return probs


def sha256(data):
    return hashlib.sha256(data).hexdigest()
