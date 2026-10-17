# Doom on the NEK-100: the plan

Goal: Doom, playable as Doom (shareware episode 1, E1M1..E1M9), on the piano's 128x64 one-bit LCD, controlled from
the keyboard, with music and sound effects from the piano's own synthesizer.

## What we build on (all confirmed on the device unless marked)

- CPU: the SAM5504B's P16XT, 16-bit words, ~25 MIPS (estimate from frame timings). cmp/blt compare unsigned.
- Code and constant data: the firmware file, far code from 0x1a280; the partition allows the file to grow to 0x40000
  words (512 KB). Far data is read with the firmware's program-to-RAM copy 0x7638. Not yet known: whether the boot
  loader loads the file beyond ~0x1b000 (test in phase 0).
- RAM: ~500 free words (0x6430..0x6629) + the framebuffer. More must be borrowed from features idle during the game
  (accompaniment, recorder, demo) — research.
- Synthesizer: `synth_send` 0x1330(status | channel, d2 << 8 | d1); USB MIDI from the PC also plays it.
- Extra storage if program memory runs out: AT45DB041 pages 0x000..0x6ff (448 KB, firmware routines read it),
  NAND Style/DEMO partitions (2 MB each; reader not found yet).
- Our tools: p16cc (C subset, static frames), the simulator, MIDI trace markers, `nuxdsp build/flash`.

## Data: DOOM1.WAD (shareware 1.9, sha1 5b2e249b…), kept local in wad/ (not in git)

| What | Raw | On the piano |
|---|---|---|
| E1M1 geometry (467 vertices, 475 lines, 85 sectors, 236 BSP nodes) | 46 KB | ~11 k words, compacted |
| All 9 maps | ~700 KB | ~100+ k words: needs the extended file or AT45/NAND |
| Music (13 MUS lumps) | 245 KB | compact event streams, a few k words per song |
| Sound effects (55, 11 kHz PCM) | 535 KB | phase 1: drum-kit notes; phase 2: real samples as custom voices in the soundbank |
| Sprites (483) | 826 KB | downscaled one-bit silhouettes, a fraction of that |

## Engine: our own, following Doom's algorithms

Doom's code (GPL) does not fit (32-bit fixed point, structs, malloc, recursion, ~250 KB+ RAM), but its data and its
algorithms do: map units are 16-bit integers, the BSP is precomputed. Render front to back through the BSP with an
explicit stack, clip with solid segments and per-column upper/lower bounds. Readability first (the user's verdict:
the Playdate port's dither is ugly, almost nothing shows; doom-nano is crude but reads better): clean wall edges and
outlines, few flat shades by light level and distance rather than noisy dither, floors and ceilings plain, sprites as
clear silhouettes clipped against walls. Game: Doom's movement and collision
(blockmap), doors, lifts, switches, pickups, monsters (simplified AI, line of sight via REJECT), weapons, HUD.

## Phases (each ends with a device test)

0. Plumbing: variable far reads (both pointer layouts tried, the right one chosen at run time), is the end of the
   512 KB partition loaded, and E1M1's music on the synth when the game starts.
1. E1M1 walls through the BSP: in the simulator first, then on the device; walking with collision.
2. Doors, lifts, switches, exits; all nine maps.
3. Things: sprites, pickups, monsters, weapons, damage, HUD, death and level end.
4. Sound effects, menus, polish, speed.
