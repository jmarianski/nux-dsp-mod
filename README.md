# doom-piano

Play **Doom on a piano**. Any MIDI keyboard over USB works (made with a NUX NEK-100 in mind):
piano keys and pedals become a virtual keyboard, so every Doom source port sees them like a real one.
*[Polski poniżej](#po-polsku).*

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
[nek100-mod](../nek100-mod).

- Step 1, `fb_splash` (works on a real NEK-100): a full-screen test card copied into the framebuffer; the image
  stays until the next full redraw of the main screen.
- Step 2, `fb_test` (`firmware/fbtest.py`, works on a real NEK-100): the card read from far program memory
  (above 0xffff) with the firmware's own copy routine, then a game loop in the 10 ms tick (a whole frame every
  50 ms: sweeping line, bouncing box, numbers) with timings on screen. VOL+/VOL- on the main screen starts and
  stops it. Measured: a whole 128x64 frame (~5000 instructions) renders in ~0.2 ms, a full LCD refresh takes
  ~0.8 ms, so at 20 frames/s a frame has a budget of very roughly 1-2 million instructions.

```sh
python3 firmware/fbtest.py                       # regenerates firmware/fb_test.patch (our own code + data)
cd ../nek100-mod
python3 -m nuxdsp build NEK100_DSP_V1.0.7.bin ../doom-piano/build/NEK100_DSP_fbtest.bin \
    -p boot_preset -p touch_off -p sustain_in_preset -p version_tag -p octave_per_part -p extra_menu \
    -p ../doom-piano/firmware/fb_test.patch
python3 -m nuxdsp flash -y ../doom-piano/build/NEK100_DSP_fbtest.bin   # piano in update mode (needs pyusb)
```

Built files contain NUX code: keep them local (`build/` is ignored). Flash the official file to go back.

## Development

```sh
uv run pytest
```

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
