# Writing patches

A patch is a small text file in `targets/<target>/patches/` (one directory per supported firmware file). It never contains vendor code: only *where* to change
something (with a few `expect` words as a safety check) and *what* to put there (your instructions).

```
.patch my_feature
.title "One line: what it does"
.param LEVEL 100 1 127 "Shown to the user in the CLI and the web page"
.requires polish_font                   ; (optional) patches that must be applied too

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

.string "2.DSP:V1.0.7" "2.DSP:1.0.7B"  ; UI string replacement (NEW may be shorter;
                                        ; any Unicode character is one word, see polish_font)

.bitmap 0x26                            ; redraw image/glyph 0x26 of the glyph table
    .################################.  ; exactly its width x height, '#' = pixel on
    ...
.end
.bitmap 0x26 at 2 1                     ; ... or only a rectangle of it (top left 2, 1)
    ...
.end

.draw 0x26 at 2 1 30 7 [inverse] [bold] ; clear a 30 x 7 rectangle of image 0x26 and centre
    1 "ZAPISZ"                          ; text in it, letters' top at row 1 of the rectangle
.end                                    ; (our pixel font, nuxdsp/pixfont.py)

.table 0x27c7 5                         ; the strings a pointer table (RAM address, 5 pointers)
    3 "ŚREDNI"                          ; points to, by position (1 = first) ...
    "HARD1" "MOCNY"                     ; ... or by the original text; laid out anew in the
.end                                    ; space the table's strings occupy
```

Inside `.code`, an `.art` … `.endart` block turns '#'/'.' rows into column words (bit 0 = top row,
terminated by `0xf000`) that your code can read with `ldc` — see `targets/nek100-dsp-1.0.7/patches/polish_font.patch`.

## Translations

UI texts are partly strings (drawn with a font) and partly **images with text in them** (buttons,
headers, dialogs). `lang_pl.patch` is a complete example.

- **Strings in pointer tables** (sound and demo names, Touch, reverb, style sections): `.table`. The
  builder packs the new texts into the space the old ones took, so a translation may be longer when
  others are shorter; it reports how many words are used. A string that the firmware may also
  reference from elsewhere (a code literal or another pointer with its address) keeps its address:
  translated in place if the new text fits, otherwise left as it is with a translated copy for the
  table. Names stay within 18 characters, the longest original.
- **Other strings** (ON, OFF, INTRO, …): `.string`, in place, not longer than the original.
- **Images**: `.draw` writes text with our pixel font (`nuxdsp/pixfont.py`: capitals 5 px high, a
  narrow form used automatically when the text is too wide, Polish accents in the row above and
  ogonki in the row below, a bold 7 px font for big words) into a rectangle of the image, so the
  frame and icons stay. `.bitmap … at X Y` does the same with hand-drawn pixels. To see the images,
  render the glyph table locally (layout in [FIRMWARE_MAP.md](FIRMWARE_MAP.md)).

Strings may contain any character `polish_font` (or a similar patch for your language) can draw; the
small 4 x 5 font has no room for accents and shows capitals of the base letter. Watch the space: the
screen is 128 px wide, a button 34 px.

## Testing code without the instrument

`nuxdsp/sim.py` runs patch code under our ISA model against fake RAM, see
`tests/test_polish_font.py` and `tests/test_boot_preset.py`. It catches logic bugs before flashing (it found one: `ó` is U+00F3,
below 0x100), not mistakes in the ISA model.

Names from the map (`touch`, `sustain_cc64`, `load_user_preset`, …) and your parameters can be used in
any expression (`#BOOT_PRESET-1`, `[sustain_cc64+1]`). Assembler syntax is described in `nuxdsp/asm.py`,
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
python3 -m nuxdsp disasm NEK100_DSP_V1.0.7.bin fw.s        # annotated listing, keep it local
# experiment: edit fw.s directly …
python3 -m nuxdsp asm NEK100_DSP_V1.0.7.bin fw.s test.bin
# … flash test.bin, try it. When it works, turn it into a shareable patch:
python3 -m nuxdsp extract NEK100_DSP_V1.0.7.bin test.bin targets/nek100-dsp-1.0.7/patches/my_feature.patch --name my_feature
python3 -m nuxdsp build NEK100_DSP_V1.0.7.bin out.bin -p my_feature -p version_tag
```

`extract` writes hooks for changed code, a `.code` block for anything you put into the pool (with
symbolic labels so it can be relocated) and `.hook … .dw` for changed data. Review it, add comments and
parameters, then add its name to the `defaults` (or `optional`) line of the target's `target.map`, and
regenerate the web data: `python3 -m nuxdsp web NEK100_DSP_V1.0.7.bin`.

Always include `version_tag` in test builds so the version screen shows that the instrument runs a mod.
Keep the official file: flashing it back restores the original state.

## Improving the map

If you work out what a function does, add a `func`/`label`/`var` line to the target's `target.map` with a short
description in **your own words** (mark it C if you confirmed it on the instrument). See
[FIRMWARE_MAP.md](FIRMWARE_MAP.md).
