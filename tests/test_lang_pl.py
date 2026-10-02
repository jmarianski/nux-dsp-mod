"""lang_pl against the official firmware (set NEK100_FW): tables read back through their pointers,
everything the firmware references elsewhere stays readable, images change only inside the text area."""
import os
import unittest

from nuxdsp import container, disasm, fwmap, patcher, pixfont

FW = os.environ.get("NEK100_FW")


def cstr(w, a):
    out = ""
    while w[a]:
        out += chr(w[a])
        a += 1
    return out


@unittest.skipUnless(FW and os.path.exists(FW), "set NEK100_FW to the official firmware file")
class TestLangPl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FW, "rb") as f:
            cls.img = f.read()
        cls.m = fwmap.load()
        cls.p = patcher.load("lang_pl", cls.m)
        out, _ = patcher.build(cls.img, cls.m, [patcher.load("polish_font", cls.m), cls.p])
        cls.o, cls.n = container.words(cls.img), container.words(out)
        cls.lo, cls.hi = cls.m.ramdata

    def table(self, w, ram, count):
        return [cstr(w, self.lo + p) for p in w[self.lo + ram:self.lo + ram + count]]

    def test_tables_read_back(self):
        for ram, count, entries, _ in self.p.tables:
            old, new = self.table(self.o, ram, count), self.table(self.n, ram, count)
            strings = dict(self.p.strings)
            want = [strings.get(s, s) for s in old]  # .string changes shared strings too
            for k, txt in entries:
                if k.isdigit():
                    want[int(k) - 1] = txt
                else:
                    want = [txt if s == k else s for s in want]
            self.assertEqual(new, want, hex(ram))

    def test_other_references_still_strings(self):
        # every string a code literal or another pointer may refer to starts where it did,
        # and is the original or its translation
        ptabs = {self.lo + r + i for r, c, _, _ in self.p.tables for i in range(c)}
        trans = {}
        for ram, count, entries, _ in self.p.tables:
            old = self.table(self.o, ram, count)
            for k, txt in entries:
                trans[old[int(k) - 1] if k.isdigit() else k] = txt
        trans.update(dict(self.p.strings))
        refs = {self.o[a] for a in range(self.lo, self.hi) if a not in ptabs}
        refs |= {lit for _, x, lit in disasm.iter_insns(self.o, self.m.code)
                 if lit is not None and x not in (0xd6c8, 0xd7c8)}
        for r in refs:
            a = self.lo + r
            if not (self.lo < a < self.hi and self.o[a - 1] == 0):
                continue
            old, new = cstr(self.o, a), cstr(self.n, a)
            if not old or not all(0x20 <= ord(c) < 0x7f for c in old):
                continue
            self.assertIn(new, (old, trans.get(old)), "%#x %r" % (r, old))

    def test_names_fit(self):
        for ram, count, entries, _ in self.p.tables:
            for _, txt in entries:
                self.assertLessEqual(len(txt), 18, txt)

    def test_images_change_only_in_text_area(self):
        for idx, (x, y, dw, dh), lines, _, inv, bold in self.p.draws:
            off, size, width, height = patcher.glyph_info(self.o, self.m, idx)
            base, cb = self.m.glyphs[1], (height + 7) // 8

            def px(w, xx, yy):
                i = off + xx * cb + yy // 8
                return (w[base + i // 2] >> (8 * (i & 1))) >> (7 - yy % 8) & 1
            want = pixfont.draw(dw, dh, [(int(t), s) for t, s in lines], inv, bold)
            for yy in range(height):
                for xx in range(width):
                    inside = x <= xx < x + dw and y <= yy < y + dh
                    exp = (want[yy - y][xx - x] == "#") if inside else px(self.o, xx, yy)
                    self.assertEqual(px(self.n, xx, yy), exp, "image %#x at %d,%d" % (idx, xx, yy))


class TestPixfont(unittest.TestCase):
    def test_polish_letters(self):
        for c in "ĄĆĘŁŃÓŚŹŻ":
            rows = pixfont.glyph(c, "small")
            self.assertEqual(len(rows), 7)
            self.assertTrue("#" in rows[0] or "#" in rows[6] or c == "Ł", c)

    def test_narrow_when_needed(self):
        self.assertEqual(len(pixfont.fit("PODZIAŁ", 30)[0]), len(pixfont.render("PODZIAŁ", "narrow")[0][0]))
        with self.assertRaises(pixfont.FontError):
            pixfont.fit("BARDZO DŁUGI NAPIS", 30)
