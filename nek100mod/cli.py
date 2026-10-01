"""Command line interface: python -m nek100mod COMMAND ..."""
import argparse
import os
import sys

from . import asm, container, disasm, extract, fwmap, patcher


def read(path):
    with open(path, "rb") as f:
        return f.read()


def write(path, data):
    with open(path, "wb" if isinstance(data, bytes) else "w") as f:
        f.write(data)


def load_checked(path, m, force=False):
    img = read(path)
    sha = container.sha256(img)
    if sha != m.sha256:
        msg = "%s is not the official %s (SHA-256 %s)" % (path, m.firmware, sha[:16])
        if not force:
            raise SystemExit("error: " + msg)
        print("warning: " + msg, file=sys.stderr)
    return img


def cmd_verify(a, m):
    img = read(a.firmware)
    probs = container.validate(img)
    sha = container.sha256(img)
    print("sha256    %s" % sha)
    print("container %s" % ("ok" if not probs else "; ".join(probs)))
    print("official  %s" % ("yes, " + m.firmware if sha == m.sha256 else "no"))
    return 0 if not probs else 1


def cmd_disasm(a, m):
    img = load_checked(a.firmware, m, a.force)
    write(a.out, disasm.Listing(img, m).render())
    print("wrote %s (local use only, do not redistribute)" % a.out)


def cmd_asm(a, m):
    img = load_checked(a.firmware, m, a.force)
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


def cmd_build(a, m):
    img = load_checked(a.firmware, m)
    names = a.patch or patcher.available()
    pats = patcher.resolve_patches(names)
    out, report = patcher.build(img, m, pats, patcher.parse_params(a.param))
    for line in report:
        print(line)
    write(a.out, out)
    print("wrote %s, sha256 %s" % (a.out, container.sha256(out)))


def cmd_list(a, m):
    for n in patcher.available():
        p = patcher.load(n)
        print("%-20s %s" % (n, p.title))
        for prm in p.params:
            print("%22s%s=%d (%d..%d) %s" % ("", prm.name, prm.default, prm.lo, prm.hi, prm.desc))


def cmd_extract(a, m):
    orig = load_checked(a.firmware, m)
    mod = read(a.modified)
    write(a.out, extract.extract(orig, mod, m, a.name))
    print("wrote %s — review it, then name and describe it" % a.out)


def cmd_web(a, m):
    from . import web
    img = load_checked(a.firmware, m)
    write(a.out, web.export(img, m, a.patch or patcher.available()))
    print("wrote %s" % a.out)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="nek100mod", description="NUX NEK-100 DSP firmware patcher")
    ap.add_argument("--map", help="firmware map (default: map/nek100_dsp_v1.0.7.map)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("verify", help="check a firmware file (container, checksum, official SHA-256)")
    s.add_argument("firmware")
    s = sub.add_parser("list", help="list available patches and their parameters")
    s = sub.add_parser("build", help="apply patches to the official firmware")
    s.add_argument("firmware")
    s.add_argument("out")
    s.add_argument("-p", "--patch", action="append", help="patch name or file (repeatable; default: all)")
    s.add_argument("--param", action="append", help="NAME=VALUE")
    s = sub.add_parser("disasm", help="annotated listing of your firmware (for local use)")
    s.add_argument("firmware")
    s.add_argument("out")
    s.add_argument("--force", action="store_true", help="accept a non-official input")
    s = sub.add_parser("asm", help="assemble a (modified) listing over the firmware image")
    s.add_argument("firmware")
    s.add_argument("source")
    s.add_argument("out")
    s.add_argument("--force", action="store_true", help="accept a non-official input")
    s.add_argument("--map-symbols", action="store_true", help="predefine map symbols (for snippets)")
    s = sub.add_parser("extract", help="turn a modified image into a .patch skeleton")
    s.add_argument("firmware")
    s.add_argument("modified")
    s.add_argument("out")
    s.add_argument("--name", default="my_patch")
    s = sub.add_parser("web", help="export the offline single-file web patcher")
    s.add_argument("firmware", help="official firmware (only used to compute the patch words)")
    s.add_argument("out")
    s.add_argument("-p", "--patch", action="append")

    a = ap.parse_args(argv)
    m = fwmap.load(a.map)
    try:
        return globals()["cmd_" + a.cmd](a, m) or 0
    except (patcher.PatchError, asm.AsmError, ValueError) as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
