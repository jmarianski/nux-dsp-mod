"""Run Touch's actual patch instructions against every MIDI velocity, without hardware."""
import unittest

from nuxdsp import asm, fwmap, patcher, sim


class Code(dict):
    def __missing__(self, key):
        return 0xFFFF


def assemble(knee=32, callback=False):
    mapping = fwmap.load()
    patches = [patcher.load(n, mapping) for n in ("touch_off", "touch_custom", "sustain_in_preset")]
    symbols = dict(mapping.symbols(), CUSTOM_KNEE=knee, OFF_VELOCITY=127)
    if callback:
        symbols["dm_key"] = 0x9000
    layout = patcher.allocate(patches, mapping)
    for patch in patches:
        for key, lines, _ in patcher.code_blocks(patch):
            _, labels = asm.assemble(lines, symbols, origin=layout[key], label_prefix=patch.name, labels_only=True)
            symbols.update(labels)
    for patch in patches:
        for name, fallback in patch.weaks:
            symbols.setdefault(name, symbols[fallback])
    code = Code()
    for patch in patches:
        for key, lines, _ in patcher.code_blocks(patch):
            words, _ = asm.assemble(lines, symbols, origin=layout[key], label_prefix=patch.name, predefined_labels=True)
            code.update(words)
    if callback:
        words, _ = asm.assemble(["ld r7, [r1+5]", "st [0x6001], r7", "ld r7, [r1+3]", "ret"], origin=0x9000)
        code.update(words)
    return code, symbols


class TestTouchCustom(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code, cls.symbols = assemble()

    def event(self, touch, kind, velocity, code=None, symbols=None):
        code, symbols = code or self.code, symbols or self.symbols
        event, frame = 0x5000, 0x7000
        ram = {symbols["touch"]: touch, frame + 15: event,
               event + 2: 2, event + 3: kind, event + 4: 60, event + 5: velocity}
        machine = sim.Sim(code, ram, fp=frame)
        machine.r = [0x1100 + r for r in range(8)]
        machine.call(symbols["tc_vel_hook"])
        return machine, ram

    def test_all_modes_event_types_and_velocities(self):
        for touch in range(7):
            for kind in range(16):
                for velocity in range(128):
                    machine, before = self.event(touch, kind, velocity)
                    expected = velocity
                    if kind == 9 and velocity:
                        if touch == 5:
                            expected = 127
                        elif touch == 6 and velocity > 32:
                            expected = min(127, 2 * velocity - 32)
                    after = before.copy()
                    after[0x5005] = expected
                    self.assertEqual(machine.ram, after, (touch, kind, velocity))
                    self.assertEqual(machine.r[1], 0x5000)
                    self.assertEqual(machine.r[7], kind)
                    self.assertEqual([machine.r[r] for r in (0, 2, 3, 4, 5, 6)],
                                     [0x1100 + r for r in (0, 2, 3, 4, 5, 6)])

    def test_every_knee_is_monotone_preserves_soft_notes_and_reaches_127(self):
        for knee in range(1, 97):
            code, symbols = assemble(knee)
            output = [self.event(6, 9, v, code, symbols)[0].rd(0x5005) for v in range(128)]
            self.assertEqual(output[:knee + 1], list(range(knee + 1)))
            self.assertEqual(output, sorted(output))
            self.assertEqual(output[0], 0)
            self.assertEqual(output[-1], 127)
            self.assertTrue(all(1 <= v <= 127 for v in output[1:]))
            self.assertEqual(output[(127 + knee + 1) // 2], 127)

    def test_menu_round_trip_keeps_old_stored_values(self):
        stored = (5, 0, 1, 2, 3, 4, 6)
        for position, value in enumerate(stored):
            machine = sim.Sim(self.code, {self.symbols["touch"]: value})
            machine.call(self.symbols["tc_load_pos"])
            self.assertEqual(machine.r[7], position)
            machine.r[7] = position
            machine.call(self.symbols["tc_store_pos"])
            self.assertEqual(machine.rd(self.symbols["touch"]), value)

    def test_only_touch_cc_translates_custom_to_hard2(self):
        for cc in range(128):
            for touch in range(7):
                machine = sim.Sim(self.code, {0x7007: cc, 0x7006: touch})
                machine.call(self.symbols["tc_cc_fix"])
                expected = {5: 0, 6: 4}.get(touch, touch) if cc == 0x32 else touch
                self.assertEqual((machine.r[7], machine.r[6]), (cc, expected))

    def test_name_pointer_and_original_names(self):
        for value in range(7):
            machine = sim.Sim(self.code)
            machine.r[1] = value
            machine.call(self.symbols["tc_name_ptr"])
            if value == 6:
                pointer = machine.rd(machine.r[1])
                self.assertEqual([machine.rd(pointer + i) for i in range(7)], list(map(ord, "CUSTOM")) + [0])
            else:
                expected = self.symbols["reverb_names"] if value == 5 else self.symbols["touch_names"] + value
                self.assertEqual(machine.r[1], expected)

    def test_custom_persists_with_sustain(self):
        machine = sim.Sim(self.code, {self.symbols["sustain_cc64"]: 90})
        machine.r[0], machine.r[1] = 6, 0x5000
        machine.call(self.symbols["save_touch_sus"])
        self.assertEqual(machine.rd(0x500c), (91 << 8) | 6)
        machine.wr(self.symbols["sustain_cc64"], 0)
        machine.r[7] = 0x5000
        machine.call(self.symbols["load_touch_sus"])
        self.assertEqual(machine.r[7], 6)
        self.assertEqual(machine.rd(self.symbols["sustain_cc64"]), 90)

    def test_optional_callback_sees_remapped_velocity(self):
        code, symbols = assemble(callback=True)
        machine, _ = self.event(6, 9, 64, code, symbols)
        self.assertEqual(machine.rd(0x6001), 96)
        self.assertEqual(machine.r[7], 9)


if __name__ == "__main__":
    unittest.main()
