"""Extra's item count: 7 (0..6), or 8 with a patch that defines dm_start (doom-piano). Simulated."""
import unittest

from nuxdsp import asm, fwmap, patcher, sim

STUB = 0x9000


class Code(dict):
    def __missing__(self, k):
        return 0xD1CA if k == STUB else 0xFFFF


def block(dm_start):
    m = fwmap.load()
    p = patcher.load("extra_menu", m)
    key, lines, _ = [b for b in patcher.code_blocks(p) if any(l.startswith("ex_succ:") for l in b[1])][0]
    y = dict(m.symbols(), **{q.name: q.default for q in p.params})
    y.update(dm_start=dm_start, ex_ret=STUB, dm_panel=STUB, tl_key=STUB, ex_norm=STUB)
    words, labels = asm.assemble(lines, y, origin=0x1a280, label_prefix=p.name)
    return Code(words), labels


class TestExtraItems(unittest.TestCase):
    def run_(self, dm_start, label, r6):
        code, labels = block(dm_start)
        s = sim.Sim(code, {})
        s.r[6], s.r[7] = r6, 0x1234
        s.call(labels[label])
        self.assertEqual(s.r[7], 0x1234)              # ex_norm's word stays for the caller
        return s.r[6]

    def test_without_doom(self):
        self.assertEqual([self.run_(STUB, "ex_succ", i) for i in range(7)], [1, 2, 3, 4, 5, 6, 0])
        self.assertEqual([self.run_(STUB, "ex_up", i) for i in range(7)], [1, 2, 3, 4, 5, 6, 6])

    def test_with_doom(self):
        self.assertEqual([self.run_(0x1a900, "ex_succ", i) for i in range(8)], [1, 2, 3, 4, 5, 6, 7, 0])
        self.assertEqual([self.run_(0x1a900, "ex_up", i) for i in range(8)], [1, 2, 3, 4, 5, 6, 7, 7])
