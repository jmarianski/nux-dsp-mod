# Adding another model or firmware version

NUX pianos of the same family (NEK-100, NEK-110, …) use the same Dream DSP and, most likely, a very
similar firmware. Each official firmware file the patcher supports is one **target**:

```
targets/nek100-dsp-1.0.7/
    target.map        addresses + our descriptions, SHA-256 of the official file, default patches
    patches/*.patch   the patches, with hook addresses for this file
web/targets/nek100-dsp-1.0.7.js   generated data for the web page (our words only)
```

The web page and the CLI pick the target by the SHA-256 of the file the user gives them, so adding a
model never changes how the existing ones behave.

## 1. Check the file

```sh
python3 -m nuxdsp verify NEK110_DSP_Vx.y.z.bin
```

`container ok` means it is the same container format (magic `rd`, length, checksum) and the tools
can work with it. Write down the SHA-256.

## 2. Draft the target with `port`

```sh
python3 -m nuxdsp port NEK100_DSP_V1.0.7.bin NEK110_DSP_Vx.y.z.bin targets/nek110-dsp-x.y.z
```

`port` looks for the code of every function, label, pool and hook of the NEK-100 target in the other
file. It compares the instruction words and ignores the literal words (addresses, constants), which
change between builds. A window grows from 12 instructions until it matches exactly one place.
RAM variables follow from the literals of the matching code. The draft has:

- a `target.map` with the new SHA-256, every entry it could find marked `(ported)`, and `# ???????`
  for the ones it could not;
- `patches/` with hook addresses moved and `expect` words taken from the new file, or `; TODO port:`
  where a hook site was not found.

Both firmware files stay on your machine. Only addresses and the few `expect` words end up in the
draft, as in any target.

## 3. Review it (the important part)

Generate listings of both files and compare them at every entry and hook:

```sh
python3 -m nuxdsp --target targets/nek110-dsp-x.y.z disasm NEK110_DSP_Vx.y.z.bin nek110.s
```

- **code / ramdata / glyphs**: `port` leaves the old values commented out. Find the new ones: code ranges
  and the initialised-data block from the listing, the glyph table from its 8-word entries.
- **pools** must be code that nothing calls, jumps into or points to. A function unused on the NEK-100
  can be used on another model, so check again, over the whole file.
- **hooks**: the replaced words must do the same thing as on the NEK-100 (a hook may land in code that
  looks the same and does something else). Read the patch comments: they say what each hook expects.
- **variables** with no vote (`# var ??????? …`) need to be found by hand, or left out if no patch uses
  them.
- fill in `firmware`, `device`, `input`, `output`, then remove the DRAFT notice.

`python3 -m nuxdsp --target targets/nek110-dsp-x.y.z build NEK110_DSP_Vx.y.z.bin test.bin` must
build without errors. Then test on the instrument, one feature at a time, with `version_tag` on, and
mark what you confirmed with `(C)` in the map.

## 4. Publish it

```sh
python3 -m nuxdsp web NEK110_DSP_Vx.y.z.bin      # writes web/targets/nek110-dsp-x.y.z.js, updates index.html
python3 -m unittest discover -s tests -t .
```

Open a pull request with the target directory and the generated `web/targets/*.js`, and say which
features you tested on which instrument. Never commit the firmware files, listings (`.s`) or builds.
