# Firmware map

`map/nek100_dsp_v1.0.7.map` is our description of one exact firmware file. It holds addresses and short
descriptions written by contributors — no code or data copied from the firmware.

```
firmware NAME sha256 HEX         the only file the map (and the patches) apply to
code    START END                code ranges, END exclusive (word addresses)
ramdata START END                file words copied to RAM address 0 at boot
pool    START END                free space for patch code (must be provably unused)
func    ADDR NAME ; text         function entry
label   ADDR NAME ; text         named place inside a function
var     ADDR NAME [SIZE] ; text  RAM variable (RAM word address), optional size in words
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
- The pool is a function that nothing calls, jumps into or points to (checked over the whole image).

## Other firmware versions

A new firmware version needs its own map: new SHA-256, re-found addresses. The patches will refuse to
apply to anything else, which is intended — check the hook sites in the new listing and update `expect`.
