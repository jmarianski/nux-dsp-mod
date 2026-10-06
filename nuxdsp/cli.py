"""Command line interface: python -m nuxdsp COMMAND ..."""
import argparse
import sys

from . import asm, container, disasm, extract, fwmap, instrument, patcher, sf2, soundbank


def read(path):
    with open(path, "rb") as f:
        return f.read()


def write(path, data):
    with open(path, "wb" if isinstance(data, bytes) else "w") as f:
        f.write(data)


def describe(m):
    return "%s %s" % (m.device, m.firmware)


def load_checked(path, target=None, force=False):
    """-> (image, map). The target comes from --target or from the file's SHA-256."""
    img = read(path)
    sha = container.sha256(img)
    m = fwmap.load(target) if target else fwmap.find(sha)
    if m is not None and sha == m.sha256:
        return img, m
    msg = ("%s is not the official %s (SHA-256 %s)" % (path, describe(m), sha[:16]) if m else
           "%s is not a supported official firmware (SHA-256 %s); see `targets`" % (path, sha[:16]))
    if not force:
        raise SystemExit("error: " + msg)
    if m is None:
        raise SystemExit("error: %s — with --force, also give --target" % msg)
    print("warning: " + msg, file=sys.stderr)
    return img, m


def cmd_targets(a):
    for m in fwmap.all_targets():
        print("%-20s %-14s %-20s %s" % (m.id, m.device, m.firmware, m.input))
        print("%20s sha256 %s" % ("", m.sha256))


def cmd_verify(a):
    img = read(a.firmware)
    probs = container.validate(img)
    sha = container.sha256(img)
    m = fwmap.find(sha)
    print("sha256    %s" % sha)
    print("container %s" % ("ok" if not probs else "; ".join(probs)))
    print("supported %s" % ("yes, %s (target %s)" % (describe(m), m.id) if m else
                            "no — not an official file of a supported firmware"))
    return 0 if not probs else 1


def cmd_list(a):
    targets = [fwmap.load(a.target)] if a.target else fwmap.all_targets()
    for m in targets:
        print("%s — %s" % (m.id, describe(m)))
        for n in patcher.available(m):
            p = patcher.load(n, m)
            print("  %-20s %s%s" % (n, p.title, "" if n in m.defaults else "  [optional]"))
            for prm in p.params:
                print("%24s%s=%d (%d..%d) %s" % ("", prm.name, prm.default, prm.lo, prm.hi, prm.desc))
    packs = instrument.bundled_names()
    if packs:
        print("bundled instruments (--voice SLOT=NAME):")
        for n in packs:
            sf = sf2.load(instrument.bundled(n))
            print("  %-20s %s / %s; %s, %s" % (n, sf.info.get("INAM", n), instrument.bundled_meta(n).get("name_pl", ""),
                                             sf.info.get("IENG", "?"), sf.info.get("ICOP", "?")))


def cmd_instruments(a):
    sf = sf2.load(a.sf2)
    for k in ("INAM", "IENG", "ICOP", "ICMT"):
        if sf.info.get(k):
            print("%s  %s" % (k, sf.info[k]))
    for n, (i, b, p, name) in enumerate(sf.presets):
        try:
            ins = sf.instrument(i, a.velocity)
            loops = sum(1 for z in ins.zones if z.loop)
            desc = "%2d zones, %6.0f kB, %s" % (len(ins.zones), ins.size / 1024,
                                              "looped" if loops == len(ins.zones) else "one-shot" if not loops else
                                              "%d looped" % loops)
        except sf2.SF2Error as e:
            desc = "-- %s" % e
        print("@%-3d bank %3d prog %3d  %-20s %s" % (n, b, p, name, desc))


def cmd_disasm(a):
    img, m = load_checked(a.firmware, a.target, a.force)
    write(a.out, disasm.Listing(img, m).render())
    print("wrote %s (local use only, do not redistribute)" % a.out)


