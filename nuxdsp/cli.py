"""Command line interface: python -m nuxdsp COMMAND ..."""
import argparse
import sys

from . import asm, container, disasm, extract, fwmap, patcher


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


def cmd_build(a):
    img, m = load_checked(a.firmware, a.target)
    pats = patcher.resolve_patches(a.patch or patcher.defaults(m), m)
    out, report = patcher.build(img, m, pats, patcher.parse_params(a.param))
    print("target    %s (%s)" % (m.id, describe(m)))
    for line in report:
        print(line)
    write(a.out, out)
    print("wrote %s, sha256 %s" % (a.out, container.sha256(out)))


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
    except (patcher.PatchError, asm.AsmError, ValueError, OSError) as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
