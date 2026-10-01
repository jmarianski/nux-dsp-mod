"""Patch files (.patch) and the builder that applies them to an official firmware image.

Patch file syntax (see docs/PATCHING.md):
    .patch NAME
    .title "One line description"
    .param NAME DEFAULT MIN MAX "description"     user-tunable constant, usable in expressions
    .hook ADDR expect W [W...]                     replace exactly these original words at ADDR ...
        instructions                               ... with the same number of words
    .end
    .code                                          new code, placed automatically in a free pool
        label:
        instructions                               labels starting with '.' are local to the patch
    .end
    .string "OLD" "NEW"                            replace a UI string (1 char per word, same length)
"""
import os
import re
import shlex
from dataclasses import dataclass, field

from . import asm, container

PATCH_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "patches")
# Canonical order: also the pool layout order used by the web patcher.
DEFAULT_ORDER = ["boot_preset", "touch_off", "sustain_in_preset", "version_tag"]


class PatchError(Exception):
    pass


@dataclass
class Param:
    name: str
    default: int
    lo: int
    hi: int
    desc: str


@dataclass
class Hook:
    addr: int
    expect: list
    lines: list
    line_no: int


@dataclass
class Patch:
    name: str
    title: str = ""
    params: list = field(default_factory=list)
    hooks: list = field(default_factory=list)
    code: list = field(default_factory=list)
    strings: list = field(default_factory=list)
    path: str = ""


def parse(text, path="<patch>"):
    p, block, cur = None, None, None
    for n, raw in enumerate(text.splitlines(), 1):
        stripped = raw.split(";", 1)[0].strip()
        where = "%s:%d" % (path, n)
        if block:
            if stripped == ".end":
                block = cur = None
                continue
            (cur.lines if block == "hook" else p.code).append(raw)
            continue
        if not stripped:
            continue
        t = split_directive(raw)
        d = t[0]
        if d == ".patch":
            p = Patch(t[1], path=path)
            continue
        if p is None:
            raise PatchError("%s: file must start with .patch NAME" % where)
        if d == ".title":
            p.title = t[1]
        elif d == ".param":
            p.params.append(Param(t[1], int(t[2], 0), int(t[3], 0), int(t[4], 0), t[5] if len(t) > 5 else ""))
        elif d == ".hook":
            if len(t) < 4 or t[2] != "expect":
                raise PatchError("%s: .hook ADDR expect W [W...]" % where)
            cur = Hook(int(t[1], 0), [int(x, 0) for x in t[3:]], [], n)
            p.hooks.append(cur)
            block = "hook"
        elif d == ".code":
            block = "code"
        elif d == ".string":
            if len(t[1]) != len(t[2]):
                raise PatchError("%s: .string OLD and NEW must have the same length" % where)
            p.strings.append((t[1], t[2]))
        else:
            raise PatchError("%s: unknown directive %r" % (where, d))
    if block:
        raise PatchError("%s: missing .end" % path)
    if p is None:
        raise PatchError("%s: empty patch" % path)
    return p


def split_directive(raw):
    lex = shlex.shlex(raw, posix=True)
    lex.commenters = ";"
    lex.whitespace_split = True
    return list(lex)


def load(name_or_path):
    path = name_or_path if os.path.exists(name_or_path) else os.path.join(PATCH_DIR, name_or_path + ".patch")
    with open(path, encoding="utf-8") as f:
        return parse(f.read(), path)


def available():
    names = sorted(f[:-6] for f in os.listdir(PATCH_DIR) if f.endswith(".patch"))
    return [n for n in DEFAULT_ORDER if n in names] + [n for n in names if n not in DEFAULT_ORDER]


def code_size(p):
    return asm.block_size(p.code)


def allocate(patches, fwmap, layout=None):
    """Place each patch's code block in a pool. layout {name: addr} forces positions."""
    layout = dict(layout or {})
    used = [(a, a + code_size(p)) for p in patches if p.name in layout for a in [layout[p.name]]]
    for p in patches:
        n = code_size(p)
        if p.name in layout or n == 0:
            layout.setdefault(p.name, None)
            continue
        for s, e in fwmap.pools:
            a = s
            for us, ue in sorted(used):
                if us < a + n and a < ue:
                    a = max(a, ue)
            if a + n <= e:
                layout[p.name] = a
                used.append((a, a + n))
                break
        else:
            raise PatchError("no free pool space for %s (%d words)" % (p.name, n))
    for p in patches:
        a, n = layout[p.name], code_size(p)
        if n and not any(s <= a and a + n <= e for s, e in fwmap.pools):
            raise PatchError("%s: code at %#x..%#x is outside the pools" % (p.name, a, a + n))
    return layout


def canonical_layout(fwmap):
    """Pool positions of the bundled patches when all are applied, in DEFAULT_ORDER.

    Used for every selection, so a given set of patches always produces the same image
    (CLI and web patcher agree, and unselected patches leave their space untouched).
    """
    return {k: v for k, v in allocate(resolve_patches(available()), fwmap).items() if v is not None}