def cmd_asm(a):
    img, m = load_checked(a.firmware, a.target, a.force)
    with open(a.source, encoding="utf-8") as f:
        words, _ = asm.assemble(f, m.symbols() if a.map_symbols else None)
    w = container.words(img)
    changed = 0
    for addr, v in words.items():
        if addr >= len(w) - 1:
            raise SystemExit("error: address %#x outside the image" % addr)
        changed += w[addr] != v
        w[addr] = v
    out = container.pack(container.fix_checksum(w))
    write(a.out, out)
    print("wrote %s: %d words assembled, %d differ from the input, sha256 %s"
          % (a.out, len(words), changed, container.sha256(out)))


def parse_voices(items):
    """SLOT=INSTRUMENT[,name[,Polish name]] -> [(slot, Instrument, name, name_pl)];
    INSTRUMENT: FILE.sf2[@PRESET] or a bundled instrument's name."""
    out = []
    for it in items or []:
        slot, _, rest = it.partition("=")
        spec, *names = rest.split(",")
        if not slot.isdigit() or not 1 <= int(slot) <= 500 or not spec:
            raise ValueError("--voice wants SLOT=INSTRUMENT[,name[,Polish name]] with SLOT 1..500, got %r" % it)
        ins, name_pl = instrument.parse_spec(spec)
        name = names[0] if names and names[0] else ins.name[:15 - len(slot) - 1].strip()
        name_pl = names[1] if len(names) > 1 else (name_pl if not names else "")
        out.append((int(slot), ins, name, name_pl))
    return out


def cmd_build(a):
    img, m = load_checked(a.firmware, a.target)
    voices = parse_voices(a.voice)
    if voices and not (a.sbank and a.sbank_out):
        raise SystemExit("error: --voice needs --sbank (the official soundbank file) and --sbank-out")
    names = list(a.patch or patcher.defaults(m))
    if voices and "custom_voices" not in names:
        names.append("custom_voices")
    pats = patcher.resolve_patches(names, m)
    out, report = patcher.build(img, m, pats, patcher.parse_params(a.param))
    if voices:
        out = soundbank.fill_names(out, m, [(s, n, npl) for s, _, n, npl in voices])
        bank = soundbank.add(read(a.sbank), img, m, [(p, s) for s, p, _, _ in voices])
    print("target    %s (%s)" % (m.id, describe(m)))
    for line in report:
        print(line)
    if voices:
        for s, p, n, npl in voices:
            print("sound %3d  %s%s (%d zones, %.0f kB)" % (s, n, " / " + npl if npl else "", len(p.zones), p.size / 1024))
        write(a.sbank_out, bank)
        print("wrote %s, sha256 %s" % (a.sbank_out, container.sha256(bank)))
    write(a.out, out)
    print("wrote %s, sha256 %s" % (a.out, container.sha256(out)))


def cmd_pack(a):
    info = {"IENG": a.author, "ICOP": a.license, "ICMT": a.comment, "ISFT": "nuxdsp"}
    ins = instrument.make(a.samples, a.name, a.cents, info)
    write(a.out, sf2.write(ins))
    print("wrote %s: %s, %d zones (root keys %s)" % (a.out, ins.name, len(ins.zones),
                                                   " ".join(str(z.root) for z in ins.zones)))


def cmd_extract(a):
    orig, m = load_checked(a.firmware, a.target)
    write(a.out, extract.extract(orig, read(a.modified), m, a.name))
    print("wrote %s — review it, then name and describe it" % a.out)


def cmd_web(a):
    from . import web
    for path in a.firmware:
        img, m = load_checked(path, a.target)
        print("wrote %s" % web.write_target(img, m, a.web_dir))
    print("index lists: %s" % ", ".join(web.update_index(a.web_dir)))
    print("instruments: %s" % ", ".join(web.write_packs(a.web_dir)))


