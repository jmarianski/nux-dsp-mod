"""Where key presses go: a virtual keyboard (uinput), or the terminal."""

import sys


class PrintSink:
    def press(self, key: str) -> None:
        print(f"  ↓ {key}", flush=True)

    def release(self, key: str) -> None:
        print(f"  ↑ {key}", flush=True)


class UInputSink:
    """A virtual keyboard the game sees like a real one (Linux, /dev/uinput)."""

    def __init__(self, keys: set[str]):
        try:
            from evdev import UInput, ecodes
        except ImportError:
            sys.exit("evdev is missing; the virtual keyboard works on Linux only (use --dry-run elsewhere)")
        self._ecodes = ecodes
        codes = [self._code(k) for k in sorted(keys)]
        try:
            self._ui = UInput({ecodes.EV_KEY: codes}, name="pianodoom virtual keyboard")
        except PermissionError:
            sys.exit(
                "no permission to /dev/uinput. Install udev/70-uinput.rules "
                "(see README) or run once with sudo to check that it works."
            )

    def _code(self, key: str) -> int:
        try:
            return getattr(self._ecodes, key)
        except AttributeError:
            raise SystemExit(f"unknown evdev key name: {key}") from None

    def _emit(self, key: str, value: int) -> None:
        self._ui.write(self._ecodes.EV_KEY, self._code(key), value)
        self._ui.syn()

    def press(self, key: str) -> None:
        self._emit(key, 1)

    def release(self, key: str) -> None:
        self._emit(key, 0)

    def close(self) -> None:
        self._ui.close()
