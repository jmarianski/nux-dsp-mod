"""Turns MIDI messages into key presses and releases.

Several notes may hold the same key (C5 and the sustain pedal both fire):
the key goes up only when the last of them is released.
"""

from collections import Counter
from typing import Protocol

from pianodoom.mapping import Layout


class KeySink(Protocol):
    def press(self, key: str) -> None: ...
    def release(self, key: str) -> None: ...


class Engine:
    def __init__(self, layout: Layout, sink: KeySink):
        self.layout = layout
        self.sink = sink
        self._held: Counter[str] = Counter()
        self._sources: dict[tuple[str, int], list[str]] = {}

    def handle(self, msg) -> str | None:
        """Takes a mido message; returns the action it triggered, if any."""
        if msg.type == "note_on" and msg.velocity > 0:
            return self._down(("note", msg.note), self.layout.notes.get(msg.note), msg.velocity)
        if msg.type == "note_off" or msg.type == "note_on":
            self._up(("note", msg.note))
        elif msg.type == "control_change" and msg.control in self.layout.cc:
            if msg.value >= 64:
                return self._down(("cc", msg.control), self.layout.cc[msg.control], 127)
            self._up(("cc", msg.control))
        return None

    def release_all(self) -> None:
        for source in list(self._sources):
            self._up(source)

    def _down(self, source, action: str | None, velocity: int) -> str | None:
        if action is None or source in self._sources:
            return None
        keys = list(self.layout.keys_for(action))
        lay = self.layout
        if lay.forte_velocity and velocity >= lay.forte_velocity and action in lay.forte_applies_to:
            keys += lay.keys_for(lay.forte_action)
        self._sources[source] = keys
        for key in keys:
            self._held[key] += 1
            if self._held[key] == 1:
                self.sink.press(key)
        return action

    def _up(self, source) -> None:
        for key in self._sources.pop(source, []):
            self._held[key] -= 1
            if self._held[key] == 0:
                del self._held[key]
                self.sink.release(key)