def find_string(w, fwmap, s):
    lo, hi = fwmap.ramdata
    target = [ord(c) for c in s]
    hits = [i for i in range(lo, hi - len(target)) if w[i:i + len(target)] == target]
    if len(hits) != 1:
        raise PatchError("string %r found %d times (need exactly 1)" % (s, len(hits)))
    return hits[0]


def build(image, fwmap, patches, params=None, layout=None, check_sha=True, owner_out=None):
    """Apply patches to an official image. Returns (new_image, report lines).

    owner_out: optional dict, filled with {word address: patch name} for every word written.
    """
    if check_sha and container.sha256(image) != fwmap.sha256:
        raise PatchError("input is not the official %s (SHA-256 mismatch) — refusing to patch"
                         % fwmap.firmware)
    probs = container.validate(image)
    if probs:
        raise PatchError("input container invalid: " + "; ".join(probs))
    names = [p.name for p in patches]
    if len(set(names)) != len(names):
        raise PatchError("patch listed twice")
    params = dict(params or {})
    syms = fwmap.symbols()
    known_params = {}
    for p in patches:
        for prm in p.params:
            if prm.name in syms or prm.name in known_params:
                raise PatchError("parameter name %r collides" % prm.name)
            v = params.pop(prm.name, prm.default)
            if not prm.lo <= v <= prm.hi:
                raise PatchError("%s must be %d..%d" % (prm.name, prm.lo, prm.hi))
            known_params[prm.name] = v
    if params:
        raise PatchError("unknown parameter(s): %s" % ", ".join(params))
    syms.update(known_params)

    if layout is None:
        bundled = canonical_layout(fwmap)
        layout = {p.name: bundled[p.name] for p in patches
                  if p.name in bundled and os.path.dirname(os.path.abspath(p.path)) == os.path.abspath(PATCH_DIR)}
    place = allocate(patches, fwmap, layout)
    # pass 1 over all code blocks: global labels (so patches can call each other)
    for p in patches:
        if place[p.name] is not None:
            _, labels = asm.assemble(p.code, syms, origin=place[p.name], label_prefix=p.name,
                                     labels_only=True)
            for k, v in labels.items():
                if k in syms:
                    raise PatchError("%s: label %r collides with an existing symbol" % (p.name, k))
                syms[k] = v

    w = container.words(image)
    orig = list(w)
    owner = {} if owner_out is None else owner_out
    report = []

    def put(addr, word, who):
        if addr in owner:
            raise PatchError("%s and %s both modify word %#x" % (owner[addr], who, addr))
        owner[addr] = who
        w[addr] = word

    for p in patches:
        try:
            if place[p.name] is not None:
                words, _ = asm.assemble(p.code, syms, origin=place[p.name], label_prefix=p.name,
                                        predefined_labels=True)
                for a, v in words.items():
                    put(a, v, p.name)
                report.append("%-18s code  %#07x..%#07x (%d words)" % (p.name, place[p.name],
                                                                      place[p.name] + len(words), len(words)))
            for h in p.hooks:
                cur = orig[h.addr:h.addr + len(h.expect)]
                if cur != h.expect:
                    raise PatchError("%s: hook %#x expects %s, firmware has %s"
                                     % (p.name, h.addr, fmt_words(h.expect), fmt_words(cur)))
                words, _ = asm.assemble(h.lines, syms, origin=h.addr, label_prefix=p.name)
                if sorted(words) != list(range(h.addr, h.addr + len(h.expect))):
                    raise PatchError("%s: hook %#x must assemble to exactly %d words"
                                     % (p.name, h.addr, len(h.expect)))
                for a, v in words.items():
                    put(a, v, p.name)
                report.append("%-18s hook  %#07x  %s -> %s" % (p.name, h.addr, fmt_words(h.expect),
                                                               fmt_words([words[a] for a in sorted(words)])))
            for old, new in p.strings:
                at = find_string(orig, fwmap, old)
                for i, c in enumerate(new):
                    if old[i] != c:
                        put(at + i, ord(c), p.name)
                report.append("%-18s text  %r -> %r" % (p.name, old, new))
        except asm.AsmError as e:
            raise PatchError("%s: %s" % (p.name, e))
    out = container.pack(container.fix_checksum(w))
    probs = container.validate(out)
    if probs:
        raise PatchError("internal error, output invalid: " + "; ".join(probs))
    return out, report


def fmt_words(ws):
    return " ".join("%04x" % x for x in ws)


def resolve_patches(names):
    return [load(n) for n in names]


def parse_params(items):
    out = {}
    for it in items or []:
        k, _, v = it.partition("=")
        if not re.fullmatch(r"[A-Za-z_]\w*", k) or not v:
            raise PatchError("parameter must be NAME=VALUE, got %r" % it)
        out[k] = int(v, 0)
    return out
