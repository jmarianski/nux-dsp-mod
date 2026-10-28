"""Simulate extra_menu's clock, held keys and Speaker (its far block; no firmware needed)."""
import unittest

from nuxdsp import asm, fwmap, patcher, sim


class Code(dict):
    def __missing__(self, k):
        return 0xFFFF


STUB = 0x9000                                   # tl_amp, bp_clk: a bare ret
SL_MAGIC, SL_ON, AMP_CNT, SL_GRACE = 0x6a3f, 0x6a41, 0x6a45, 0x6a4a
TM_NOW, TM_DT, NT_PED, NT_MAP = 0x63c0, 0x63c1, 0x63c2, 0x63c8
FP, EV = 0x7000, 0x7100


class Runner:
    def __init__(self, **params):
        m = fwmap.load()
        p = patcher.load("extra_menu", m)
        self.params = dict({q.name: q.default for q in p.params}, **params)
        _, lines, _ = next(block for block in patcher.code_blocks(p)
                           if any(line.startswith("amp_chk:") for line in block[1]))
        self.y = dict(m.symbols(), tl_amp=STUB, bp_clk=STUB, **self.params)
        words, self.labels = asm.assemble(lines, self.y, origin=0x1a280, label_prefix=p.name)
        for a, w in list(words.items()):   # port writes (d0cd/d0cc + mask): li r0 in the simulation
            if w in (0xD0CC, 0xD0CD):
                words[a] = 0xD048
        code = Code(words)
        code[STUB] = 0xD1CA
        self.s = sim.Sim(code, {FP + 15: EV}, fp=FP)

    def run(self, label, **regs):
        s = self.s
        for k, v in regs.items():
            s.r[int(k[1])] = v
        s.steps = 0
        s.call(self.labels[label])
        return s

    def idle(self, v=None):
        y, s = self.y["idle_ticks"], self.s
        if v is not None:
            s.wr(y, v >> 16)
            s.wr(y + 1, v & 0xFFFF)
        return s.rd(y) << 16 | s.rd(y + 1)


class TestClock(unittest.TestCase):
    def test_awake_and_before_boot(self):
        r = Runner()
        r.s.wr(TM_DT, 32)                       # garbage before st_boot: 1
        r.s.wr(TM_NOW, 0xffff)
        r.idle(100)
        r.run("tm_tick")
        self.assertEqual((r.s.rd(TM_DT), r.s.rd(TM_NOW), r.idle()), (1, 0, 100))
        r.s.wr(SL_MAGIC, 0xa55a)
        r.s.wr(TM_DT, 7)                        # anything but 1 or SLEEP_W: 1
        r.run("tm_tick")
        self.assertEqual((r.s.rd(TM_DT), r.s.rd(TM_NOW)), (1, 1))

    def test_slow_ticks_count_real_time(self):
        r = Runner()
        r.s.wr(SL_MAGIC, 0xa55a)
        r.s.wr(TM_DT, 32)
        for before, after in [(100, 131), (0xffe0, 0xffff), (0xfff0, 0x1000f), (0x2fffff, 0x30001e)]:
            r.idle(before)
            r.run("tm_tick")
            self.assertEqual(r.idle(), after, hex(before))   # + the stock 1 = 32 per slow tick
        self.assertEqual(r.s.rd(TM_NOW), 4 * 32)

    def test_auto_off_asleep(self):
        """30 min Auto Off, 1 min awake then asleep: off after 29 more minutes, not ~15 h."""
        r = Runner()
        r.s.wr(SL_MAGIC, 0xa55a)
        r.s.wr(TM_DT, 32)
        r.idle(6000)
        slow = 0
        while r.idle() < 180000:
            r.idle(r.idle() + 1)                # the stock tick
            r.run("tm_tick")
            slow += 1
        self.assertAlmostEqual(slow * 0.32 / 60, 29, delta=0.01)


