# Writing patches

A patch is a small text file in `patches/`. It never contains vendor code: only *where* to change
something (with a few `expect` words as a safety check) and *what* to put there (your instructions).

```
.patch my_feature
.title "One line: what it does"
.param LEVEL 100 1 127 "Shown to the user in the CLI and the web page"

.hook 0x02833 expect 0xc1bf 0xc793      ; replace exactly these 2 words ...
    call  my_hook                       ; ... with exactly 2 words
.end

.code                                   ; placed automatically in free space (the map's pool)
my_hook:
    ld    r1, [fp+15]                   ; redo what the replaced words did
    ld    r7, [r1+3]
    cmp   r7, #LEVEL
    bne   .skip                         ; labels starting with '.' are local to the patch
    ...
.skip:
    ret
.end

.string "2.DSP:V1.0.7" "2.DSP:1.0.7b"  ; UI string replacement (NEW may be shorter;
                                        ; any Unicode character is one word, see polish_font)

.bitmap 0x26                            ; redraw image/glyph 0x26 of the glyph table
    .################################.  ; exactly its width x height, '#' = pixel on
    ...
.end
```

Inside `.code`, an `.art` … `.endart` block turns '#'/'.' rows into column words (bit 0 = top row,
terminated by `0xf000`) that your code can read with `ldc` — see `patches/polish_font.patch`.

## Translations

UI texts are partly strings (drawn with a font) and partly **images with text in them** (buttons,
headers, dialogs). `python3 -m nek100mod disasm` gives you the strings; to see the images, render the glyph
table locally (layout in [FIRMWARE_MAP.md](FIRMWARE_MAP.md)) and redraw them with `.bitmap`.
Strings may contain any character `polish_font` (or a similar patch for your language) can draw.
Watch the space: the screen is 128 px wide, a button 34 px.

## Testing code without the instrument

`nek100mod/sim.py` runs patch code under our ISA model against fake RAM, see
`tests/test_polish_font.py`. It catches logic bugs before flashing (it found one: `ó` is U+00F3,
below 0x100), not mistakes in the ISA model.

Names from the map (`touch`, `sustain_cc64`, `load_user_preset`, …) and your parameters can be used in
any expression (`#BOOT_PRESET-1`, `[sustain_cc64+1]`). Assembler syntax is described in `nek100mod/asm.py`,
instructions in [ISA.md](ISA.md).

## Safety rules enforced by the builder

- input must be the official firmware (SHA-256 from the map), otherwise nothing is built;
- every hook checks its `expect` words and must assemble to exactly the same number of words;
- two patches writing the same word is an error;
- code blocks must fit into the pools; each bundled patch has a fixed place (`canonical_layout`), so any
  combination gives the same bytes in the CLI and on the web page;
- the container checksum is recomputed and the output re-validated.

## Workflow

```sh
python3 -m nek100mod disasm NEK100_DSP_V1.0.7.bin fw.s        # annotated listing, keep it local
# experiment: edit fw.s directly …
python3 -m nek100mod asm NEK100_DSP_V1.0.7.bin fw.s test.bin
# … flash test.bin, try it. When it works, turn it into a shareable patch:
python3 -m nek100mod extract NEK100_DSP_V1.0.7.bin test.bin patches/my_feature.patch --name my_feature
python3 -m nek100mod build NEK100_DSP_V1.0.7.bin out.bin -p my_feature -p version_tag
```

`extract` writes hooks for changed code, a `.code` block for anything you put into the pool (with
symbolic labels so it can be relocated) and `.hook … .dw` for changed data. Review it, add comments and
parameters, then add the name to `DEFAULT_ORDER` in `patcher.py` if it should be bundled.

Always include `version_tag` in test builds so the version screen shows that the instrument runs a mod.
Keep the official file: flashing it back restores the original state.

## Improving the map

If you work out what a function does, add a `func`/`label`/`var` line to `map/…map` with a short
description in **your own words** (mark it C if you confirmed it on the instrument). See
[FIRMWARE_MAP.md](FIRMWARE_MAP.md).
