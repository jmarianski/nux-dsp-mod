"""The flashing sequence against a simulated Dream RPC bootloader (no device needed)."""
import struct
import unittest

from nuxdsp import container, dfu

TABLE = [("NF Firmware", 0x40000, 0x80000, 2), ("NF SBank2K", 0x80000, 0x7000000, 0x11),
         ("NF DEMO", 0x7000000, 0x7100000, 6), ("NF Style", 0x7100000, 0x7200000, 4)]
FRAG = 1024


class Boot:
    """Answers as the instrument did (2026-10-16) and records what it gets."""

    def __init__(self, done_value=1):
        self.out, self.pending, self.log, self.flash = [], None, [], {}
        self.addr, self.done_value = None, done_value

    def reply(self, status, words=()):
        return struct.pack("<IHHH", 0x74535542, 1, status, len(words)) + struct.pack("<%dH" % len(words), *words)

    def write(self, data):
        if self.pending is None:
            magic, bb, nb, cmd, nargs, z = struct.unpack_from("<IHHHHI", data)
            assert magic == 0x75625542 and z == 0 and len(data) == 16 + 2 * nargs
            self.pending = [cmd, data[16:], bb, nb, []]
        else:
            assert len(data) == self.pending[2]
            self.pending[4].append(data)
        if len(self.pending[4]) == self.pending[3]:
            self.answer(*self.pending)
            self.pending = None

    def answer(self, cmd, args, bb, nb, blocks):
        self.log.append((cmd, args, nb))
        if cmd == 0x1000:
            body = struct.pack("<4H", FRAG, len(TABLE), 1, 0)
            for name, s, e, k in TABLE:
                body += struct.pack("<HHHHHH", s >> 16, e >> 16, k, 0, 0, 0) + name.encode().ljust(12, b"\0")
            self.out.append(self.reply(1, struct.unpack("<%dH" % (len(body) // 2), body)))
        elif cmd == 0x1001:
            self.addr = struct.unpack("<I", args)[0]
            self.out.append(self.reply(1))
        elif cmd == 0x1003:
            for b in blocks:
                for i in range(0, len(b), 2):
                    self.flash[self.addr] = b[i] | b[i + 1] << 8
                    self.addr += 1
            self.out.append(self.reply(1))
        elif cmd == 0x1007:
            st = struct.unpack_from("<H", args)[0]
            w = [0, 0, self.done_value, 0] + [0] * 32 if st == 6 else []
            self.out.append(self.reply(1 if w else 0, w))
        elif cmd in (0x1002, 0x1004, 0xf01):
            self.out.append(self.reply(1))
        else:
            self.out.append(struct.pack("<IHHH", 0x74535542, 0, 0xfffe, 0))

    def read(self):
        return self.out.pop(0)


def firmware(words):
    w = [0x6472, words & 0xFFFF, words >> 16] + [(i * 7919) & 0xFFFF for i in range(3, words - 1)] + [0]
    w[-1] = -sum(w) & 0xFFFF
    return struct.pack("<%dH" % words, *w)


class TestFlash(unittest.TestCase):
    def test_firmware_sequence_and_content(self):
        data = firmware(107137)
        self.assertEqual(container.validate(data), [])
        b = Boot()
        name, ok = dfu.flash(b, data, "/x/NEK100_DSP_V1.0.7B.bin")
        self.assertEqual((name, ok), ("NF Firmware", 1))
        cmds = [c for c, _, _ in b.log]
        self.assertEqual(cmds[:5], [0x1000, 0x1007, 0x1007, 0x1007, 0x1001])
        self.assertEqual(cmds[-6:], [0x1002, 0x1004] + [0x1007] * 4)
        states = [struct.unpack_from("<H", a)[0] for c, a, _ in b.log if c == 0x1007]
        self.assertEqual(states, [2, 3, 8, 4, 5, 6, 7])
        st8 = [a for c, a, _ in b.log if c == 0x1007][2]
        self.assertEqual(len(st8), 74)
        self.assertEqual(struct.unpack_from("<I", st8, 6)[0], (len(data) >> 16) | (len(data) & 0xFFFF) << 16)
        self.assertEqual(st8[10:].rstrip(b"\0"), b"NEK100_DSP_V1.0.7B.bin")
        self.assertEqual(struct.unpack("<I", [a for c, a, _ in b.log if c == 0x1001][0])[0], 0x40000)
        self.assertEqual([n for c, _, n in b.log if c == 0x1003][0], 8)    # 16 KB transfers for a 214 KB file
        words = struct.unpack("<%dH" % (len(data) // 2), data)
        self.assertEqual([b.flash[0x40000 + i] for i in range(len(words))], list(words))
        pad = range(0x40000 + len(words), 0x40000 + -(-len(words) // FRAG) * FRAG)
        self.assertTrue(pad and all(b.flash[a] == 0xFFFF for a in pad))
        self.assertNotIn(0x40000 + -(-len(words) // FRAG) * FRAG, b.flash)

    def test_no_restart_without_confirmation(self):
        b = Boot(done_value=0)
        self.assertEqual(dfu.flash(b, firmware(5000), "f.bin"), ("NF Firmware", 0))
        states = [struct.unpack_from("<H", a)[0] for c, a, _ in b.log if c == 0x1007]
        self.assertEqual(states, [2, 3, 8, 4, 5, 6])

    def test_refuses_before_writing(self):
        for data, msg in [(firmware(5000)[:-2] + b"\0\1", "checksum"), (firmware(0x40001), "too large"),
                          (b"XXXX" * 8, "unknown file type")]:
            b = Boot()
            with self.assertRaisesRegex(dfu.DfuError, msg):
                dfu.flash(b, data, "f.bin")
            self.assertEqual([c for c, _, _ in b.log], [0x1000])

    def test_kinds(self):
        self.assertEqual(dfu.kind(b"Bank\0\0"), "NF SBank2K")
        self.assertEqual(dfu.kind(b"StyCe\0"), "NF Style")
        self.assertEqual(dfu.chunk_frags(107136, FRAG), 8)
        self.assertEqual(dfu.chunk_frags(108_000_000, FRAG), 64)


if __name__ == "__main__":
    unittest.main()
