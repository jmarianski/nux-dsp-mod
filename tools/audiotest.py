#!/usr/bin/env python3
"""Sound tests from the PC, straight into the piano's synthesizer over USB MIDI (no flashing).

    audiotest.py drums            a kick / snare / hi-hat bar on channel 10 in a few setups, one after another
    audiotest.py music [SONG]     a song (default wad.SONG) from the same stream the game plays, timed by the PC
    audiotest.py off              all notes off on every channel

Usage: uv run python tools/audiotest.py drums
"""
import sys
import time

import mido

import wad

DRUM_SETUPS = [
    ("A: channel 10, program 0 (what the game sends now)", []),
    ("B: bank 120 (GM2 rhythm) + program 0", [("control_change", 0, 120), ("control_change", 32, 0), ("program_change", 0)]),
    ("C: bank 127 + program 0", [("control_change", 0, 127), ("control_change", 32, 0), ("program_change", 0)]),
    ("D: program 16 (the Rock style's drum voice)", [("control_change", 0, 0), ("control_change", 32, 0), ("program_change", 16)]),
    ("E: bank 128/MSB 1 + program 0", [("control_change", 0, 1), ("control_change", 32, 0), ("program_change", 0)]),
]


def port():
    names = [n for n in mido.get_output_names() if "nek" in n.lower()]
    if not names:
        sys.exit("no NEK-100 MIDI port")
    return mido.open_output(names[0])


def send(out, kind, ch, a=0, b=0):
    if kind == "control_change":
        out.send(mido.Message(kind, channel=ch, control=a, value=b))
    elif kind == "program_change":
        out.send(mido.Message(kind, channel=ch, program=a))


def drums(out):
    for title, setup in DRUM_SETUPS:
        print(title, flush=True)
        for m in setup:
            send(out, m[0], 9, *m[1:])
        for beat in range(8):
            notes = [42] + ([36] if beat % 4 == 0 else [38] if beat % 4 == 2 else [])
            for n in notes:
                out.send(mido.Message("note_on", channel=9, note=n, velocity=100))
            time.sleep(0.25)
            for n in notes:
                out.send(mido.Message("note_off", channel=9, note=n))
        time.sleep(1.0)


QUIET = 0.2   # the song's channel volumes scaled down: the game plays at 40% of them at full VOL, this is half that


def music(out, song):
    words = wad.mus_stream(wad.Wad().lump(song))
    for ch in range(4, 16):                     # as music.c's mu_restart: MIDI's default 100, scaled
        out.send(mido.Message("control_change", channel=ch, control=7, value=round(100 * QUIET)))
    t = time.time()
    print("playing", song, "- Ctrl+C stops", flush=True)
    i = 0
    while True:
        w0, w1 = words[i], words[i + 1]
        i += 2
        st = w0 & 255
        if st == 255:
            i = 0
            continue
        if st & 0xF0 == 0xB0 and w1 >> 8 == 7:
            w1 = 0x0700 | round((w1 & 127) * QUIET)
        if st:
            out.send(mido.Message.from_bytes([st, w1 >> 8, w1 & 255][:2 if st & 0xE0 == 0xC0 else 3]))
        t += (w0 >> 8) / 100
        d = t - time.time()
        if d > 0:
            time.sleep(d)


def off(out):
    for ch in range(16):
        out.send(mido.Message("control_change", channel=ch, control=123, value=0))
        out.send(mido.Message("control_change", channel=ch, control=120, value=0))


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "drums"
    with port() as out:
        try:
            if what == "drums":
                drums(out)
            elif what == "music":
                music(out, sys.argv[2] if len(sys.argv) > 2 else wad.SONG)
            off(out)
        except KeyboardInterrupt:
            off(out)
