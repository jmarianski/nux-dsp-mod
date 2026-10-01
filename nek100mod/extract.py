"""Turn an experiment (modified firmware) back into a shareable .patch with only your changes."""
from . import container, disasm, isa


def changed_ranges(a, b, lo, hi):
    out, i = [], lo
    while i < hi:
        if a[i] != b[i]:
            j = i
            while j < hi and a[j] != b[j]:
                j += 1
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


def align(ranges, starts):
    """Extend ranges to whole instructions of the original listing and merge neighbours."""
    st = sorted(starts)
    import bisect
    res = []
    for s, e in ranges:
        i = bisect.bisect_right(st, s) - 1
        s2 = st[i] if i >= 0 else s
        j = bisect.bisect_left(st, e)
        e2 = st[j] if j < len(st) else e
        if res and s2 <= res[-1][1]:
            res[-1] = (res[-1][0], max(res[-1][1], e2))
        else:
            res.append((s2, e2))
    return res


def decode_block(w, s, e, labels, fwmap):
    lines, a = [], s
    while a < e:
        x = w[a]
        two = isa.is_two_words(x) and a + 1 < e
        lit = w[a + 1] if two else None
        if a in labels:
            lines.append("%s:" % labels[a])
        text, h = disasm.format_insn(a, x, lit, lambda t: labels.get(t, "%#x" % t), fwmap.var_name)
        lines.append("    %s%s" % (text, ("    ; " + h) if h else ""))
        a += 2 if two else 1
    return lines


def extract(orig_img, mod_img, fwmap, name="my_patch"):
    a, b = container.words(orig_img), container.words(mod_img)
    if len(a) != len(b):
        raise ValueError("images differ in size")
    starts = {x for x, _, _ in disasm.iter_insns(a, fwmap.code)}
    code_r, data_r = [], []
    for s, e in fwmap.code:
        code_r += changed_ranges(a, b, s, e)
    lo, hi = fwmap.ramdata
    data_r = changed_ranges(a, b, lo, hi)
    code_r = align(code_r, starts)
    in_pool = [r for r in code_r if any(ps <= r[0] < pe for ps, pe in fwmap.pools)]
    hooks = [r for r in code_r if r not in in_pool]
    labels = {e.addr: e.name for e in fwmap.by_kind("func", "label")}
    labels.update({s: "blk_%05x" % s for s, _ in in_pool})
    # every target inside a moved block gets a label, so the extracted patch is relocatable
    for s, e in code_r:
        for x_a, x, lit in disasm.iter_insns(b, [(s, e)]):
            d = isa.decode(x, lit)
            t = disasm.target_of(x_a, *d) if d else None
            if t is not None and any(ps <= t < pe for ps, pe in in_pool):
                labels.setdefault(t, "blk_%05x" % t)
    out = [".patch %s" % name, '.title "describe what it does"', ""]
    for s, e in hooks:
        out.append(".hook %#07x expect %s" % (s, " ".join("%#06x" % v for v in a[s:e])))
        out += decode_block(b, s, e, labels, fwmap)
        out.append(".end")
    for s, e in data_r:
        txt = "".join(chr(v) for v in b[s:e])
        out.append("; RAM data %#06x (file word %#07x): %r" % (s - lo, s, txt))
        out.append(".hook %#07x expect %s" % (s, " ".join("%#06x" % v for v in a[s:e])))
        out.append("    .dw   " + ", ".join("%#06x" % v for v in b[s:e]))
        out.append(".end")
    if in_pool:
        out += ["", ".code"]
        for s, e in in_pool:
            out += decode_block(b, s, e, labels, fwmap)
        out.append(".end")
    return "\n".join(out) + "\n"
