#!/usr/bin/env python3
"""Print the markers doom_ray sends over USB MIDI (channel 16 CC: value = controller << 7 | data).

    0x201..0x214  the call depth probe came back from that many nested calls
    0x100         __cc_init done          0x300 + ok   the C self-test (1 = as in the simulator)
    0x400 + n     frame n drawn (mod 256)

Usage: uv run python tools/trace_listen.py [PORT-SUBSTRING]
"""
import sys
import time

import mido

NAMES = {0x100: "__cc_init done"}


def describe(v):
    if 0x200 < v < 0x300:
        return "call depth %d ok" % (v - 0x200)
    if v in (0x300, 0x301):
        return "self-test %s" % ("OK" if v == 0x301 else "DIFFERENT")
    if 0x400 <= v < 0x500:
        return "frame %d" % (v - 0x400)
    return NAMES.get(v, "")


def main():
    want = sys.argv[1] if len(sys.argv) > 1 else ""
    while True:
        names = [n for n in mido.get_input_names() if "Through" not in n and want.lower() in n.lower()]
        if names:
            break
        print("waiting for the piano's MIDI port...", flush=True)
        time.sleep(1)
    print("listening on", names[0], flush=True)
    t0 = time.time()
    with mido.open_input(names[0]) as port:
        for msg in port:
            if msg.type == "control_change" and msg.channel == 15:
                v = msg.control << 7 | msg.value
                print("%8.3f  %#06x  %s" % (time.time() - t0, v, describe(v)), flush=True)


if __name__ == "__main__":
    main()
