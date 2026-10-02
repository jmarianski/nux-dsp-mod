"""Simulate the boot_preset label code (no firmware needed)."""
import unittest

from nuxdsp import asm, fwmap, patcher, sim


class Code(dict):
    def __missing__(self, k):
        return 0xFFFF


def label(n, boot=1, enabled=1):
    """Run preset_label's tail for preset n: buffer holds "N.UserN", r1 = terminator index."""
    m = fwmap.load()
    p = patcher.load("boot_preset", m)
    syms = dict(m.symbols(), BOOT_PRESET=boot, DEFAULT_LABEL=enabled)
    words, labels = asm.assemble(p.code, syms, origin=0x9000, label_prefix=p.name)
    buf = syms["text_buf"]
    text = "%d.User%d" % (n + 1, n + 1)
    ram = {buf + i: ord(c) for i, c in enumerate(text)}
    fp = 0x7000
    ram[fp + 3] = n
    s = sim.Sim(Code(words), ram, fp=fp)
    s.r[1] = len(text)
    s.call(labels["default_label"])
    s.wr(s.r[1], 0)  # what the firmware does right after the hook
    out = ""
    a = buf
    while s.rd(a):
        out += chr(s.rd(a))
        a += 1
    return out


class TestDefaultLabel(unittest.TestCase):
    def test_boot_preset_is_default(self):
        self.assertEqual(label(0), "1.Default")
        self.assertEqual(label(2, boot=3), "3.Default")

    def test_others_numbered_user1_to_user4(self):
        self.assertEqual([label(n) for n in range(1, 5)], ["2.User1", "3.User2", "4.User3", "5.User4"])
        self.assertEqual([label(n, boot=3) for n in (0, 1, 3, 4)], ["1.User1", "2.User2", "4.User3", "5.User4"])
        self.assertEqual([label(n, boot=5) for n in range(4)], ["1.User1", "2.User2", "3.User3", "4.User4"])

    def test_disabled(self):
        self.assertEqual([label(n, enabled=0) for n in range(5)], ["%d.User%d" % (n + 1, n + 1) for n in range(5)])


if __name__ == "__main__":
    unittest.main()
