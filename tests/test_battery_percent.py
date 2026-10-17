"""Simulate battery_percent's curve, the never-up rule and the text (no firmware needed)."""
import unittest

from nuxdsp import asm, fwmap, patcher, sim


class Code(dict):
    def __missing__(self, k):
        return 0xFFFF


DEFAULTS = {"EMPTY": 760, "STEP1": 23, "STEP2": 16, "STEP3": 12, "STEP4": 10, "STEP5": 11, "STEP6": 13,
            "STEP7": 16, "STEP8": 24, "STEP9": 27, "STEP10": 23, "CHARGING": 34, "REDRAW": 2,
            "SAG_LOW": 4, "SAG_KNEE": 858, "SAG_MAX": 16, "SETTLE": 300}
SL_MAGIC, SL_ON, BP_HOLD, BP_SLP, TM_DT = 0x6a3f, 0x6a41, 0x640f, 0x640e, 0x63c1
SETTLED = DEFAULTS["SETTLE"] * 100


def sag(x, params):
    return min(params["SAG_MAX"], params["SAG_LOW"] + max(0, x - params["SAG_KNEE"]) // 4)


def expected(adc, params, asleep=False):
    """Percent of the asleep-scale reading: thresholds EMPTY + sum of the steps before + j/10 of the tenth's step."""
    if not asleep:
        adc += sag(adc, params)
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

    def pct(self, adc, src=1, asleep=False, hold=SETTLED):
        s, y = self.s, self.syms
        s.wr(y["batt_adc"], adc)
        s.wr(y["power_src"], src)
        s.wr(SL_MAGIC, 0xa55a)
        s.wr(SL_ON, int(asleep))
        s.wr(BP_HOLD, hold)
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
        for adc in range(600, 1024):
            r.s.wr(0x6406, 0)
            self.assertEqual(r.pct(adc, asleep=True), expected(adc, r.params, True), adc)
        r.s.wr(0x6406, 0)
        self.assertEqual((r.pct(755), r.pct(756)), (0, 0))   # the stock cut-off: 0% awake
        r.s.wr(0x6406, 0)
        self.assertEqual(r.pct(919), 100)                     # awake right after a full charge (+16)
        r.s.wr(0x6406, 0)
        self.assertEqual(r.pct(935, asleep=True), 100)
        r.s.wr(0x6406, 0)
        self.assertEqual(r.pct(832, asleep=True), 50)         # 760 + 23 + 16 + 12 + 10 + 11

    def test_uneven_steps(self):
        r = Runner(EMPTY=700, STEP1=40, STEP2=0, STEP3=5, STEP10=50)
        for adc in range(650, 1024):
            self.assertEqual(r.pct(adc, src=2), expected(adc - r.params["CHARGING"], r.params), adc)

    def test_sag(self):
        r = Runner()
        self.assertEqual([sag(x, r.params) for x in (790, 858, 861, 862, 890, 902, 950)], [4, 4, 4, 5, 12, 15, 16])
        for asleep, awake in [(925, 907), (892, 880), (866, 862), (800, 796)]:   # log 2026-10-17, same moment
            r.s.wr(0x6406, 0)
            a = r.pct(awake)
            r.s.wr(0x6406, 0)
            self.assertLessEqual(abs(a - r.pct(asleep, asleep=True)), 2, (asleep, awake))

    def test_no_extra_menu_is_awake(self):
        r = Runner()
        r.s.wr(0x6406, 0)
        r.pct(880, asleep=True)
        r.s.wr(SL_MAGIC, 0)
        r.s.wr(0x6406, 0)
        r.s.wr(r.syms["batt_adc"], 880)
        r.s.steps = 0
        r.s.call(r.labels["bp_pct"])
        self.assertEqual(r.s.rd(0x6402), expected(880, r.params))

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


class TestSettle(unittest.TestCase):
    def clk(self, r, asleep, dt=1):
        s = r.s
        s.wr(SL_MAGIC, 0xa55a)
        s.wr(SL_ON, int(asleep))
        s.r[7] = dt
        s.steps = 0
        s.call(r.labels["bp_clk"])
        self.assertEqual(s.r[7], dt)             # kept for extra_menu's clock
        return s.rd(BP_HOLD)

    def test_timer(self):
        r = Runner()
        r.s.wr(BP_SLP, 0)
        r.s.wr(BP_HOLD, 0xc000)                  # garbage after power-on: settled
        self.assertEqual(self.clk(r, False), SETTLED)
        r.s.wr(BP_HOLD, SETTLED - 3)
        self.assertEqual([self.clk(r, False) for _ in range(4)], [SETTLED - 2, SETTLED - 1, SETTLED, SETTLED])
        self.assertEqual(self.clk(r, True), 0)   # fell asleep
        self.assertEqual(self.clk(r, True, 32), 32)
        self.assertEqual(self.clk(r, True, 32), 64)
        r.s.wr(BP_HOLD, SETTLED - 10)
        self.assertEqual(self.clk(r, True, 32), SETTLED)
        self.assertEqual(self.clk(r, False), 0)  # woke up

    def bp_tick(self, r, magic):
        s = r.s
        s.wr(SL_MAGIC, magic)
        s.r[1] = 0x001a
        s.wr(0x001a, 32)
        s.steps = 0
        s.call(r.labels["bp_tick"])
        self.assertEqual(s.rd(0x001a), 0)        # the replaced stock instructions
        return s.rd(BP_HOLD)

    def test_without_extra_menus_clock(self):
        r = Runner()
        r.s.wr(BP_SLP, 0)
        r.s.wr(BP_HOLD, 100)
        self.assertEqual(self.bp_tick(r, 0), 132)       # 32 ticks of battery_tick
        self.assertEqual(self.bp_tick(r, 0xa55a), 132)  # the clock counts it (bp_clk)

    def test_value_held(self):
        r = Runner()
        r.s.wr(0x6406, 0)
        v = r.pct(900)
        self.assertEqual(r.pct(870, asleep=True, hold=100), v)   # just fell asleep: the reading is still low
        self.assertEqual(r.pct(870, asleep=True), expected(870, r.params, True))
        self.assertLess(r.pct(870, asleep=True), v)


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
    def blink(self, r, counter, phase, dt=None):
        s = r.s
        s.wr(SL_MAGIC, 0 if dt is None else 0xa55a)
        s.wr(TM_DT, dt or 0)
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

    def test_asleep_in_real_time(self):
        r = Runner()
        self.assertEqual(self.blink(r, 1300, 1, dt=32), (0, 1332))
        self.assertEqual(self.blink(r, 1368, 1, dt=32), (1, 1400))
        self.assertEqual(self.blink(r, 10, 0, dt=1), (0, 11))


if __name__ == "__main__":
    unittest.main()
