"""pianodoom: play Doom on a MIDI piano."""

import argparse
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from pianodoom.engine import Engine
from pianodoom.mapping import default_config_text, load_layout
from pianodoom.notes import note_name
from pianodoom.output import PrintSink, UInputSink

IWADS = [
    "/usr/share/games/doom/freedoom1.wad",
    "/usr/share/games/doom/freedoom2.wad",
    "/usr/share/games/doom/doom1.wad",
    "/usr/share/games/doom/doom.wad",
    "/usr/share/games/doom/doom2.wad",
]
PORTS = ["chocolate-doom", "crispy-doom", "prboom-plus", "gzdoom"]


def find_port(wanted: str, wait: bool) -> str:
    import mido

    announced = False
    while True:
        names = [n for n in mido.get_input_names() if "Through" not in n]
        matches = [n for n in names if wanted.lower() in n.lower()]
        if matches:
            return matches[0]
        if not wait:
            sys.exit(f"no MIDI input matching {wanted!r}; available: {names or 'none'}")
        if not announced:
            print(f"waiting for a MIDI input{f' matching {wanted!r}' if wanted else ''}… (connect the piano)")
            announced = True
        time.sleep(1)


def bridge(args, stop: threading.Event) -> None:
    import mido

    layout = load_layout(args.config)
    sink = PrintSink() if args.dry_run else UInputSink(layout.all_keys())
    engine = Engine(layout, sink)
    name = find_port(args.port if args.port is not None else layout.port, wait=True)
    print(f"listening on: {name}")
    try:
        with mido.open_input(name) as inport:
            while not stop.is_set():
                for msg in inport.iter_pending():
                    action = engine.handle(msg)
                    if action and args.verbose:
                        label = note_name(msg.note) if msg.type == "note_on" else f"CC{msg.control}"
                        print(f"{label:>5} → {action}", flush=True)
                time.sleep(0.001)
    finally:
        engine.release_all()
        if hasattr(sink, "close"):
            sink.close()


def cmd_ports(args) -> int:
    import mido

    for name in mido.get_input_names():
        print(name)
    return 0


def cmd_monitor(args) -> int:
    import mido

    name = find_port(args.port or "", wait=True)
    print(f"listening on: {name} (Ctrl+C to stop)")
    with mido.open_input(name) as inport:
        for msg in inport:
            if msg.type in ("note_on", "note_off"):
                print(f"{msg.type:8} {note_name(msg.note):>4} (MIDI {msg.note:3}) velocity {msg.velocity}")
            elif msg.type != "clock":
                print(msg)
    return 0


def cmd_run(args) -> int:
    stop = threading.Event()
    try:
        bridge(args, stop)
    except KeyboardInterrupt:
        pass
    return 0


def doom_command(extra: list[str]) -> list[str]:
    if extra:
        return extra
    exe = next((p for p in PORTS if shutil.which(p)), None)
    if not exe:
        sys.exit(
            "no Doom found. Install one, e.g.: sudo apt install chocolate-doom freedoom\n"
            "or pass your own command: pianodoom play -- gzdoom -iwad doom2.wad"
        )
    iwad = next((w for w in IWADS if Path(w).exists()), None)
    return [exe] + (["-iwad", iwad] if iwad else [])


def cmd_play(args) -> int:
    cmd = doom_command(args.doom)
    stop = threading.Event()
    errors: list[BaseException] = []

    def worker():
        try:
            bridge(args, stop)
        except BaseException as e:  # SystemExit from a missing port or permission
            errors.append(e)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    time.sleep(0.5)  # let the virtual keyboard appear before the game starts
    if errors:
        raise errors[0]
    print("starting:", " ".join(cmd))
    try:
        code = subprocess.call(cmd)
    except KeyboardInterrupt:
        code = 130
    stop.set()
    t.join(timeout=2)
    return code


def cmd_layout(args) -> int:
    if args.toml:
        print(default_config_text(), end="")
        return 0
    layout = load_layout(args.config)
    for n in sorted(layout.notes):
        print(f"{note_name(n):>4}  (MIDI {n:3})  {layout.notes[n]}")
    for c in sorted(layout.cc):
        print(f"CC{c:<3} (pedal)      {layout.cc[c]}")
    if layout.forte_velocity:
        print(f"velocity ≥ {layout.forte_velocity} on movement keys also holds {layout.forte_action!r}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pianodoom", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--config", type=Path, help="layout file (TOML); default: built-in")
        sp.add_argument("--port", help="part of the MIDI input name (overrides the layout)")
        sp.add_argument("--dry-run", action="store_true", help="print keys instead of pressing them")
        sp.add_argument("-v", "--verbose", action="store_true", help="print each triggered action")

    sub.add_parser("ports", help="list MIDI inputs").set_defaults(func=cmd_ports)

    sp = sub.add_parser("monitor", help="print what the piano sends (to find note names)")
    sp.add_argument("--port")
    sp.set_defaults(func=cmd_monitor)

    sp = sub.add_parser("run", help="only the bridge: piano → virtual keyboard")
    common(sp)
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("play", help="bridge + start Doom (default: chocolate-doom + freedoom)")
    common(sp)
    sp.add_argument("doom", nargs=argparse.REMAINDER, help="own Doom command after --")
    sp.set_defaults(func=cmd_play)

    sp = sub.add_parser("layout", help="show the key layout")
    sp.add_argument("--config", type=Path)
    sp.add_argument("--toml", action="store_true", help="print the default layout file to copy")
    sp.set_defaults(func=cmd_layout)

    args = p.parse_args(argv)
    if getattr(args, "doom", None) and args.doom[0] == "--":
        args.doom = args.doom[1:]
    return args.func(args)
