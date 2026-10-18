# Doom on the NEK-100: the plan

Goal: Doom, playable as Doom (shareware episode 1, E1M1..E1M9), on the piano's 128x64 one-bit LCD, controlled from
the keyboard, with music and sound effects from the piano's own synthesizer.

## Browser iteration checkpoint

Run `python3 tools/webserve.py` and open http://localhost:8017/. The default is a playable E1M1 demo, compiled
from `firmware/doom.c` + `firmware/game.c` by p16cc and executed by `web/p16.js`. It includes radius/height/step
collision, doors and floor specials, four easy-difficulty monsters, pickups, pistol/shotgun hitscan, health/ammo,
death/restart and the real exit switch. Music is shared in `firmware/music.c`; MIDI SFX use an unused E1M1 channel.

The state uses 474/482 C RAM words, plus the separately reserved 24 glue words and 1024-word framebuffer. Constants,
map grid, spawn records, sine, font and sprites live in far program memory. Clip-window words become wall-depth
words after each column closes, avoiding a second depth buffer. A generated local patch is built by
`tools/builddemo.py`; RAM, far-pool overlap/bounds, checksum and the full 512 KiB partition are hard gates.

Confirmed: nineteen textured geometry views and three door opening heights match the reference; synthetic and real-map collision contracts; doors block
movement and hitscan until opened; combat, pickups, death and restart; a full input-driven spawn-to-exit replay
with no teleport/inventory edits (4 kills, 62 health, 32 ammo, max call depth 13), also from the actual linked
firmware image. Replay drives start/key/tick callbacks, with a one-million-instruction ceiling per tick. Runtime
guards inspect every C/native RAM write. Browser timing is measured separately from device timing.

Demo scope is deliberately smaller than full Doom: E1M1 easy, simple silhouettes and direct chase/hitscan AI,
shared ammo, doors stay open, vertical position snaps to the floor, floors and ceilings share the plain background.
Simple 32×32 material tiles distinguish walls, supports, computers, doors and switches. A browser-only navigation
map reads the live player/enemies and ROM geometry, with an optional fixed route from spawn to the first soldier.
The first hardware build froze after displaying its first frame, including without key input. The current diagnostic
version uses resumable rendering, freezes camera/door heights during a frame, isolates key-handler scratch RAM and
emits USB markers for music/logic/render/return. The higher instruction budget and larger work batches address the
conservative version's approximately 0.5 FPS in simulation; the freeze's cause remains unconfirmed. The CPU model
and host farcopy/synth substitutions do not establish device timing or read integrity. Device timing, responsiveness,
real WebMIDI audio validation and the earlier music-read glitch diagnosis remain pending before a hardware milestone.

## What we build on (all confirmed on the device unless marked)

- CPU: the SAM5504B's P16XT, 16-bit words, ~25 MIPS (estimate from frame timings). cmp/blt compare unsigned.
- Code and constant data: the firmware file, far code from 0x1a280; the partition allows 0x40000 words (512 KiB).
  Far data is read with the firmware's program-to-RAM copy 0x7638. The preceding device session confirmed reads
  near the end of the full partition; this demo still needs its own hardware validation.
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
