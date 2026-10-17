import pytest

from pianodoom.notes import note_name, parse_note


@pytest.mark.parametrize("name,num", [("C4", 60), ("A0", 21), ("C8", 108), ("F#3", 54), ("Bb2", 46), ("c-1", 0), ("60", 60)])
def test_parse(name, num):
    assert parse_note(name) == num


def test_roundtrip():
    for n in range(128):
        assert parse_note(note_name(n)) == n


@pytest.mark.parametrize("bad", ["H2", "C", "G#9", "C#"])
def test_bad(bad):
    with pytest.raises(ValueError):
        parse_note(bad)
