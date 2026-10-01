"""Firmware map: our own description of a firmware version (symbols, variables, free space).

Format, one entry per line, `;` starts a comment that is kept as the entry description:
    firmware NAME sha256 HEX
    code    START END            code range (word addresses, END exclusive)
    ramdata START END            file words copied to RAM address 0 at boot
    pool    START END            free space usable for patch code
    func    ADDR NAME            function entry
    label   ADDR NAME            named location inside a function
    var     ADDR NAME [SIZE]     RAM variable (word address), optional size in words
    glyphs  TABLE BITMAPS COUNT  file word addresses of the glyph/image table and its bitmap data
"""
import os
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MAP = os.path.join(HERE, "..", "map", "nek100_dsp_v1.0.7.map")


@dataclass
class Entry:
    kind: str
    addr: int
    name: str
    size: int = 1
    comment: str = ""


@dataclass
class FwMap:
    firmware: str = ""
    sha256: str = ""
    code: list = field(default_factory=list)
    ramdata: tuple = None
    pools: list = field(default_factory=list)
    glyphs: tuple = None
    entries: list = field(default_factory=list)

    def by_kind(self, *kinds):
        return [e for e in self.entries if e.kind in kinds]

    def symbols(self):
        """name -> address for the assembler (functions, labels, variables)."""
        return {e.name: e.addr for e in self.entries}

    def code_names(self):
        return {e.addr: e for e in self.by_kind("func", "label")}

    def var_name(self, addr):
        """Symbolic name for a RAM address ('touch', 'sustain_cc64+1') or None."""
        for e in self.by_kind("var"):
            if e.addr <= addr < e.addr + e.size:
                return e.name if addr == e.addr else "%s+%d" % (e.name, addr - e.addr)
        return None


def load(path=None):
    m = FwMap()
    with open(path or DEFAULT_MAP, encoding="utf-8") as f:
        lines = f.readlines()
    for n, raw in enumerate(lines, 1):
        line, _, comment = raw.partition(";")
        t = line.split()
        if not t or t[0].startswith("#"):
            continue
        k = t[0]
        try:
            if k == "firmware":
                m.firmware, m.sha256 = t[1], t[3].lower()
            elif k in ("code", "pool"):
                getattr(m, "code" if k == "code" else "pools").append((int(t[1], 16), int(t[2], 16)))
            elif k == "glyphs":
                m.glyphs = (int(t[1], 16), int(t[2], 16), int(t[3], 0))
            elif k == "ramdata":
                m.ramdata = (int(t[1], 16), int(t[2], 16))
            elif k in ("func", "label", "var"):
                size = int(t[3], 0) if len(t) > 3 else 1
                m.entries.append(Entry(k, int(t[1], 16), t[2], size, comment.strip()))
            else:
                raise ValueError("unknown entry %r" % k)
        except (IndexError, ValueError) as e:
            raise ValueError("%s:%d: %s" % (path or DEFAULT_MAP, n, e))
    names = [e.name for e in m.entries]
    dup = {x for x in names if names.count(x) > 1}
    if dup:
        raise ValueError("duplicate names in map: %s" % ", ".join(sorted(dup)))
    return m
