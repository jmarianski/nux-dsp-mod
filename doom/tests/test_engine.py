import mido
import pytest

from pianodoom.engine import Engine
from pianodoom.mapping import load_layout, parse_layout


class Recorder:
    def __init__(self):
        self.log = []

    def press(self, key):
        self.log.append(("down", key))

    def release(self, key):
        self.log.append(("up", key))


def on(note, vel=64):
    return mido.Message("note_on", note=note, velocity=vel)


def off(note):
    return mido.Message("note_off", note=note)


def pedal(value, control=64):
    return mido.Message("control_change", control=control, value=value)


@pytest.fixture
def setup():
    rec = Recorder()
    return Engine(load_layout(), rec), rec


def test_default_layout_loads():
    layout = load_layout()
    assert layout.notes[48] == "turn_left"  # C3
    assert layout.cc[64] == "fire"


def test_press_and_release(setup):
    eng, rec = setup
    assert eng.handle(on(48)) == "turn_left"
    eng.handle(off(48))
    assert rec.log == [("down", "KEY_LEFT"), ("up", "KEY_LEFT")]


def test_note_on_velocity_zero_is_release(setup):
    eng, rec = setup
    eng.handle(on(48))
    eng.handle(on(48, 0))
    assert rec.log[-1] == ("up", "KEY_LEFT")


def test_forte_adds_run(setup):
    eng, rec = setup
    eng.handle(on(49, 120))  # C#3 forward, hard
    eng.handle(off(49))
    assert rec.log == [("down", "KEY_UP"), ("down", "KEY_RIGHTSHIFT"), ("up", "KEY_UP"), ("up", "KEY_RIGHTSHIFT")]


def test_forte_only_for_movement(setup):
    eng, rec = setup
    eng.handle(on(72, 127))  # C5 fire
    assert rec.log == [("down", "KEY_RIGHTCTRL")]


def test_shared_key_held_until_last_release(setup):
    eng, rec = setup
    eng.handle(on(72))  # C5 fire
    eng.handle(pedal(127))  # sustain pedal fire
    eng.handle(off(72))
    assert rec.log == [("down", "KEY_RIGHTCTRL")]
    eng.handle(pedal(0))
    assert rec.log == [("down", "KEY_RIGHTCTRL"), ("up", "KEY_RIGHTCTRL")]


def test_pedal_repeats_ignored(setup):
    eng, rec = setup
    for v in (70, 90, 127):
        eng.handle(pedal(v))
    assert rec.log == [("down", "KEY_RIGHTCTRL")]


def test_unmapped_and_stray_release(setup):
    eng, rec = setup
    assert eng.handle(on(100)) is None
    eng.handle(off(100))
    eng.handle(off(48))
    eng.handle(pedal(127, control=1))
    assert rec.log == []


def test_release_all(setup):
    eng, rec = setup
    eng.handle(on(48))
    eng.handle(pedal(127))
    eng.release_all()
    assert sorted(rec.log[2:]) == [("up", "KEY_LEFT"), ("up", "KEY_RIGHTCTRL")]


def test_custom_layout_raw_key_and_override():
    layout = parse_layout({
        "keys": {"C4": "KEY_F12", "D4": "fire"},
        "actions": {"fire": "KEY_LEFTCTRL"},
    })
    rec = Recorder()
    eng = Engine(layout, rec)
    eng.handle(on(60))
    eng.handle(on(62))
    assert rec.log == [("down", "KEY_F12"), ("down", "KEY_LEFTCTRL")]


def test_unknown_action_rejected():
    with pytest.raises(KeyError):
        parse_layout({"keys": {"C4": "jump"}})
