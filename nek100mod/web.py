"""Export the offline, single-file web patcher (web/nek100-patcher.html).

The page contains only the words *we* write (our code, our hook instructions, our string
characters), never original firmware words: the user's file is identified by its SHA-256.
Parameters are exported as per-value word tables computed by the real builder, so the page
cannot drift from the CLI.
"""
import html
import json
import os

from . import container, patcher

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web_template.html")


def patch_words(image, fwmap, p, params=None):
    owner = {}
    out, _ = patcher.build(image, fwmap, [p], params, owner_out=owner)
    new = container.words(out)
    return {a: new[a] for a in sorted(owner)}  # the checksum word is recomputed in JS


def export_data(image, fwmap, names):
    data = {"firmware": fwmap.firmware, "sha256": fwmap.sha256, "words": len(container.words(image)),
            "patches": []}
    for n in names:
        p = patcher.load(n)
        base = patch_words(image, fwmap, p)
        entry = {"name": p.name, "title": p.title, "words": base, "params": [],
                 "default": p.name in patcher.DEFAULT_ORDER}
        seen = set()
        for prm in p.params:
            values = {}
            for v in range(prm.lo, prm.hi + 1):
                w = patch_words(image, fwmap, p, {prm.name: v})
                if set(w) - set(base) or set(base) - set(w):
                    raise patcher.PatchError("%s: %s changes which words are written" % (p.name, prm.name))
                values[v] = {a: x for a, x in w.items() if x != base[a]}
            touched = {a for d in values.values() for a in d}
            if touched & seen:
                raise patcher.PatchError("%s: parameters share words, not exportable" % p.name)
            seen |= touched
            entry["params"].append({"name": prm.name, "default": prm.default, "lo": prm.lo, "hi": prm.hi,
                                    "desc": prm.desc, "values": values})
        data["patches"].append(entry)
    return data


def export(image, fwmap, names):
    data = export_data(image, fwmap, names)
    with open(TEMPLATE, encoding="utf-8") as f:
        page = f.read()
    return (page.replace("__DATA__", json.dumps(data, separators=(",", ":")))
                .replace("__FIRMWARE__", html.escape(fwmap.firmware)))
