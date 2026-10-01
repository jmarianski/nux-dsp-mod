"""Simulate the polish_font patch code (no firmware needed): character mapping and glyph drawing."""
import unittest

from nuxdsp import asm, fwmap, patcher, sim

FB = 0x662a


class Code(dict):
    def __missing__(self, k):
        return 0xFFFF


def build_code():
    m = fwmap.load()
    p = patcher.load("polish_font")
    origin = patcher.canonical_layout(m)["polish_font"]
    words, labels = asm.assemble(p.code, m.symbols(), origin=origin, label_prefix=p.name)
    return Code(words), labels, p


def glyph_art(p):
    """{char: (base, rows)} from the patch source itself."""
    out, rows = {}, None
    text = open(p.path, encoding="utf-8").read()
    table = {}
    for line in text.splitlines():
        if line.strip().startswith(".dw") and ";" in line and "," in line:
            parts = line.split(";")[0].split(None, 1)[1].split(",")
            if len(parts) == 3:
                table[parts[2].strip()] = (int(parts[0], 0), int(parts[1], 0))
    lab = None
    for line in text.splitlines():
        s = line.split(";")[0].strip()
        if s.endswith(":") and s[:-1] in table:
            lab = s[:-1]
        elif s == ".art":
            rows = []
        elif s == ".endart":
            cp, base = table[lab]
            out[chr(cp)] = (chr(base), rows)
            rows = None
        elif rows is not None and s:
            rows.append(s)
    return out


class TestPolishFont(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code, cls.labels, cls.patch = build_code()
        cls.art = glyph_art(cls.patch)
        cls.m = fwmap.load()

    def test_all_letters_present(self):
        self.assertEqual(sorted(self.art), sorted("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"))

    def test_uni_map(self):
        base = self.m.symbols()["font_medium_chars"]
        cases = {c: c for c in "Az 9"}
        cases.update({c: b for c, (b, _) in self.art.items()})
        cases["€"] = "?"
        for c, b in cases.items():
            s = sim.Sim(self.code)
            s.r[1] = ord(c)
            s.call(self.labels["uni_map"])
            self.assertEqual(s.r[1], base + ord(b), c)

    def redraw(self, ch, x, y, inv, font=0, fill=0):
        fp = 0x7000
        ram = {0x5000: ord(ch), fp + 0: 0, fp + 1: 0, fp + 2: 0x4f, fp + 5: x & 0xFFFF, fp + 6: y, fp + 7: inv,
               fp + 8: 0x5000, fp + 9: font, fp + 10: 1}
        ram.update({FB + i: fill for i in range(1024)})
        s = sim.Sim(self.code, ram, fp)
        s.call(self.labels["pl_redraw"])
        self.assertEqual((s.r[7], s.r[1]), (1, 0x3a26))  # what the replaced code needs
        return s

    def pixel(self, s, x, y):
        return (s.rd(FB + (y >> 3) * 128 + x) >> (y & 7)) & 1

    def test_draws_every_glyph_normal_and_inverted(self):
        for ch, (_, rows) in self.art.items():
            for inv in (0, 1):
                s = self.redraw(ch, 50, 20, inv, fill=0xFF if inv else 0)
                for yy, row in enumerate(rows):
                    for xx, c in enumerate(row):
                        self.assertEqual(self.pixel(s, 50 + xx, 20 + yy), (c == "#") ^ inv, (ch, inv, xx, yy))
                self.assertEqual((s.rd(0x7000), s.rd(0x7002)), (0, 0))

    def test_touches_only_its_cell(self):
        s = self.redraw("Ż", 50, 20, 0)
        for i in range(1024):
            if s.rd(FB + i):
                self.assertTrue(50 <= i % 128 < 57 and 2 <= i // 128 <= 3, i)

    def test_ascii_and_other_fonts_untouched(self):
        for ch, font in (("a", 0), ("ą", 1)):
            s = self.redraw(ch, 50, 20, 0, font=font)
            self.assertEqual(s.rd(0x7002), 0x4f)
            self.assertFalse(any(s.rd(FB + i) for i in range(1024)))

    def test_clipping(self):
        for x, y in ((124, 58), (-3, 0), (0, 60)):
            s = self.redraw("Ż", x, y, 0)
            self.assertFalse([a for a, v in s.ram.items() if v and not (FB <= a < FB + 1024) and a not in (0x5000,) and a < 0x7000])


if __name__ == "__main__":
    unittest.main()