def cmd_port(a):
    from . import port
    old, m = load_checked(a.firmware, a.target)
    for line in port.port(old, read(a.new_firmware), m, a.out_dir):
        print(line)
    print("wrote draft target %s — every entry needs review, see docs/NEW_TARGET.md" % a.out_dir)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="nuxdsp", description="Community patcher for NUX digital piano DSP firmware")
    ap.add_argument("--target", help="target id, directory or .map file (default: detected from the firmware file)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("targets", help="list supported firmware files")
    s = sub.add_parser("verify", help="check a firmware file (container, checksum, supported?)")
    s.add_argument("firmware")
    sub.add_parser("list", help="list the patches of each target and their parameters")
    s = sub.add_parser("build", help="apply patches to an official firmware file")
    s.add_argument("firmware")
    s.add_argument("out")
    s.add_argument("-p", "--patch", action="append", help="patch name or file (repeatable; default: the target's defaults)")
    s.add_argument("--param", action="append", help="NAME=VALUE")
    s.add_argument("--voice", action="append", metavar="SLOT=INSTRUMENT[,NAME[,NAME_PL]]",
                   help="put an instrument (FILE.sf2[@PRESET], see `instruments`, or a bundled one, see `list`) on "
                        "sound SLOT (1..500); repeatable, at most 4; needs --sbank and --sbank-out")
    s.add_argument("--sbank", help="the official soundbank file (e.g. NEK100_SBANK_V1.0.4.bin)")
    s.add_argument("--sbank-out", help="where to write the soundbank with the instruments")
    s = sub.add_parser("instruments", help="list the presets of a SoundFont (.sf2) and what of them can be used")
    s.add_argument("sf2")
    s.add_argument("--velocity", type=int, default=sf2.VELOCITY, help="which velocity layer (default %(default)s)")
    s = sub.add_parser("pack", help="make a SoundFont (.sf2) from samples, one per root key")
    s.add_argument("samples", help="directory of r<midi>.wav (mono 16-bit 44.1 kHz) or r<midi>.raw, each at its root key")
    s.add_argument("out", help="the .sf2 file")
    s.add_argument("--name", required=True)
    s.add_argument("--cents", type=int, default=0, help="tuning of the whole instrument")
    s.add_argument("--author", default="")
    s.add_argument("--license", default="")
    s.add_argument("--comment", default="", help="where the samples come from, ...")
    s = sub.add_parser("disasm", help="annotated listing of your firmware (for local use)")
    s.add_argument("firmware")
    s.add_argument("out")
    s.add_argument("--force", action="store_true", help="accept a non-official input (needs --target)")
    s = sub.add_parser("asm", help="assemble a (modified) listing over the firmware image")
    s.add_argument("firmware")
    s.add_argument("source")
    s.add_argument("out")
    s.add_argument("--force", action="store_true", help="accept a non-official input (needs --target)")
    s.add_argument("--map-symbols", action="store_true", help="predefine map symbols (for snippets)")
    s = sub.add_parser("extract", help="turn a modified image into a .patch skeleton")
    s.add_argument("firmware")
    s.add_argument("modified")
    s.add_argument("out")
    s.add_argument("--name", default="my_patch")
    s = sub.add_parser("port", help="draft a target for another firmware file by matching code signatures")
    s.add_argument("firmware", help="official file of a supported target")
    s.add_argument("new_firmware", help="the other firmware file (e.g. another model or version)")
    s.add_argument("out_dir", help="new target directory, e.g. targets/nek110-dsp-1.0.0")
    s = sub.add_parser("web", help="regenerate web/targets/<id>.js for the given official files")
    s.add_argument("firmware", nargs="+", help="official firmware files (only used to compute the patch words)")
    s.add_argument("--web-dir", default=None, help="default: web/ of this repository")

    a = ap.parse_args(argv)
    if getattr(a, "web_dir", 0) is None:
        from . import web
        a.web_dir = web.WEB_DIR
    try:
        return globals()["cmd_" + a.cmd](a) or 0
    except (patcher.PatchError, asm.AsmError, soundbank.BankError, instrument.PackError, sf2.SF2Error, ValueError, OSError) as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
