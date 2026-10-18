# DOOM on the NEK-100

An unofficial Doom port for the piano's own 128x64 one-bit LCD, shipped as the optional `doom_demo` patch
(Extra > DOOM). DOOM is a trademark of id Software; this project is not affiliated with or endorsed by id.

## What it is

- One map of our own, **Hangar** (`tools/makemap.py` -> `maps/hangar.wad`, nodes by zdbsp), with
  [Freedoom](https://freedoom.github.io) Phase 1's textures, sprites and music (BSD 3-clause,
  `art/FREEDOOM-COPYING.txt`, quoted in full in the generated patch). Builds from these may be shared.
- Your own WAD works locally (`--wad`, `--map`, `--music`, or `PIANODOOM_WAD` / `PIANODOOM_MAP` /
  `PIANODOOM_MUSIC`), e.g. id's shareware E1M1. Such builds carry id's data: keep them private.
  `wad.shareable()` decides, and `tools/exportpatch.py` refuses anything else.
- Gameplay: four enemy slots fed from a roster by distance and skill, pistol/shotgun hitscan, pickups, doors,
  lift, a sinking gate, HUD, death/restart, the exit switch, a title screen and a skill menu.
- Music: the title plays D_INTRO once, the level loops D_E4M8 (falls back to D_E1M1 when the WAD has no E4M8).
  Effects play on the GM drums in the patch (the gunshot voice of soundbank slot 500 would clash with an added
  instrument there).

## How it is built

- The engine is ours, in C (`firmware/doom.c` rendering, `firmware/game.c` gameplay, `firmware/music.c`), compiled
  by our own compiler for the P16 CPU, `cc/p16cc.py` (a C subset, static frames, no recursion). Doom's GPL code
  does not fit (32-bit fixed point, malloc, ~250 KB RAM); its data and algorithms do: front-to-back BSP walk with
  an explicit stack, solid-segment and per-column clipping, sprites clipped against walls.
- `firmware/doom.py` turns the map, assets and compiled code into the patch; the C state lives in RAM, everything
  constant (map, textures, sprites, font, music) in far program memory, read with the firmware's copy routine.
- The browser simulator (`tools/webserve.py`, http://localhost:8017/) runs the same compiled instructions in
  `web/p16.js`; host natives stand in for the firmware's copy, synth and trace services.

## Budgets (hard gates in `tools/builddemo.py`)

| What | Used / limit |
|---|---|
| C RAM | 479 / 482 words, plus 24 glue words and the 1024-word framebuffer |
| Far code + data | inside the target far pool, no overlap with other patches |
| Firmware file | the whole 0x40000-word (512 KiB) partition, checksum and padding included |
| Bank-0 pools with every bundled patch | a handful of words left in each (see `nuxdsp/patcher.py`'s layout) |

The replay (`tools/playthrough.py` + `tools/playthrough.cjs`) plays the whole level from the actual linked
firmware image by key ticks only, with a guard on every RAM write, and must end alive at the exit.

## Lessons from the hardware

- Frames: a full 128x64 frame (~5000 instructions) copies in ~0.2 ms, an LCD refresh takes ~0.8 ms; the game
  renders in resumable slices from the 10 ms tick.
- Music goes straight to the synthesizer. Songs send no bank select, so a channel left in another bank plays that
  bank's voice (bank 18, program 34 is a laugh). The stream therefore starts with CC0/CC32 = 0 on each melodic
  channel, then a 20 ms gap. The same messages sent in one burst right before a program change silenced the
  channel; over USB, a millisecond apart, they worked.
- Browser timing proves nothing about device timing; state which checks ran on the piano.

## Next: a WAD and a map picked in the web patcher

1. Map data patched into the already-built code: fixed table addresses and sizes, no extra RAM.
2. The WAD and map converters (`tools/wad.py`, `firmware/doommap.py`, the asset packers) ported to JavaScript.
3. Limits checked before patching (vertices, lines, sectors, nodes, things, far words), with a clear message.
4. In the patcher: "Load WAD", a map list, the song; the result stays in the browser (a commercial WAD's data
   must not be shared).
