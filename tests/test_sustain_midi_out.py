"""Run sustain_midi_out's hook and code against keyboard control changes (no firmware needed)."""
import unittest

from nuxdsp import asm, fwmap, patcher, sim


class Code(dict):
    def __missing__(self, k):
        return 0xFFFF


HOOK, SYNTH_CALL = 0x28EF, 0x28F9


def assemble():
    m = fwmap.load()
    p = patcher.load("sustain_midi_out", m)
    syms = m.symbols()
    origin = {"sustain_midi_out": 0xF0B0, "sustain_midi_out#2": 0x19720}   # bank 0, bank 1 (far)
    blocks = patcher.code_blocks(p)
    for key, lines, _ in blocks:
        _, labels = asm.assemble(lines, syms, origin=origin[key], label_prefix=p.name, labels_only=True)
        syms.update(labels)
    code = Code()
    for key, lines, _ in blocks:
        words, _ = asm.assemble(lines, syms, origin=origin[key], label_prefix=p.name, predefined_labels=True)
        code.update(words)
    (hook,) = p.hooks
    words, _ = asm.assemble(hook.lines, syms, origin=hook.addr, label_prefix=p.name)
    assert sorted(words) == list(range(HOOK, SYNTH_CALL)), "the hook ends right before the stock ccall"
    code.update(words)
    # the stock words after the hook: ccall synth_send, then the case's exit (here a ret, to end the run)
    stock, _ = asm.assemble(["ccall %#x" % syms["synth_send"], "ret"], origin=SYNTH_CALL)
    code.update(stock)
    return code, syms


CODE, SYMS = assemble()


def run(channel, controller, value):
    """The CC case from the hook to its exit, for one keyboard event: its ccalls, (target, args in push order)."""
    ev = 0x6000
    ram = {ev + 2: channel, ev + 3: 0xB, ev + 4: controller, ev + 5: value}
    s = sim.Sim(CODE, ram, fp=None,  # nothing here may need fp
                arity={SYMS[n]: 2 for n in ("synth_send", "usb_out_packet", "port2_out_packet")})
    s.r[1] = ev
    s.call(HOOK)
    assert s.pushed == [], s.pushed
    return s.ccalls


class TestPedalOut(unittest.TestCase):
    def test_cc64_to_usb_port2_and_synth(self):
        # as sustain_switch: the low word (controller, value) pushed first, then CIN | status
        packet = [0x407F, 0x0BB0]
        self.assertEqual(run(0, 0x40, 0x7F), [(SYMS["usb_out_packet"], packet), (SYMS["port2_out_packet"], packet),
                                              (SYMS["synth_send"], packet)])

    def test_release_and_channel(self):
        self.assertEqual([a for _, a in run(3, 0x40, 0)], [[0x4000, 0x0BB3]] * 3)

    def test_value_masked_to_7_bits(self):
        self.assertEqual(run(0, 0x40, 0xC5)[0][1], [0x4045, 0x0BB0])

    def test_other_controllers_only_synth(self):
        # the stock case: synth_send(0xbb0 | channel, controller << 8 | value), nothing else
        for cc in (0, 1, 7, 0x3F, 0x41, 0x43, 0x7B):
            self.assertEqual(run(2, cc, 0x7F), [(SYMS["synth_send"], [cc << 8 | 0x7F, 0x0BB2])])

    def test_output_calls_from_bank_0(self):
        # port2_out_packet misbehaves when ccalled from bank 1 (checked on the device): every ccall of the patch
        # sits below 0x10000
        for a, w in CODE.items():
            if w == 0xD7C8:
                self.assertLess(a, 0x10000, hex(a))


if __name__ == "__main__":
    unittest.main()
