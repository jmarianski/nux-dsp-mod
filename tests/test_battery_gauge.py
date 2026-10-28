"""Simulate battery_gauge together with battery_percent (no firmware needed): the flash page at power-on and
power-off, the rates, the minute's correction and what is shown."""
import unittest

from nuxdsp import asm, fwmap, patcher, sim


class Code(dict):
    def __missing__(self, k):
        return 0xFFFF


BP, BG = 0x1a280, 0x1b000
SL_MAGIC, SL_ON = 0x6a3f, 0x6a41
BG_Q, BG_OK, BG_MAG, BG_SHOWN, BG_DRAWN, BG_ST = 0x6424, 0x642a, 0x6429, 0x642b, 0x642c, 0x641d
BP_VAL, BP_MAG = 0x6402, 0x6406
TL_MAGIC, TL_AMPOFF = 0x6330, 0x6335
PAGE, RP = 0x7e00, 0x7f00                       # the fake flash page and its read pointer


def build(**params):
    m = fwmap.load()
    y = m.symbols()
    bp, bg = patcher.load("battery_percent", m), patcher.load("battery_gauge", m)
    prm = dict({q.name: q.default for q in bp.params + bg.params}, **params)
    _, lb = asm.assemble(bp.code, dict(y, bg_clk=0, bg_raw=0, bg_show=0, **prm), origin=BP,
                         label_prefix=bp.name, labels_only=True)
    _, lg = asm.assemble(bg.code, dict(y, bp_pct=0, bp_asleep=0, **prm), origin=BG,
                         label_prefix=bg.name, labels_only=True)
    pub = lambda labels: {k: v for k, v in labels.items() if "." not in k}
    wb, lb = asm.assemble(bp.code, dict(y, **pub(lg), **prm), origin=BP, label_prefix=bp.name)
    wg, lg = asm.assemble(bg.code, dict(y, **pub(lb), **prm), origin=BG, label_prefix=bg.name)
    code = Code(wb)
    code.update(wg)
    for a in list(code):                        # push #imm / ccall: li r0 (C functions are not simulated)
        if code[a] in (0xC14C, 0xD7C8):
            code[a] = 0xD048
    stubs = {                                   # the flash routines: CS off, start reading, next word
        0x07b2d: ["ret"],
        0x07bf1: ["li r7, #%d" % PAGE, "st [%d], r7" % RP, "ret"],
        y["flash_get_word"]: ["ld r7, [%d]" % RP, "mov r1, r7", "ld r0, [r1+0]", "add r7, #1",
                              "st [%d], r7" % RP, "ret"],
    }
    for a, lines in stubs.items():
        w, _ = asm.assemble(lines, {}, origin=a)
        code.update(w)
    return sim.Sim(code), y, dict(lb, **lg), prm


