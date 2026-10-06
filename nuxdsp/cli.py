"""Command line interface: python -m nuxdsp COMMAND ..."""
import argparse
import sys

from . import asm, container, disasm, extract, fwmap, instrument, patcher, soundbank


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
        print("instrument packs (--voice SLOT=NAME):")
        for n in packs:
            p = instrument.load(instrument.bundled(n))
            h = p.header
            print("  %-20s %s / %s, %d zones; %s, %s, %s" % (n, p.name, h.get("name_pl", ""), len(p.pcm),
                                                             h.get("author", "?"), h.get("source", "?"), h.get("license", "?")))


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
    """SLOT=PACK[,name[,Polish name]] -> [(slot, pack, name, name_pl)]; PACK: a .nxi file or a bundled pack's name."""
    out = []
    for it in items or []:
        slot, _, rest = it.partition("=")
        path, *names = rest.split(",")
        if not slot.isdigit() or not 1 <= int(slot) <= 500 or not path:
            raise ValueError("--voice wants SLOT=PACK[,name[,Polish name]] with SLOT 1..500, got %r" % it)
        p = instrument.load(path if path.endswith(".nxi") else instrument.bundled(path))
        name = names[0] if names and names[0] else p.name
        name_pl = names[1] if len(names) > 1 else (p.header.get("name_pl", "") if not names else "")
        out.append((int(slot), p, name, name_pl))
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
            print("sound %3d  %s%s (%d zones)" % (s, n, " / " + npl if npl else "", len(p.pcm)))
        write(a.sbank_out, bank)
        print("wrote %s, sha256 %s" % (a.sbank_out, container.sha256(bank)))
    write(a.out, out)
    print("wrote %s, sha256 %s" % (a.out, container.sha256(out)))


def cmd_pack(a):
    p = instrument.make(a.samples, a.name, a.name_pl, a.cents, author=a.author, source=a.source, license=a.license)
    write(a.out, p.to_bytes())
    print("wrote %s: %s, %d zones (keys %d..%d)" % (a.out, p.name, len(p.pcm), p.roots[0], p.roots[-1]))


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
    s.add_argument("--voice", action="append", metavar="SLOT=PACK[,NAME[,NAME_PL]]",
                   help="put an instrument pack (.nxi file or bundled pack name, see `list`) on sound SLOT (1..500); "
                        "repeatable, at most 4; needs --sbank and --sbank-out")
    s.add_argument("--sbank", help="the official soundbank file (e.g. NEK100_SBANK_V1.0.4.bin)")
    s.add_argument("--sbank-out", help="where to write the soundbank with the instruments")
    s = sub.add_parser("pack", help="make an instrument pack (.nxi) from samples")
    s.add_argument("samples", help="directory of r<midi>.wav (mono 16-bit 44.1 kHz) or r<midi>.raw, each at its root key")
    s.add_argument("out")
    s.add_argument("--name", required=True, help="at most %d characters" % instrument.MAX_NAME)
    s.add_argument("--name-pl", default="", help="Polish name (optional)")
    s.add_argument("--cents", type=float, default=0, help="tuning of the whole instrument")
    s.add_argument("--author", default="")
    s.add_argument("--source", default="")
    s.add_argument("--license", default="")
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
    except (patcher.PatchError, asm.AsmError, soundbank.BankError, instrument.PackError, ValueError, OSError) as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
