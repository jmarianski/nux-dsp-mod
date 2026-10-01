"""Port the NEK-100 target onto synthetic 'other builds' of its firmware (needs NEK100_FW)."""
import os
import tempfile
import unittest

from nuxdsp import container, disasm, fwmap, patcher, port

FW = os.environ.get("NEK100_FW")


def shifted(img, m, at, n, var_from=None, var_to=None):
    """Insert n words at `at` (code moves, literals stay), optionally renumber one RAM variable."""
    w = container.words(img)
    if var_from is not None:
        for a, x, lit in disasm.iter_insns(w, m.code):
            if lit == var_from:
                w[a + 1] = var_to
    w = w[:at] + [0x0000] * n + w[at:]
    w[1], w[2] = len(w) & 0xFFFF, len(w) >> 16
    return container.pack(container.fix_checksum(w))


@unittest.skipUnless(FW and os.path.exists(FW), "set NEK100_FW to the official firmware file")
class TestPort(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FW, "rb") as f:
            cls.img = f.read()
        cls.m = fwmap.load()

    def run_port(self, new):
        d = tempfile.mkdtemp()
        port.port(self.img, new, self.m, d)
        return fwmap.load(os.path.join(d, "target.map")), d

    def test_shifted_build(self):
        m2, d = self.run_port(shifted(self.img, self.m, 0x300, 0x40, 0x0144, 0x0150))
        old = {e.name: e.addr for e in self.m.by_kind("func", "label")}
        new = {e.name: e.addr for e in m2.by_kind("func", "label")}
        self.assertGreater(len(new), 0.9 * len(old))
        for k, v in new.items():
            self.assertEqual(v, old[k] + 0x40, k)
        self.assertEqual(m2.symbols()["touch"], 0x0150)
        self.assertEqual([s + 0x40 for s, _ in self.m.pools], [s for s, _ in m2.pools])
        p = patcher.load("touch_off", m2)
        self.assertEqual(p.hooks[1].addr, 0x03f85 + 0x40)
        self.assertEqual(p.hooks[1].expect, [0xff80, 0x0150])


if __name__ == "__main__":
    unittest.main()