class Gauge:
    def __init__(self, **params):
        self.s, self.y, self.l, self.p = build(**params)

    def call(self, label, **regs):
        s = self.s
        for k, v in regs.items():
            s.r[int(k[1])] = v
        s.steps = 0
        s.call(self.l[label], max_steps=2000000)
        return s

    def page(self, words):
        for i, w in enumerate(words):
            self.s.wr(PAGE + i, w)

    def state(self, src=1, adc=850, asleep=False, full=0):
        s, y = self.s, self.y
        s.wr(y["power_src"], src)
        s.wr(y["batt_adc"], adc)
        s.wr(y["charge_full"], full)
        s.wr(SL_MAGIC, 0xa55a)
        s.wr(SL_ON, int(asleep))

    def boot(self, q=None):
        self.page([0x6267, q, (q + 0x5a5a) & 0xffff] if q is not None else [0xffff] * 3)
        self.call("bg_boot")

    def run(self, seconds, dt=100):
        """at least that many seconds of ticks of dt x 10 ms through battery_percent's bp_clk"""
        for _ in range(-(-seconds * 100 // dt)):
            self.call("bp_clk", r7=dt)

    def q(self):
        return self.s.rd(BG_Q)

    def draw(self):
        """bp_draw's value: bp_pct, then bg_show (its drawing is C calls, not simulated)"""
        self.call("bp_pct")
        self.call("bg_show")
        return self.s.rd(BP_VAL)

    def curve(self, adc, asleep=True):
        """battery_percent's own value of that reading"""
        self.state(adc=adc, asleep=asleep)
        self.s.wr(BP_MAG, 0)
        self.call("bp_pct")
        return self.s.rd(BP_VAL)


class TestBoot(unittest.TestCase):
    def test_page(self):
        g = Gauge()
        g.boot(4321)
        self.assertEqual((g.s.rd(BG_MAG), g.s.rd(BG_OK), g.q()), (0x6267, 1, 4321))
        for bad in ([0x6267, 4321, 0], [0x6266, 4321, 4321 + 0x5a5a], [0x6267, 10001, 10001 + 0x5a5a], [0xffff] * 3):
            g.page(bad)
            g.call("bg_boot")
            self.assertEqual(g.s.rd(BG_OK), 0, bad)

    def test_redraw_after_load(self):
        g = Gauge()
        last = g.y["power_src"] + 0x13          # 0x0019
        g.s.wr(last, 1)
        g.boot(4321)
        self.assertEqual(g.s.rd(last), 0xffff)
        g.page([0xffff] * 3)
        g.s.wr(last, 1)
        g.call("bg_boot")
        self.assertEqual(g.s.rd(last), 1)

    def test_nothing_before_boot(self):
        g = Gauge()
        g.state()
        g.s.wr(BG_Q, 5000)
        g.s.wr(BG_MAG, 1)                       # after init_all's copy
        g.run(7200)
        self.assertEqual(g.q(), 5000)

    def test_clk_keeps_r1_and_r7(self):
        g = Gauge()
        g.state(asleep=False)
        g.boot(5000)
        for _ in range(130):                    # a minute's correction (bp_pct uses r1) on the way
            g.s.r[1] = 0x1234
            s = g.call("bg_clk", r7=77)
            self.assertEqual((s.r[1], s.r[7]), (0x1234, 77))


class TestRates(unittest.TestCase):
    def hour(self, asleep=False, ampoff=None, src=1, dt=100, q=5000):
        g = Gauge(JUMP=100, GAIN_SH=15, GAIN_LOW_SH=15)   # no correction from the reading here
        g.state(src=src, asleep=asleep)
        g.boot(q)
        if ampoff is not None:
            g.s.wr(TL_MAGIC, 0x4c47)
            g.s.wr(TL_AMPOFF, ampoff)
        g.run(3600, dt)
        return g

    def test_asleep(self):
        self.assertEqual(5000 - self.hour(asleep=True, dt=32).q(), 190)

    def test_awake(self):
        self.assertEqual(5000 - self.hour().q(), 460)
        self.assertEqual(5000 - self.hour(ampoff=0).q(), 460)

    def test_speaker_off_needs_telemetry(self):
        self.assertEqual(5000 - self.hour(ampoff=1).q(), 275)

    def test_charging(self):
        self.assertEqual(self.hour(src=2).q() - 5000, 3200)
        self.assertEqual(self.hour(src=2, q=9500).q(), 9900)    # 99% until the charger says full

    def test_full_and_empty(self):
        g = Gauge()
        g.state(src=2, full=1)
        g.boot(3000)
        g.run(1)
        self.assertEqual(g.q(), 10000)
        g = Gauge(JUMP=100, GAIN_SH=15, GAIN_LOW_SH=15)
        g.state()
        g.boot(10)
        g.run(3600)
        self.assertEqual(g.q(), 0)


class TestCorrection(unittest.TestCase):
    def setUp(self):
        self.g = Gauge()

    def settled(self, q, adc, asleep=True):
        g = self.g
        v = g.curve(adc, asleep)
        g.state(adc=adc, asleep=asleep)
        g.boot(q)
        g.run(60, 32)                           # the first minute: the check
        g.s.wr(BP_MAG, 0x5aa5)                  # START is over
        g.s.wr(BG_ST, g.p["HOLD"])
        return v

    def test_first_minute_keeps_a_close_q(self):
        g = self.g
        v = g.curve(850)
        g.state(adc=850, asleep=True)
        g.boot(v * 100 + 2000)                  # 20 points above: kept
        g.run(60, 32)
        self.assertEqual(g.s.rd(BG_OK), 2)
        self.assertGreater(g.q(), v * 100 + 1990)
        g.boot(v * 100 + 2600)                  # 26: the reading
        g.run(60, 32)
        self.assertAlmostEqual(g.q(), v * 100, delta=1)

    def test_first_minute_without_page(self):
        g = self.g
        v = g.curve(880, asleep=False)
        g.state(adc=880)
        g.boot()
        self.assertEqual(g.s.rd(BG_OK), 0)
        g.run(60)
        self.assertEqual((g.s.rd(BG_OK), g.q()), (2, v * 100))

    def test_moves_towards_the_curve(self):
        g = self.g
        v = self.settled(5000, 870)             # well above 20%
        self.assertGreater(v, 40)
        before = g.q()
        g.run(60, 32)
        d = v * 100 - before
        self.assertAlmostEqual(g.q(), before + (abs(d) >> 7) * (1 if d > 0 else -1) - 3, delta=1)   # 3: a minute asleep

    def test_stronger_below_low(self):
        g = self.g
        v = self.settled(1000, 775)             # about 6%, q 10%
        self.assertLess(v, 15)
        before = g.q()
        g.run(60, 32)
        self.assertAlmostEqual(g.q(), before - ((before - v * 100) >> 4) - 3, delta=1)

    def test_jump(self):
        g = self.g
        v = self.settled(9000, 830)
        g.run(60, 32)
        self.assertAlmostEqual(g.q(), v * 100, delta=4)   # the jump, then the rest of the minute asleep

    def test_not_while_settling_or_starting(self):
        g = self.g
        self.settled(5000, 870)
        g.s.wr(BG_ST, 10)
        before = g.q()
        g.run(60, 32)
        self.assertAlmostEqual(g.q(), before - 3, delta=1)   # only the drain
        g.s.wr(BG_ST, g.p["HOLD"])
        g.s.wr(BP_MAG, 0)                       # charger, or no reading yet
        g.run(60, 32)
        self.assertAlmostEqual(g.q(), before - 6, delta=1)


class TestShow(unittest.TestCase):
    def test_shown_never_up_on_battery(self):
        g = Gauge()
        g.state(adc=950)                        # the curve says 100
        g.boot(4249)
        self.assertEqual(g.draw(), 42)          # q, not the curve, from the first drawing
        g.s.wr(BG_Q, 4351)
        self.assertEqual(g.draw(), 42)
        g.s.wr(BG_Q, 4049)
        self.assertEqual((g.draw(), g.s.rd(BG_SHOWN), g.s.rd(BG_DRAWN)), (40, 40, 40))

    def test_charger(self):
        g = Gauge()
        g.state(src=2, adc=900)
        g.boot(4000)
        self.assertEqual((g.draw(), g.s.rd(BG_SHOWN)), (40, 0xffff))
        g.s.wr(BG_Q, 4600)
        self.assertEqual(g.draw(), 46)          # up while charging
        g.state(adc=850)
        self.assertEqual(g.draw(), 46)          # unplugged: from there, never up

    def test_without_q_the_curve(self):
        g = Gauge()
        v = g.curve(870, asleep=False)
        g.state(adc=870)
        g.boot()
        g.s.wr(BP_MAG, 0)
        self.assertEqual(g.draw(), v)

    def test_redraw_request(self):
        g = Gauge(JUMP=100, GAIN_SH=15, GAIN_LOW_SH=15)
        last = g.y["power_src"] + 0x13          # 0x0019
        g.state(asleep=True)
        g.boot(5049)
        self.assertEqual(g.draw(), 50)
        g.s.wr(last, 1)
        g.run(600, 32)                          # 32 hundredths: still 50
        self.assertEqual(g.s.rd(last), 1)
        g.run(1500, 32)
        self.assertEqual(g.s.rd(last), 0xffff)  # 49 to draw


class TestSave(unittest.TestCase):
    def test_page_written(self):
        g = Gauge()
        buf = g.y["user_presets"] + 124
        g.state()
        g.boot(6543)
        g.call("bg_save")
        self.assertEqual([g.s.rd(buf + i) for i in range(4)], [0x6267, 6543, (6543 + 0x5a5a) & 0xffff, 0xffff])
        self.assertEqual(g.s.rd(buf + 30), 0xffff)

    def test_not_without_q_or_on_low_battery(self):
        g = Gauge()
        buf = g.y["user_presets"] + 124
        g.state()
        g.boot()
        g.call("bg_save")
        self.assertEqual(g.s.rd(buf), 0)
        g.boot(6543)
        g.s.wr(g.y["batt_low"], 1)
        g.call("bg_save")
        self.assertEqual(g.s.rd(buf), 0)


if __name__ == "__main__":
    unittest.main()