class TestKeys(unittest.TestCase):
    def event(self, r, label, d1, d2, ch=0):
        r.s.wr(EV + 2, ch)
        r.s.wr(EV + 4, d1)
        r.s.wr(EV + 5, d2)
        s = r.run(label, r6=0x1234, r7=0x5678)
        self.assertEqual((s.r[6], s.r[7], s.r[1]), (0x1234, 0x5678, r.y["idle_ticks"]))

    def busy(self, r):
        return r.run("nt_busy").r[7]

    def test_held_keys(self):
        r = Runner()
        r.idle(10)
        for k in range(8):
            r.s.wr(NT_MAP + k, 0)
        self.assertEqual(self.busy(r), 0)
        for key in (0, 15, 16, 60, 127):
            self.event(r, "nt_on", key, 100)
        self.assertEqual([r.s.rd(NT_MAP + k) for k in range(8)], [0x8001, 1, 0, 0x1000, 0, 0, 0, 0x8000])
        self.assertEqual(self.busy(r), 1)
        self.event(r, "nt_on", 60, 0x80)        # velocity 0 (7 bits): off
        for key in (0, 15, 16):
            self.event(r, "nt_off", key, 64)
        self.event(r, "nt_on", 127, 50)         # twice on, once off: up
        self.assertEqual(self.busy(r), 1)
        self.event(r, "nt_off", 127, 0)
        self.assertEqual([r.s.rd(NT_MAP + k) for k in range(8)], [0] * 8)
        self.assertEqual(self.busy(r), 0)

    def test_lost_note_off(self):
        r = Runner()
        r.s.wr(NT_MAP + 3, 0x1000)
        r.idle(11999)
        self.assertEqual(self.busy(r), 1)
        r.idle(12000)                           # 2 min without a key event
        self.assertEqual(self.busy(r), 0)
        r.idle(0x10005)
        self.assertEqual(self.busy(r), 0)

    def test_pedal(self):
        r = Runner()
        self.event(r, "nt_cc", 0x40, 127)
        self.assertEqual(r.s.rd(NT_PED), 1)
        self.event(r, "nt_cc", 0x07, 0)         # another controller: no change
        self.assertEqual(r.s.rd(NT_PED), 1)
        self.event(r, "nt_cc", 0x40, 63)
        self.assertEqual(r.s.rd(NT_PED), 0)
        self.event(r, "nt_cc", 0x40, 64)
        self.assertEqual(r.s.rd(NT_PED), 1)
        self.event(r, "nt_cc", 0x40, 0, ch=15)  # the MCU's channel: controller 64 there is not the pedal
        self.assertEqual(r.s.rd(NT_PED), 1)


class TestSpeaker(unittest.TestCase):
    def setup(self, speaker, dt=1):
        r = Runner()
        s, y = r.s, r.y
        s.wr(y["presets_header"], 0x8000 | speaker << 12)
        s.wr(TM_DT, dt)
        s.wr(0x0011, 0)                          # welcome over: outputs on
        r.idle(5)
        return r

    def tick(self, r, cnt=None):
        """-> (speaker on, amp_cnt after)."""
        if cnt is not None:
            r.s.wr(AMP_CNT, cnt)
        s = r.run("amp_chk")
        return s.r[7] == 0, s.rd(AMP_CNT)

    def test_after_the_last_sound(self):
        for speaker, secs in [(0, 5), (1, 30), (2, 60)]:
            r = self.setup(speaker)
            self.assertEqual(self.tick(r, 100 * secs - 2), (True, 100 * secs - 1))
            self.assertEqual(self.tick(r), (False, 100 * secs), speaker)
            r.idle(0)                                 # a panel key (idle_ticks): no matter
            self.assertEqual(self.tick(r)[0], False)

    def test_always_on_and_defaults(self):
        r = self.setup(3)
        self.assertEqual(self.tick(r, 29999), (True, 30000))
        self.assertEqual(self.tick(r), (True, 30000))   # stops counting
        r.s.wr(r.y["presets_header"], 0x0000)           # not ours yet: always on
        self.assertEqual(self.tick(r, 20000)[0], True)

    def test_held_key_keeps_it_on(self):
        r = self.setup(0)
        r.s.wr(NT_MAP + 2, 4)
        self.assertEqual(self.tick(r, 5000), (True, 0))
        r.s.wr(NT_MAP + 2, 0)
        self.assertEqual(self.tick(r, 499), (False, 500))

    def test_sustain_rings_on(self):
        tail = Runner().params["SUS_TAIL"] * 100
        for ped, key, pedal in [(1, 0, 0), (0, 1, 0), (0, 0, 127)]:   # pedal: pedal_in's state (controller 0x74)
            r = self.setup(0)
            r.s.wr(NT_PED, ped)
            r.s.wr(r.y["sustain_on"], key)
            r.s.wr(r.y["pedal_state"], pedal)
            self.assertEqual(self.tick(r, 600)[0], True)
            self.assertEqual(self.tick(r, tail - 2)[0], True)
            self.assertEqual(self.tick(r)[0], False)
        r = self.setup(2)                                # 1 min is longer than the tail
        r.s.wr(NT_PED, 1)
        self.assertEqual(self.tick(r, tail + 100)[0], True)

    def test_asleep(self):
        r = self.setup(3, dt=32)
        self.assertEqual(self.tick(r, 100), (True, 132))  # slow ticks count 32
        self.assertEqual(self.tick(r, 0xc000), (True, 30000))   # garbage at power-on
        r.s.wr(SL_ON, 1)
        self.assertEqual(self.tick(r)[0], False)
        r.s.wr(SL_ON, 0)
        r.s.wr(SL_GRACE, 3)
        self.assertEqual(self.tick(r)[0], False)


if __name__ == "__main__":
    unittest.main()
