"""sustain_midi_out against the Sustain key's own way to the dongle (sustain_switch 0x33b3); NEK100_FW for the stock words."""
import os
import unittest

from nuxdsp import asm, container, fwmap, patcher

FW = os.environ.get("NEK100_FW")

HOOK = 0x0E57           # cc_out: stores the packet, pushes it, ccall usb_out_packet; 0x0e5f its epilogue
EPILOGUE = 0xD5CC       # 0x0e5f, return with 4 arguments
KEY_TO_DONGLE = 0x33B3  # sustain_switch: fbe2 fffd fbf7 7e06 7e07 d7c8 2cbe (packet at [bp-3], to port2_out_packet)


def assemble():
    m = fwmap.load()
    p = patcher.load("sustain_midi_out", m)
    syms = m.symbols()
    origin = {"sustain_midi_out": 0x9169, "sustain_midi_out#2": 0xF0B0}   # both bank 0
    blocks = patcher.code_blocks(p)
    for key, lines, _ in blocks:
        _, labels = asm.assemble(lines, syms, origin=origin[key], label_prefix=p.name, labels_only=True)
        syms.update(labels)
    code = {}
    for key, lines, _ in blocks:
        words, _ = asm.assemble(lines, syms, origin=origin[key], label_prefix=p.name, predefined_labels=True)
        code.update(words)
    (hook,) = p.hooks
    words, _ = asm.assemble(hook.lines, syms, origin=hook.addr, label_prefix=p.name)
    return hook, words, code, syms


HOOK_DEF, HOOK_WORDS, CODE, SYMS = assemble()


def run(a, n):
    return [CODE[a + i] for i in range(n)]


class TestPedalToDongle(unittest.TestCase):
    def test_hook_keeps_the_packet_and_usb(self):
        # the stock stores (high word at [bp-6], low at [bp-5]) and pushes stay; only the ccall becomes a jump
        stock = HOOK_DEF.expect
        got = [HOOK_WORDS[HOOK + i] for i in range(len(stock))]
        self.assertEqual(got[:6], stock[:6])
        self.assertEqual(got[6:], [0xD0CE, SYMS["so_usb"]])
        self.assertEqual(stock[6:], [0xD7C8, SYMS["usb_out_packet"]])

    def test_usb_then_controller(self):
        a = SYMS["so_usb"]
        self.assertEqual(run(a, 6), [0xD7C8, SYMS["usb_out_packet"],   # the replaced ccall, first
                                     0xD2CF, 0x0004,                   # cc_out's 3rd argument, the controller
                                     0xD0CE, SYMS["so_cc64"]])

    def test_cc64_as_the_sustain_key(self):
        a = SYMS["so_cc64"]
        self.assertEqual(run(a, 2), [0x0F40, 0xE307])   # cmp r7, #0x40; bne +7 (the epilogue)
        high = HOOK_DEF.expect[3]                        # 0xfffa: where cc_out keeps the high word
        key = [0xFBE2, 0xFFFD, 0xFBF7, 0x7E06, 0x7E07, 0xD7C8, SYMS["port2_out_packet"]]
        mine = run(a + 2, 7)
        self.assertEqual(mine[:1] + mine[2:], key[:1] + key[2:])   # same load, pushes and ccall
        self.assertEqual(mine[1], high)
        self.assertEqual(CODE[a + 1 + 1 + (CODE[a + 1] & 0xFF)], EPILOGUE)   # where bne goes, and after the ccall
        self.assertEqual(CODE[a + 9], EPILOGUE)

    def test_calls_from_bank_0(self):
        for a, w in CODE.items():
            self.assertLess(a, 0x10000, hex(a))


@unittest.skipUnless(FW and os.path.exists(FW), "set NEK100_FW to the official firmware file")
class TestStockWords(unittest.TestCase):
    def test_stock(self):
        with open(FW, "rb") as f:
            w = container.words(f.read())
        self.assertEqual(w[HOOK + 8], EPILOGUE)
        self.assertEqual([w[KEY_TO_DONGLE + i] for i in range(7)],
                         [0xFBE2, 0xFFFD, 0xFBF7, 0x7E06, 0x7E07, 0xD7C8, SYMS["port2_out_packet"]])
        # mcu_cc: controller 0x74 from the MCU is the pedal -> pedal_in 0x1204 -> cc_all_parts 0x0e60 -> cc_out
        self.assertEqual(w[0x21A8:0x21AB], [0x0F74, 0xFFE7, 0x2242 - 0x21AB])   # cmp r7, #0x74; long branch to 0x2242
        self.assertEqual(w[0x2242 + 12], 0xD7C8)                                  # ... ccall pedal_in
        self.assertEqual(w[0x2242 + 13], 0x1204)
        self.assertEqual(w[0x0DE2:0x0DE4], [0xD148, 0xDFB6])                      # cc_out: li r1, #pedal_cc
        self.assertEqual(w[0xDFB6], 0x40)


if __name__ == "__main__":
    unittest.main()
