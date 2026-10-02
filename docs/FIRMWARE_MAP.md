# Firmware map

`targets/<id>/target.map` (e.g. `targets/nek100-dsp-1.0.7/target.map`) is our description of one exact
firmware file. It holds addresses and short
descriptions written by contributors — no code or data copied from the firmware.

```
firmware NAME sha256 HEX         the only file the map (and the patches) apply to
device   "Brand Model"           shown by the web page and `nuxdsp targets`
input    FILE.bin                official file name; output FILE.bin: suggested name of the result
defaults NAME...                 patches applied by default (and the pool layout order); optional NAME...
code    START END                code ranges, END exclusive (word addresses)
ramdata START END                file words copied to RAM address 0 at boot
pool    START END                free space for patch code (must be provably unused)
func    ADDR NAME ; text         function entry
label   ADDR NAME ; text         named place inside a function
var     ADDR NAME [SIZE] ; text  RAM variable (RAM word address), optional size in words
glyphs  TABLE BITMAPS COUNT      glyph/image table and its bitmaps (file word addresses)
```

Descriptions marked `(C)` were confirmed on the instrument, `(H)` are hypotheses.

## How things were found (short version)

- `main → init_all → main_loop_tick`; `boot_presets` (end of `init_all`) loads factory preset 0.
- Presets are 31 words, all fields in use; field 12 is Touch. The patch `sustain_in_preset` reuses its
  high byte.
- Touch (`touch`, 0..4) is only stored by the DSP and sent to the MCU as CC 0x32 — the MCU applies the
  velocity curve. Touch OFF therefore rewrites the note-on velocity in `task_key_events`, which affects
  both the internal sound and USB MIDI out.
- Sustain (`sustain_cc64`, one value per part) is the CC64 value sent when the pedal is pressed.
- The display (128×64 mono) is driven by the DSP. All UI graphics are one table of 243 glyphs/images
  (`glyphs` line in the map): 8 words per entry (u32 byte offset, size, width, height), bitmaps stored
  by columns, each column starting on a byte, MSB = top pixel. It holds three fonts (main 7×12, small
  4×5, big digits), buttons and headers with English text, dialogs and icons. Image numbers used by
  `lang_pl`: buttons 34×9 in pairs normal/selected 0x00–0x33 and 30×9 0xed–0xf2, screen headers
  64×8 0x34–0x43, dialogs 128×44 0xbe, 0xc5, 0xd1, 0xd8, 0xdf, power-on screen 0xd3.
- UI strings live in the initialised data, one character per word, 0-terminated. The sound and demo
  names, effect, section, style, Touch and reverb names are reached through pointer tables
  (`sound_names`, `touch_names`, …); a few short ones (ON, OFF, INTRO, …) are used directly.
  The small font has no lowercase letters: its character table points lowercase codes at
  unrelated glyphs (`polish_font` maps them to capitals).
- The pools are functions that nothing calls, jumps into or points to (checked over the whole image).

## Other firmware versions and models

Every firmware file needs its own target directory: new SHA-256, re-found addresses. The patches refuse
to apply to anything else, which is intended. See [NEW_TARGET.md](NEW_TARGET.md).
