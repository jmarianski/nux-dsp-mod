# Touch CUSTOM

`touch_custom` adds a separate Touch mode after HARD2/MOCNY+. It uses HARD2 as its input and
changes incoming key velocity before the internal sound and outgoing USB MIDI routes. The change
therefore affects every voice played from the keyboard, including Grander Piano on slot 2. Incoming
external MIDI uses the original route. The patch is opt-in and requires `touch_off`.

## Curve and calibration

With `v` the MIDI velocity delivered by HARD2 and `k` the build parameter `CUSTOM_KNEE`:

```
custom(v) = v                         when v <= k
            min(127, 2*v - k)         when v > k
```

Default `k = 32`:

| HARD2 input velocity | 0 | 1 | 16 | 32 | 48 | 64 | 80 | 96 | 127 |
|---|---|---|---|---|---|---|---|---|---|
| CUSTOM output velocity | 0 | 1 | 16 | 32 | 64 | 96 | 127 | 127 | 127 |

Zero stays zero, including Note On with velocity 0. The function is monotone and reaches 127 at
`ceil((127+k)/2)`. This is an initial correction, not a measured inverse of the factory curve.
`CUSTOM_KNEE` ranges from 1 to 96: a higher value preserves more of HARD2 and raises the upper
range less. For example, 64 preserves 1–64 and reaches 127 at input 96. The parameter is chosen
when building the firmware, not edited in the piano's menu.

Use velocities from comfortable piano and forte playing to choose the knee. The numbers describe
input/output MIDI, not finger pressure, dB or sample amplitude. Grander's sample selection, G2 volume
modulators, filter and envelopes then respond to the resulting velocity as usual.

## Patch integration

Touch values 0–4 keep their factory meanings; OFF stays 5 and CUSTOM is 6. The menu order is OFF,
LIGHT2, LIGHT1, NORMAL, HARD1, HARD2, CUSTOM. CUSTOM is saved in the existing Touch preset field,
including when `sustain_in_preset` uses its high byte. Presets selecting CUSTOM need this patch
when loaded; original and existing OFF presets retain their values.

For internal CC 0x32, CUSTOM is translated to HARD2 (4), while OFF keeps its existing translation to
LIGHT2 (0). The event hook delegates to `touch_off` after remapping, retaining its optional Doom
callback. Only CUSTOM remaps dynamic notes; the other Touch modes retain their event velocities.
Extra → Patches lists TOUCH CUSTOM when its seven-setting menu is installed.

Example with the normal default patches and CUSTOM:

```sh
python3 -m nuxdsp build NEK100_DSP_V1.0.7.bin custom.bin \
    -p boot_preset -p touch_off -p sustain_in_preset -p version_tag \
    -p octave_per_part -p extra_menu -p touch_custom --param CUSTOM_KNEE=32
```

On the web page, select `touch_custom` as well as `touch_off`. Added instruments and the Grander
soundbank options work as before; this patch changes the DSP, not the soundbank.

## Original tables and verification

The map identifies the original library at file word 0x12cb9 / byte 0x25972: 12 records of 5 words
each, with nine packed byte points and one padding byte. `synth_curve_00`..`synth_curve_11` and their
readers appear in a locally generated listing:

```sh
python3 -m nuxdsp disasm NEK100_DSP_V1.0.7.bin original_with_curves.s
```

Their mapping to the five factory Touch settings has not been established. They include pitch and
other synthesis uses; CUSTOM does not overwrite them. A local original-value comparison is kept
in the sibling RE workspace's `notes/TOUCH_CURVES.md` and `notes/CURVES_ORIGINAL.csv`.

Tests run the actual patch instructions over every event type, all seven Touch values, all 128
velocities and all allowed knees. They also cover menu/value conversion, internal CC translation,
preset storage and the optional callback. Firmware checks verify that the original tables and
external MIDI entry remain untouched, disassembly/assembly preserves every annotated data word,
and the web builder agrees with the CLI. On a NEK-100 (2026-10-20, default knee 32) CUSTOM
shows in the menu, gives more control over soft playing and forte with less force; full volume comes early,
as on an acoustic piano. Not calibrated against measured velocities: raise `CUSTOM_KNEE` for a later forte.
