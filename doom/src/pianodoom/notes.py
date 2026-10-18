"""Note names <-> MIDI numbers. Middle C (MIDI 60) is C4."""

import re

_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_OFFSETS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_RE = re.compile(r"^([A-Ga-g])([#b]?)(-?\d+)$")


def parse_note(text: str | int) -> int:
    """'C4' -> 60, 'F#3' -> 54, 'Bb2' -> 46; a plain number is taken as is."""
    if isinstance(text, int) or str(text).isdigit():
        n = int(text)
    else:
        m = _RE.match(str(text).strip())
        if not m:
            raise ValueError(f"not a note: {text!r} (expected e.g. C4, F#3, Bb2 or 60)")
        letter, accidental, octave = m.groups()
        n = _OFFSETS[letter.upper()] + (accidental == "#") - (accidental == "b")
        n += (int(octave) + 1) * 12
    if not 0 <= n <= 127:
        raise ValueError(f"note out of MIDI range: {text!r}")
    return n


def note_name(n: int) -> str:
    return f"{_NAMES[n % 12]}{n // 12 - 1}"
