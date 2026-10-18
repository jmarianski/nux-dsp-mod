"""Layout: which note or pedal triggers which action, and which keys an action presses."""

import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from pianodoom.notes import parse_note

# Doom's stock controls (vanilla, Chocolate Doom, Crispy Doom, PrBoom+).
DEFAULT_ACTIONS: dict[str, list[str]] = {
    "forward": ["KEY_UP"],
    "backward": ["KEY_DOWN"],
    "turn_left": ["KEY_LEFT"],
    "turn_right": ["KEY_RIGHT"],
    "strafe_left": ["KEY_COMMA"],
    "strafe_right": ["KEY_DOT"],
    "strafe": ["KEY_RIGHTALT"],
    "fire": ["KEY_RIGHTCTRL"],
    "use": ["KEY_SPACE"],
    "run": ["KEY_RIGHTSHIFT"],
    "automap": ["KEY_TAB"],
    "menu": ["KEY_ESC"],
    "enter": ["KEY_ENTER"],
    "yes": ["KEY_Y"],
    "no": ["KEY_N"],
    "pause": ["KEY_PAUSE"],
    "quicksave": ["KEY_F6"],
    "quickload": ["KEY_F9"],
    **{f"weapon{i}": [f"KEY_{i}"] for i in range(1, 8)},
}


@dataclass
class Layout:
    notes: dict[int, str] = field(default_factory=dict)
    cc: dict[int, str] = field(default_factory=dict)
    actions: dict[str, list[str]] = field(default_factory=lambda: dict(DEFAULT_ACTIONS))
    port: str = ""
    forte_velocity: int = 0
    forte_action: str = "run"
    forte_applies_to: set[str] = field(default_factory=set)

    def keys_for(self, action: str) -> list[str]:
        """An action name, or a raw evdev key name such as 'KEY_F12'."""
        if action in self.actions:
            return self.actions[action]
        if action.startswith(("KEY_", "BTN_")):
            return [action]
        raise KeyError(f"unknown action {action!r}")

    def all_keys(self) -> set[str]:
        used = list(self.notes.values()) + list(self.cc.values())
        if self.forte_velocity:
            used.append(self.forte_action)
        return {k for a in used for k in self.keys_for(a)}


def default_config_text() -> str:
    return resources.files("pianodoom").joinpath("default.toml").read_text()


def load_layout(path: Path | None = None) -> Layout:
    text = path.read_text() if path else default_config_text()
    return parse_layout(tomllib.loads(text))


def parse_layout(data: dict) -> Layout:
    settings = data.get("settings", {})
    layout = Layout(
        port=settings.get("port", ""),
        forte_velocity=int(settings.get("forte_velocity", 0)),
        forte_action=settings.get("forte_action", "run"),
        forte_applies_to=set(settings.get("forte_applies_to", [])),
    )
    for action, keys in data.get("actions", {}).items():
        layout.actions[action] = [keys] if isinstance(keys, str) else list(keys)
    for note, action in data.get("keys", {}).items():
        layout.notes[parse_note(note)] = action
    for cc, action in data.get("cc", {}).items():
        layout.cc[int(cc)] = action
    layout.all_keys()  # fail early on unknown actions
    return layout
