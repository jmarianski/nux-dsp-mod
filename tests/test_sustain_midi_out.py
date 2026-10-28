"""Run sustain_midi_out's pedal code against keyboard control changes (no firmware needed)."""
import unittest

from nuxdsp import asm, fwmap, patcher, sim


class Code(dict):
    def __missing__(self, k):
        return 0xFFFF


def pedal(channel, controller, value):
    """so_cc for one keyboard control change: the ccalls it makes, as (target, args in push order)."""
    m = fwmap.load()
    p = patcher.load("sustain_midi_out", m)
    syms = m.symbols()
    words, labels = asm.assemble(p.code, syms, origin=0x19720, label_prefix=p.name)
    ev = 0x6000
    ram = {ev + 2: channel, ev + 3: 0xB, ev + 4: controller, ev + 5: value}
    s = sim.Sim(Code(words), ram, fp=None,  # the hook's code must not need fp
                arity={syms["synth_send"]: 2, syms["usb_out_packet"]: 2, syms["port2_out_packet"]: 2})
    s.r[1] = ev
    s.call(labels["so_cc"])
    assert s.pushed == [], s.pushed
    return s.ccalls, syms


class TestPedalOut(unittest.TestCase):
    def test_cc64_to_synth_usb_and_port2(self):
        calls, syms = pedal(0, 0x40, 0x7F)
        # as sustain_switch: the low word (controller, value) pushed first, then CIN | status
        packet = [0x407F, 0x0BB0]
        self.assertEqual(calls, [(syms["synth_send"], packet), (syms["usb_out_packet"], packet),
                                 (syms["port2_out_packet"], packet)])

    def test_release_and_channel(self):
        calls, _ = pedal(3, 0x40, 0)
        self.assertEqual([a for _, a in calls], [[0x4000, 0x0BB3]] * 3)

    def test_value_masked_to_7_bits(self):
        calls, _ = pedal(0, 0x40, 0xC5)
        self.assertEqual(calls[0][1], [0x4045, 0x0BB0])

    def test_other_controllers_only_synth(self):
        # the stock case: synth_send(0xbb0 | channel, controller << 8 | value), nothing else
        for cc in (0, 1, 7, 0x3F, 0x41, 0x43, 0x7B):
            calls, syms = pedal(2, cc, 0x7F)
            self.assertEqual(calls, [(syms["synth_send"], [cc << 8 | 0x7F, 0x0BB2])])


if __name__ == "__main__":
    unittest.main()
