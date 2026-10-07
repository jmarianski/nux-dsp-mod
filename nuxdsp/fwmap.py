"""Firmware map: our own description of a firmware version (symbols, variables, free space).

Each supported firmware is a *target*: a directory targets/<id>/ with target.map and patches/.

Format, one entry per line, `;` starts a comment that is kept as the entry description:
    firmware NAME sha256 HEX
    device   "Brand Model"        shown by the web patcher and `targets`
    input    FILE.bin             the official file name, as shipped by the vendor
    output   FILE.bin             suggested name of the patched file
    download URL                  official page where users get the firmware file
    defaults NAME [NAME...]       patches applied when none are selected (also the pool layout order)
    optional NAME [NAME...]       further bundled patches, selected explicitly (laid out after defaults)
    code    START END            code range (word addresses, END exclusive)
    ramdata START END            file words copied to RAM address 0 at boot
    pool    START END            free space usable for patch code
    func    ADDR NAME            function entry
    label   ADDR NAME            named location inside a function
    var     ADDR NAME [SIZE]     RAM variable (word address), optional size in words
    glyphs  TABLE BITMAPS COUNT  file word addresses of the glyph/image table and its bitmap data
    soundbank NAME sha256 HEX template VOICE ZONE [loop VOICE ZONE]
                                 the official soundbank file instruments are added to, and the zone
                                 (sound number, zone index) whose settings added instruments copy;
                                 instruments with loops copy the "loop" one when given
"""
import os
import shlex
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
TARGETS_DIR = os.path.join(HERE, "..", "targets")
DEFAULT_TARGET = "nek100-dsp-1.0.7"


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
    id: str = ""
    dir: str = ""
    device: str = ""
    input: str = ""
    output: str = ""
    download: str = ""
    defaults: list = field(default_factory=list)
    optional: list = field(default_factory=list)
    code: list = field(default_factory=list)
    ramdata: tuple = None
    pools: list = field(default_factory=list)
    glyphs: tuple = None
    soundbank: dict = None
    entries: list = field(default_factory=list)

    @property
    def patch_dir(self):
        return os.path.join(self.dir, "patches")

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


def target_ids():
    return sorted(d for d in os.listdir(TARGETS_DIR) if os.path.exists(os.path.join(TARGETS_DIR, d, "target.map")))


def load(path=None):
    """Load a map: a target id, a target directory or a .map file (default: DEFAULT_TARGET)."""
    path = path or DEFAULT_TARGET
    if not os.path.exists(path) and os.path.isdir(os.path.join(TARGETS_DIR, path)):
        path = os.path.join(TARGETS_DIR, path)
    if os.path.isdir(path):
        path = os.path.join(path, "target.map")
    m = FwMap(dir=os.path.dirname(os.path.abspath(path)))
    m.id = os.path.basename(m.dir)
    with open(path, encoding="utf-8") as f:
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
            elif k in ("device", "input", "output", "download"):
                setattr(m, k, " ".join(shlex.split(line)[1:]))
            elif k in ("defaults", "optional"):
                setattr(m, k, t[1:])
            elif k in ("code", "pool"):
                getattr(m, "code" if k == "code" else "pools").append((int(t[1], 16), int(t[2], 16)))
            elif k == "glyphs":
                m.glyphs = (int(t[1], 16), int(t[2], 16), int(t[3], 0))
            elif k == "soundbank":
                m.soundbank = {"name": t[1], "sha256": t[3].lower(), "template": (int(t[5]), int(t[6]))}
                if len(t) > 9 and t[7] == "loop":
                    m.soundbank["template_loop"] = (int(t[8]), int(t[9]))
            elif k == "ramdata":
                m.ramdata = (int(t[1], 16), int(t[2], 16))
            elif k in ("func", "label", "var"):
                size = int(t[3], 0) if len(t) > 3 else 1
                m.entries.append(Entry(k, int(t[1], 16), t[2], size, comment.strip()))
            else:
                raise ValueError("unknown entry %r" % k)
        except (IndexError, ValueError) as e:
            raise ValueError("%s:%d: %s" % (path, n, e))
    names = [e.name for e in m.entries]
    dup = {x for x in names if names.count(x) > 1}
    if dup:
        raise ValueError("duplicate names in map: %s" % ", ".join(sorted(dup)))
    return m


def all_targets():
    return [load(t) for t in target_ids()]


def find(sha256):
    """The target whose official firmware has this SHA-256, or None."""
    return next((m for m in all_targets() if m.sha256 == sha256), None)
