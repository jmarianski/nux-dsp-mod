"""Simulate battery_percent's curve, the never-up rule and the text (no firmware needed)."""
import unittest

from nuxdsp import asm, fwmap, patcher, sim


class Code(dict):
    def __missing__(self, k):
        return 0xFFFF


DEFAULTS = {"EMPTY": 756, "STEP1": 23, "STEP2": 16, "STEP3": 12, "STEP4": 10, "STEP5": 11, "STEP6": 13,
            "STEP7": 16, "STEP8": 19, "STEP9": 22, "STEP10": 24, "CHARGING": 34, "REDRAW": 2}


def expected(adc, params):
    """Percent: thresholds EMPTY + sum of the steps before + j/10 of the tenth's step."""
    a, b, pct = 10 * adc, 10 * params["EMPTY"], 0
    if a < b:
        return 0
    for i in range(1, 11):
        for _ in range(10):
            b += params["STEP%d" % i]
            if a < b:
                return pct
            pct += 1
            if pct == 100:
                return 100
    return pct


class Runner:
    def __init__(self, **params):
        m = fwmap.load()
        p = patcher.load("battery_percent", m)
        self.params = dict(DEFAULTS, **params)
        self.syms = dict(m.symbols(), **self.params)
        words, self.labels = asm.assemble(p.code, self.syms, origin=0x1a280, label_prefix=p.name)
        self.s = sim.Sim(Code(words))

    def pct(self, adc, src=1):
        s, y = self.s, self.syms
        s.wr(y["batt_adc"], adc)
        s.wr(y["power_src"], src)
        s.steps = 0
        s.call(self.labels["bp_pct"])
        return s.rd(0x6402)

    def text(self, val):
        s = self.s
        s.wr(0x6402, val)
        s.steps = 0
        s.call(self.labels["bp_text"])
        out, a = "", 0x6420
        while s.rd(a):
            out += chr(s.rd(a))
            a += 1
        return out, s.rd(0x6409)


class TestCurve(unittest.TestCase):
    def test_default_line(self):
        r = Runner()
        for adc in range(600, 1024):
            r.s.wr(0x6406, 0)  # afresh: no never-up memory
            self.assertEqual(r.pct(adc), expected(adc, r.params), adc)
        r.s.wr(0x6406, 0)
        self.assertEqual((r.pct(755), r.pct(756)), (0, 0))
        r.s.wr(0x6406, 0)
        self.assertEqual(r.pct(922), 100)
        r.s.wr(0x6406, 0)
        self.assertEqual(r.pct(828), 50)  # 756 + 23 + 16 + 12 + 10 + 11

    def test_uneven_steps(self):
        r = Runner(EMPTY=700, STEP1=40, STEP2=0, STEP3=5, STEP10=50)
        for adc in range(650, 1024):
            self.assertEqual(r.pct(adc, src=2), expected(adc - r.params["CHARGING"], r.params), adc)

    def test_never_up_on_battery(self):
        r = Runner()
        r.s.wr(0x6406, 0)
        self.assertEqual(r.pct(900), expected(900, r.params))
        low = r.pct(850)
        self.assertEqual(r.pct(880), low)          # recovered voltage: still the lower value
        self.assertEqual(r.pct(300), low)          # no reading yet: not remembered
        self.assertEqual(r.pct(800), expected(800, r.params))
        r.pct(990, src=2)                          # charger: afresh
        self.assertEqual(r.pct(900), expected(900, r.params))

    def test_charging_takes_off_the_offset(self):
        r = Runner()
        self.assertEqual(r.pct(862, src=2), expected(828, r.params))
        self.assertEqual(Runner(CHARGING=18).pct(846, src=2), expected(828, r.params))


class TestText(unittest.TestCase):
    def test_digits_and_width(self):
        r = Runner()
        self.assertEqual(r.text(0), ("0", 119))
        self.assertEqual(r.text(7), ("7", 119))
        self.assertEqual(r.text(1), ("1", 120))      # draw_text_impl advances one less after '1'
        self.assertEqual(r.text(73), ("73", 114))
        self.assertEqual(r.text(11), ("11", 116))
        self.assertEqual(r.text(99), ("99", 114))
        self.assertEqual(r.text(100), ("100", 110))  # 110..122, past the lightning (107..111) only at 100% = full


class TestBlink(unittest.TestCase):
    def blink(self, r, counter, phase):
        s = r.s
        s.wr(0x001e, counter)
        s.wr(0x6407, phase)
        s.steps = 0
        s.call(r.labels["bp_blink"])
        return s.r[7], s.rd(0x001e)

    def test_power_off_at_1400_as_stock(self):
        r = Runner()
        self.assertEqual(self.blink(r, 1398, 1), (0, 1399))  # 1399 % 200 >= 100: shown, already drawn
        self.assertEqual(self.blink(r, 1399, 1), (1, 1400))

    def test_phase_kept_without_drawing(self):
        r = Runner()
        self.assertEqual(self.blink(r, 0, 0), (0, 1))        # hidden first, as stock
        self.assertEqual(self.blink(r, 250, 0), (0, 251))
        self.assertEqual(self.blink(r, 1150, 1), (0, 1151))


if __name__ == "__main__":
    unittest.main()
