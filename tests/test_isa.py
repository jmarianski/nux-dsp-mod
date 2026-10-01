"""Tests that need no firmware file: ISA encode/decode, assembler, patch parser, map."""
import unittest

from nek100mod import asm, disasm, fwmap, isa, patcher


class TestISA(unittest.TestCase):
    def test_every_one_word_encoding_round_trips(self):
        for x in range(0x10000):
            if isa.is_two_words(x):
                continue
            d = isa.decode(x, None)
            if d:
                self.assertEqual(isa.encode(*d), [x], hex(x))

    def test_two_word_encodings_round_trip(self):
        for x in range(0x10000):
            if not isa.is_two_words(x):
                continue
            for lit in (0, 1, 0x7FFF, 0x8000, 0xFFFF):
                d = isa.decode(x, lit)
                if d:
                    self.assertEqual(isa.encode(*d), [x, lit], hex(x))

    def test_text_round_trip(self):
        """format_insn -> assembler gives the same words (for every decodable one-word form)."""
        for x in range(0x10000):
            if isa.is_two_words(x) or not isa.decode(x, None):
                continue
            text, _ = disasm.format_insn(0x1000, x, None, lambda t: "%#x" % t, lambda a: None)
            words, _ = asm.assemble([text], origin=0x1000)
            self.assertEqual(list(words.values()), [x], "%04x %s" % (x, text))


class TestAsm(unittest.TestCase):
    def test_labels_locals_and_expressions(self):
        src = [".org 0x100", "start:", "  mov r7, #N+1", ".loop:", "  cmp r7, #0", "  bne .loop",
               "  call start", "  ld r6, [var+2]", "  .dw N<<8 | 3", "  ret"]
        words, labels = asm.assemble(src, {"N": 4, "var": 0x15e}, label_prefix="p")
        self.assertEqual(labels, {"start": 0x100, "p.loop": 0x101})
        self.assertEqual(words[0x100], 0x0705)
        self.assertEqual(words[0x102], 0xE3FE)  # bne back to 0x101
        self.assertEqual((words[0x103], words[0x104]), (0xD6C8, 0x100))
        self.assertEqual((words[0x105], words[0x106]), (0xFE80, 0x160))  # ld r6, [abs]: 0xF880 | r << 8
        self.assertEqual(words[0x107], 0x0403)

    def test_errors(self):
        for bad in (["mov r7, #300"], ["ld r1, [r1+16]"], ["frob r1"], ["call nowhere"]):
            with self.assertRaises(asm.AsmError):
                asm.assemble(bad, origin=0)

    def test_branch_range(self):
        with self.assertRaises(asm.AsmError):
            asm.assemble(["beq 0x200"], origin=0)


class TestBundled(unittest.TestCase):
    def test_map_loads(self):
        m = fwmap.load()
        self.assertEqual(len(m.sha256), 64)
        self.assertEqual(m.var_name(0x160), "sustain_cc64+2")

    def test_patches_parse_and_fit(self):
        m = fwmap.load()
        layout = patcher.canonical_layout(m)
        for n in patcher.available():
            p = patcher.load(n)
            self.assertTrue(p.title, n)
            for h in p.hooks:
                self.assertTrue(h.expect, n)

    def test_parse_errors(self):
        with self.assertRaises(patcher.PatchError):
            patcher.parse(".hook 0x10 expect 0x1\n")
        with self.assertRaises(patcher.PatchError):
            patcher.parse(".patch x\n.code\n ret\n")
        with self.assertRaises(patcher.PatchError):
            patcher.parse('.patch x\n.string "AB" "ABC"\n')


if __name__ == "__main__":
    unittest.main()
