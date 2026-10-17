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


def ports():
    try:
        return mido.get_input_names()
    except Exception:                           # rtmidi, while a port comes or goes
        return []


def main():
    want = (sys.argv[1] if len(sys.argv) > 1 else "NEK").lower()
    t0 = time.time()
    while True:                                 # the port goes away with every restart of the piano: reopen it
        names = [n for n in ports() if want in n.lower()]
        if not names:
            time.sleep(0.5)
            continue
        print("%8.3f  listening on %s" % (time.time() - t0, names[0]), flush=True)
        try:
            port = mido.open_input(names[0])
        except Exception as e:
            print("%8.3f  cannot open: %s" % (time.time() - t0, e), flush=True)
            time.sleep(0.5)
            continue
        with port:
            last = time.time()
            while True:
                for msg in port.iter_pending():
                    if msg.type == "control_change" and msg.channel == 15:
                        v = msg.control << 7 | msg.value
                        print("%8.3f  %#06x  %s" % (time.time() - t0, v, describe(v)), flush=True)
                time.sleep(0.005)
                if time.time() - last > 1:
                    last = time.time()
                    if not any(want in n.lower() for n in ports()):
                        print("%8.3f  port gone" % (time.time() - t0), flush=True)
                        break


if __name__ == "__main__":
    main()
