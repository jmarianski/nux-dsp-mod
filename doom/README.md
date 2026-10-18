# doom (formerly doom-piano)

Play **Doom on a piano**. Any MIDI keyboard over USB works (made with a NUX NEK-100 in mind):
piano keys and pedals become a virtual keyboard, so every Doom source port sees them like a real one.
*[Polski poniżej](#po-polsku).*

## Local browser simulator (NEK-100 LCD)

```sh
python3 tools/webserve.py
```

Open **http://localhost:8017/**. No Python packages are needed for the server/compiler (it uses nek100-mod, this
directory's parent); put [Freedoom](https://freedoom.github.io) Phase 1 at `wad/freedoom1.wad`
(BSD license: textures, sprites, title and music). The map is our own, **Hangar** (`maps/hangar.wad`, written by
`tools/makemap.py`): its BSP geometry is rendered by `firmware/doom.c`, with gameplay in `firmware/game.c`, compiled
for the piano's P16 CPU and executed in JavaScript. The canvas is the same 128×64, one-bit framebuffer. The
**playable demo**: start room, corridor and stairs, a hangar with a skylight, crates and a lift to the balcony with
the shotgun, a computer room, a gate that sinks as you walk into it, and the exit room. Zombies, imps and shotgun
guys by skill (four at a time), pickups, pistol/shotgun, doors, health/ammo HUD, death/restart and the exit switch.
The selector retains the earlier test raycaster.

The title screen shows the DOOM logo (`art/doom_logo.txt`, 1-bit, from
[Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Doom_logo.png), public domain there as a text logo)
marked "UNOFFICIAL PORT": DOOM is a trademark of id Software, and this project is not affiliated with or endorsed by
id. Since the map and the assets are free, builds can be shared. Your own WAD works too: `--wad` takes the
textures, sprites and music from it, `--map` the E1M1 it holds, e.g. id's original from the shareware WAD:

```sh
python3 tools/builddemo.py --wad wad/DOOM1.WAD --map wad/DOOM1.WAD
python3 tools/packdemo.py  --wad wad/DOOM1.WAD --map wad/DOOM1.WAD
```

The music: the title plays Freedoom's intro once, the level loops E4M8; `--music E1M1` (any song lump of the WAD)
picks another for the level. Those `--wad` builds stay private (the tools say so). The server and the tests take the same as `PIANODOOM_WAD` /
`PIANODOOM_MAP`. The shareable build is also nek100-mod's `doom_demo` patch (its CLI and web patcher):
`tools/exportpatch.py` writes it there (effects on the GM drums, Freedoom's license inside), then
`python3 -m nuxdsp web NEK100_DSP_V1.0.7.bin` in nek100-mod. Editing the map:
change `tools/makemap.py` and run it; the nodes come from `zdbsp` (`apt install zdbsp`, or without root
`apt-get download zdbsp && dpkg-deb -x zdbsp_*.deb x`, then `--zdbsp x/usr/bin/zdbsp`). `maps/hangar.wad` also plays
in any source port: `chocolate-doom -iwad freedoom1.wad -file maps/hangar.wad -warp 1 1`.

- Arrow keys / WASD: turn and move; Q/E: strafe.
- **Space**: fire; **F**: doors/switches; **Shift**: run. Reach the exit switch (west wall of the last room) and press F to win.
- **Enter** restarts after death or winning. Piano: C5 fire, D5 use, E5 run, B0 restart.
- Stand close to a door and face it, then tap **F / D5**; it lifts upwards. **M / Mapa** opens a browser-only
  map: current player arrow, live enemies, yellow doors and a fixed route from spawn to the first zombie.
- **R / Przeładuj**: recompile changed sources and restart. Build errors appear in the log; fix the code and retry.
- **Włącz MIDI**: select the piano as output for the music (Freedoom's intro on the title, E4M8 in the level) through its own synthesizer over USB, or as input
  for piano-key movement. No browser synthesizer is included. This does not flash firmware.
- Pause, reload, MIDI disconnection and hiding the tab release controls/silence notes as appropriate.

The server binds only to localhost. `web/build/` contains generated WAD-derived data and stays out of git.
To build without the server: `python3 tools/webbuild.py` (or `--engine ray` for the test raycaster).
The map currently needs 479 of the target's 482 free C RAM words, leaving 3 words; the reserved 24 words of firmware
glue and 1024-word framebuffer are counted separately. Pixel parity of geometry with the Python reference is
tested at twenty-two viewpoints plus three door opening heights. Native firmware services are simulated,
so browser performance does not predict device timing. The earlier build was flashed and froze after its first
frame. The current diagnostic build spreads rendering across callbacks, allows up to one million P16 instructions
per tick in the emulator, and emits USB stage markers to investigate that hardware failure. Its device behavior
still needs checking.

The demo deliberately simplifies Doom: original one-bit silhouettes, direct chase/ranged enemy AI, hitscan attacks,
one shared ammo pool, doors that stay open, instant vertical snapping on steps, plain floors/ceilings. It plays
one map. Music and temporary MIDI sound effects play through the piano; no browser synthesizer is included.
Walls use original, simple 32×32 one-bit tiles selected by the WAD's material names: metal panels, masonry,
ribbed supports, computer faces, steps, doors, switches and exit signs. Their world coordinates and clipping
are shared by both targets; doors have large frames/handles and the pattern moves with the panel. These are
simplified patterns, rather than full Doom textures. The tile column buffer holds up to eight ink intervals;
compressed columns and surface descriptors live in program memory. The navigation map adds no target RAM or firmware data.

### Memory gates and a local firmware build

```sh
python3 tools/builddemo.py
python3 tools/playthrough.py
node tools/playthrough.cjs web/p16.js build/linked-game.json build/route.json
```

`builddemo.py` requires the local official `NEK100_DSP_V1.0.7.bin` (next to nek100-mod, or `NEK100_FW`), builds the patch with the target's normal
patches, verifies checksums and enforces the target far pool and the entire 0x40000-word / 512 KiB partition.
It writes the firmware, exact memory report and an emulator program decoded from the linked firmware into
ignored `build/`. Nothing is flashed. The last command replays the entire level using that actual artifact's
instructions and far addresses, with a guard on every RAM write. The recorded run finished with all 4 enemies
defeated, 62 health, 32 ammo and a maximum call depth of 13. Replay drives the actual start/key/tick callbacks and
enforces each callback's instruction budget. Host-native firmware services remain outside that count.
`build/memory-budget.json` is the current size report.

To prepare a private hardware package, run `.venv/bin/python tools/packdemo.py`. It runs the full tests, builds
and replays the exact linked demo, then verifies a diagnostic ZIP under ignored `build/packages/`. The package includes
the target's six default patches and their parameter values, the local Windows updater, Polish instructions,
checksums, and recovery images with the same defaults without Doom plus the official DSP firmware. The
saved Default preset remains the startup preset (slot 1); the package updates only DSP. It never flashes or
uploads anything. The official updater/DLL must already be present in the parent NUX update directory.

## Quick start (Linux)

```sh
sudo apt install chocolate-doom freedoom   # or any other Doom and IWAD
uv run pianodoom play                       # connect the piano, it waits for it
```

`play` starts the bridge and then Chocolate Doom with Freedoom (or Crispy Doom, PrBoom+, GZDoom, and
`doom1.wad`/`doom.wad`/`doom2.wad`, whichever it finds). Your own command goes after `--`:

```sh
uv run pianodoom play -- gzdoom -iwad ~/wads/doom2.wad
```

Only the bridge, for a game you start yourself: `uv run pianodoom run -v`.

## Layout

Middle C (MIDI 60) is **C4**. The keys send Doom's stock controls, no Doom config needed.

| Where | Note | Action |
|---|---|---|
| left hand | `C#3` `D#3` (black keys) | forward |
| | `C3` / `E3` | turn left / right |
| | `D3` | backward |
| | `B2` / `F3` | strafe left / right |
| right hand | `C5` | fire |
| | `D5` | use (doors, switches) |
| | `E5` | run |
| | `G5` | automap |
| weapons | `C6` `D6` `E6` `F6` `G6` `A6` `B6` | weapons 1–7 |
| bottom | `A0` `B0` `C1` `D1` | Esc (menu), Enter, Y, N |
| top | `C8` | pause |
| pedals | sustain (CC64) / soft (CC67) | fire / use |

Hit a movement key **forte** (velocity ≥ 100) and you run. Turn Touch off on the piano
(or use `touch_off` from [nux-dsp-mod](https://github.com/jmarianski/nux-dsp-mod)) if you never want that,
or set `forte_velocity = 0`.

Arrow keys also move the cursor in Doom's menus, so the left hand navigates them too.

### Your own layout

```sh
uv run pianodoom layout --toml > my.toml   # copy the default
uv run pianodoom monitor                   # press keys to see their names
uv run pianodoom play --config my.toml
```

A layout maps note names (`C4`, `F#3`, `Bb2` or MIDI numbers) and pedal CC numbers to actions.
An action is a name from `[actions]` (`forward`, `fire`, `weapon3`, …) or any evdev key name
(`KEY_F12`); `[actions]` can also redefine what a name presses.

## Permissions

The virtual keyboard needs write access to `/dev/uinput`. On many desktops the logged-in user
already has it; if `pianodoom` says otherwise:

```sh
sudo cp udev/70-uinput.rules /etc/udev/rules.d/
sudo udevadm control --reload && sudo udevadm trigger /dev/uinput
```

`--dry-run` prints the keys instead of pressing them, without any permission.

## Commands

| Command | |
|---|---|
| `pianodoom play [-- cmd…]` | bridge + Doom |
| `pianodoom run` | bridge only |
| `pianodoom ports` | MIDI inputs |
| `pianodoom monitor` | what the piano sends |
| `pianodoom layout [--toml]` | current layout / default layout file |

Common options: `--config FILE`, `--port NAME` (part of the MIDI input name), `--dry-run`, `-v`.

## On the piano's own display (work in progress)

The long-term goal is Doom running on the NEK-100 itself, drawn on its 128x64 LCD, as a patch for
[nek100-mod](..).

- Step 1, `fb_splash` (works on a real NEK-100): a full-screen test card copied into the framebuffer; the image
  stays until the next full redraw of the main screen.
- Step 2, `fb_test` (`firmware/fbtest.py`, works on a real NEK-100): the card read from far program memory
  (above 0xffff) with the firmware's own copy routine, then a game loop in the 10 ms tick (a whole frame every
  50 ms: sweeping line, bouncing box, numbers) with timings on screen. Extra > DOOM (page 3, extra_menu's item 7,
  shown only with this patch) starts it, any panel key stops it; while it runs the piano keys steer the box
  (C3/E3 left/right, C#3 or D#3 up, D3 down) and make no sound. Measured: a whole 128x64 frame (~5000 instructions) renders in ~0.2 ms, a full LCD refresh takes
  ~0.8 ms, so at 20 frames/s a frame has a budget of very roughly 1-2 million instructions.
- Step 3, `doom_ray` (`firmware/ray.c`, compiled by `cc/p16cc.py`, our C compiler for the DSP): a raycaster on the
  LCD, started from Extra > DOOM. C3/E3 turn, C#3 or D#3 forward, D3 back, B2/F3 strafe, any panel key leaves.
  Top-left: the last frame's time in ~ms (a second number = the C self-test failed on the device).
  Build it as below with `firmware/ray.py` and `-p doom/firmware/ray.patch` instead of fb_test (ray.patch is
  generated, local: it carries the WAD's music).

```sh
python3 firmware/fbtest.py                       # regenerates firmware/fb_test.patch (our own code + data)
cd ..   # nek100-mod
python3 -m nuxdsp build ../NEK100_DSP_V1.0.7.bin doom/build/NEK100_DSP_fbtest.bin \
    -p boot_preset -p touch_off -p sustain_in_preset -p version_tag -p octave_per_part -p extra_menu \
    -p doom/firmware/fb_test.patch
python3 -m nuxdsp flash -y doom/build/NEK100_DSP_fbtest.bin   # piano in update mode (needs pyusb)
```

Built files contain NUX code: keep them local (`build/` is ignored). Flash the official file to go back.

## Development

```sh
uv run pytest
```

The BSP/game tests require the local WAD and Node; they skip if either is missing. The linked-firmware replay
also requires the official local firmware. Tests reject RAM/ROM overflow and overlapping code/data, characterize
collision/doors/combat/pickups/restart, and replay a complete win of the map. Optional real-browser checks,
with the server running and Playwright installed: `node tools/webcheck.cjs`. Set `PLAYWRIGHT_MODULE` to an
existing Playwright installation if needed. These checks use mocked MIDI and save `build/webcheck.png`.

---

## Po polsku

Doom na pianinie. Każda klawiatura MIDI na USB (robione z myślą o NUX NEK-100): klawisze i pedały
zamieniają się w wirtualną klawiaturę komputera, więc każdy port Dooma widzi je jak prawdziwą.

```sh
sudo apt install chocolate-doom freedoom
uv run pianodoom play
```

Lewa ręka wokół C3 jak WASD (czarne klawisze `C#3`/`D#3` — naprzód, `C3`/`E3` — obrót, `D3` — wstecz,
`B2`/`F3` — krok w bok), prawa wokół C5 (`C5` strzał, `D5` użyj, `E5` bieg, `G5` mapa), bronie na
białych klawiszach oktawy 6, menu na samym dole (`A0` Esc, `B0` Enter, `C1`/`D1` Y/N), pedał sustain
strzela. Mocne uderzenie (forte) w klawisz ruchu = bieg. Własny układ: `pianodoom layout --toml > my.toml`,
nazwy klawiszy podejrzysz przez `pianodoom monitor`. Uprawnienia do `/dev/uinput`: reguła w `udev/`.
