"""Flash over USB in the instrument's update mode, without the Windows updater (Dream RPC, as DREAM-Programmer).

Update mode: hold Power + VOL+ + VOL- for about half a second; the instrument shows up as 1fc9:5250 "RPC DFU"
(vendor interface 0, bulk endpoints 0x04 out / 0x84 in). Linux access without root: udev/70-nux-dfu.rules.

A request is one bulk write of a 16-byte header ('BUbu', block bytes, block count, command, argument words, 0)
and the arguments, then one write per data block; the reply ('BUSt' ..., status at 6, word count at 8, words)
comes back on 0x84. The sequence follows DREAM-Programmer 1.5.2 (macOS build, read from its code):
states 2, 3 (range start), 8 (file size, file name); programBegin(start); blocks of whole fragments, the last
one padded with 0xff; programEnd; programmingDone; states 4 (range start), 5, 6 (a non-zero answer = done,
restart offered); 7 = restart. An unknown command answers status 0xfffe.
"""
import os
import struct

from . import container

VID, PID = 0x1FC9, 0x5250
EP_OUT, EP_IN = 0x04, 0x84
MAGIC_OUT, MAGIC_IN = 0x75625542, 0x7453     # 'BUbu', 'St'
INFO, RANGES = 0xF01, 0x1000
BEGIN, END, BLOCK, DONE, STATE = 0x1001, 0x1002, 0x1003, 0x1004, 0x1007
CHUNK = 0x20000                                # bytes per transfer before shrinking for small files
TEXT = 64

# file magic (first bytes) -> range name (as the bootloader lists it)
KINDS = [(b"rd", "NF Firmware"), (b"Bank", "NF SBank2K"), (b"StyC", "NF Style")]


class DfuError(RuntimeError):
    pass


class Usb:
    """pyusb transport (pip install pyusb; libusb)."""

    def __init__(self, timeout=5000):
        try:
            import usb.core
            import usb.util
        except ImportError:
            raise DfuError("needs pyusb: pip install pyusb")
        self.usb, self.timeout = usb, timeout
        self.dev = usb.core.find(idVendor=VID, idProduct=PID)
        if self.dev is None:
            raise DfuError("no instrument in update mode (1fc9:5250): hold Power + VOL+ + VOL- for ~0.5 s")
        try:
            usb.util.claim_interface(self.dev, 0)
        except usb.core.USBError as e:
            raise DfuError("cannot open the device (%s); see udev/70-nux-dfu.rules" % e)

    def write(self, data):
        if self.dev.write(EP_OUT, data, self.timeout) != len(data):
            raise DfuError("short write")

    def read(self):
        return bytes(self.dev.read(EP_IN, 0x200, self.timeout))

    def close(self):
        self.usb.util.release_interface(self.dev, 0)
        self.usb.util.dispose_resources(self.dev)


def transact(t, cmd, args=b"", blocks=(), block_bytes=0):
    """-> (status, words). Blocks are sent one write each, all block_bytes long."""
    if len(args) % 2 or len(args) > 128:
        raise ValueError("arguments: even, at most 128 bytes")
    t.write(struct.pack("<IHHHHI", MAGIC_OUT, block_bytes, len(blocks), cmd, len(args) // 2, 0) + args)
    for b in blocks:
        t.write(b)
    r = t.read()
    if len(r) < 10 or struct.unpack_from("<H", r, 2)[0] != MAGIC_IN:
        raise DfuError("bad reply to %#x: %s" % (cmd, r[:16].hex()))
    status, n = struct.unpack_from("<HH", r, 6)
    while len(r) < 10 + 2 * n:
        r += t.read()
    return status, list(struct.unpack_from("<%dH" % n, r, 10))


def info(t):
    st, w = transact(t, INFO)
    return w


def ranges(t):
    """-> (fragment words, [(name, start, end)]) with addresses in words."""
    st, w = transact(t, RANGES, struct.pack("<H", 1))
    if st != 1 or len(w) < 3:
        raise DfuError("range table: status %d" % st)
    frag, count, fmt = w[:3]
    raw = struct.pack("<%dH" % len(w), *w)
    size = 24 if fmt == 1 else 16
    out = []
    for i in range(count):
        e = raw[8 + i * size: 8 + (i + 1) * size]
        if fmt == 1:
            name = e[12:24]
            start, end = e[0] | e[1] << 8, e[2] | e[3] << 8
            out.append((name.split(b"\0")[0].decode("latin1"), start << 16, end << 16))
        else:
            out.append((e[4:16].split(b"\0")[0].decode("latin1"), None, None))
    return frag, out


def state(t, n, value=0, text=""):
    """programState: u16 state, u32 0x0032ffff (as DREAM-Programmer), u32 value (halves swapped), 64 B text.
    -> the value of the reply (status 1 with 36 words), else None."""
    v = (value >> 16 | value << 16) & 0xFFFFFFFF
    args = struct.pack("<HII", n, 0x0032FFFF, v) + text.encode("ascii", "replace")[:TEXT - 1].ljust(TEXT, b"\0")
    st, w = transact(t, STATE, args)
    if st == 1 and len(w) == 0x24 and w[0] != 0xFFFF:
        return w[2] | w[3] << 16
    return None


def kind(data):
    for magic, name in KINDS:
        if data.startswith(magic):
            return name
    return None


def plan(data, table, frag, name=None):
    """-> (range name, start, words). Checks what can be checked before anything is sent."""
    if len(data) % 2:
        raise DfuError("odd file size")
    name = name or kind(data)
    if name is None:
        raise DfuError("unknown file type (magic %s); give --range" % data[:4].hex())
    hit = [r for r in table if r[0] == name]
    if not hit:
        raise DfuError("the instrument has no range %r (it has: %s)" % (name, ", ".join(r[0] for r in table)))
    _, start, end = hit[0]
    words = len(data) // 2
    if words > end - start:
        raise DfuError("file too large for %s: %d words, room for %d" % (name, words, end - start))
    if name == "NF Firmware":
        probs = container.validate(data)
        if probs:
            raise DfuError("not a valid DSP firmware file: " + "; ".join(probs))
    return name, start, words


def chunk_frags(file_words, frag):
    """Fragments per transfer: DREAM-Programmer starts at 128 KB and halves it for small files."""
    frag_bytes = 2 * frag
    n = CHUNK // frag_bytes
    while n >= 5 and file_words < 5 * n * frag_bytes:
        n >>= 1
    return max(n, 1)


def flash(t, data, filename, name=None, restart=True, progress=None):
    """Program one file. -> the range name. Raises DfuError before the first write if the file does not fit."""
    frag, table = ranges(t)
    name, start, words = plan(data, table, frag, name)
    frag_bytes = 2 * frag
    per = chunk_frags(words, frag) * frag
    state(t, 2)
    state(t, 3, start)
    state(t, 8, len(data), os.path.basename(filename))
    transact(t, BEGIN, struct.pack("<I", start))
    done = 0
    while done < words:
        n = min(per, words - done)
        buf = data[2 * done: 2 * (done + n)]
        nf = -(-len(buf) // frag_bytes)
        buf = buf.ljust(nf * frag_bytes, b"\xff")
        transact(t, BLOCK, blocks=[buf[i * frag_bytes:(i + 1) * frag_bytes] for i in range(nf)],
                 block_bytes=frag_bytes)
        done += n
        if progress:
            progress(done, words)
    transact(t, END)
    transact(t, DONE)
    state(t, 4, start)
    state(t, 5)
    ok = state(t, 6)
    if ok and restart:
        state(t, 7)
    return name, ok
