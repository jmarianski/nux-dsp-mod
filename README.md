# nux-dsp-mod

Community patches for the DSP firmware of **NUX digital pianos**, without distributing any NUX code.
You bring the official firmware file, the patcher adds the features.
*[Polski poniżej](#po-polsku).*

## Supported firmware

| Instrument | Official file | Target |
|---|---|---|
| NUX NEK-100 | `NEK100_DSP_V1.0.7.bin` (SHA-256 `b072b6bd…3bffc0`), inside the official update package from [nuxaudio.com/product/nek100](https://nuxaudio.com/product/nek100/) (Support → Firmware) | [`targets/nek100-dsp-1.0.7`](targets/nek100-dsp-1.0.7) |

Other models (NEK-110, …) use the same DSP and a similar firmware. Adding one is described in
[docs/NEW_TARGET.md](docs/NEW_TARGET.md), and `nuxdsp port` does most of the address hunting.

## Patches (NEK-100 1.0.7)

| Patch | What it does |
|---|---|
| `boot_preset` | loads a user preset (default 1) at power-on, where the stock firmware loads the factory default. On the preset screen it is called `Default` and the others `User1`..`User4`; `PRESET_LABELS` picks the style (with or without the slot number `1.`, or stock names) |
| `touch_off` | new Touch setting **OFF**: every note at a fixed velocity (default 127), first in the menu |
| `touch_custom` *(optional, not a default; needs `touch_off`)* | new Touch setting **CUSTOM** after HARD2: uses HARD2 as input, preserves soft velocities and raises the middle/top earlier. Default: 1–32 unchanged, 48 → 64, 64 → 96, 80 → 127; adjustable `CUSTOM_KNEE`. Tested on a NEK-100 with the default knee. [Details](docs/TOUCH_CUSTOM.md) |
| `sustain_in_preset` | the **Sustain** value (pedal level) is saved in user presets |
| `sustain_midi_out` *(optional)* | the **sustain pedal** also reaches the NUX wireless dongle. Stock, the pedal's CC64 goes to the internal sound and to USB (once per part: channels 1–3) but not to the dongle, while the panel's **Sustain** key reaches both; with this patch the pedal's CC64 also goes to the dongle, the same way the key's does and with what USB gets. Other controllers stay as they are. Pedal and Sustain key are not merged: each sends its own messages, so with the key on, letting go of the pedal sends CC64 0 and releases the sustain inside and outside alike, as stock does inside |
| `octave_per_part` | **Octave** for each part: MAIN, DUAL and SPLIT get their own octave, -3..+3, chosen with the keys under the display like on the Sustain screen. Lets the split's left hand reach the lowest bass while the right plays higher. Saved in user presets |
| `extra_menu` | **Extra** in place of Info in the function menu (in Polish with `lang_pl`), on three pages: **Auto Off** (separate times on battery and on cable: Off, 5, 10, 15, 30, 60, 90, 120 min; stock is 30 min on battery and never on cable, those stay the defaults), **Startup** (what power-on loads: *Default* = the `boot_preset` preset, *Autosave* = the settings you had when you switched off with the power key or by Auto Off, kept in a hidden slot so User1..User5 stay untouched, the **Sustain** key's on/off state included (accompaniment and Live Music on/off are not: the panel's MCU keeps them, and restoring them looks doable but is not done yet), and the panel's factory reset clears the saved state and puts Auto Off and Startup back to their defaults, or *Factory*), **Backlight** (the display light goes off after 5 s, 10 s, 15 s, 30 s, 1 min or 5 min without a panel key or the dial, also while you play, and comes back with the next one; or always off, or always on as stock), **Speaker** (the speaker amplifier switches off 5 s, 30 s or 1 min after the last sound — a key held down, accompaniment, demo, metronome and MIDI keep it on, panel keys do not; with the Sustain key on or the pedal down it waits at least 20 s, while the notes ring on; the idle hiss stops — and back on with the next note; or always on, as stock and the default), **Sleep** (after 30 s, 1 min or 5 min with nothing played, counted as for Speaker, the instrument shows SLEEP and the battery, turns the backlight and speaker off and slows its clock down to the crystal with the PLL stopped — the DSP chip's datasheet gives 6 mA instead of 76 mA; any key, panel key or the dial wakes it, and that first press only wakes it; Off is the default; Auto Off and the other times count real time asleep too, though the clock runs 32 times slower then), **Patches** (which of these patches are installed) and the stock **Info** |
| `version_tag` | version screen shows `DSP:1.0.7B`, so you can see the mod is installed |
| `short_welcome` *(optional)* | shorter welcome screen at power-on: under 1 s instead of about 3 s (the rest is the instrument starting up; adjustable) |
| `welcome_cat` *(optional)* | two cats beside the welcome text on the power-on screen |
| `telemetry` *(optional, off unless you select it)* | usage log for measuring battery life: 5-minute windows of time played, average volume, silence with the speaker on and off, time asleep and the battery reading (sleep and speaker off come from `extra_menu`; without it they stay 0), in flash pages the stock firmware does not use (about 17 days). Nothing leaves the instrument by itself: it is read only on request over USB (below). Listed on the Extra → Patches screen when installed (with `extra_menu`) |
| `polish_font` *(optional)* | Polish letters (ąćęłńóśźż ĄĆĘŁŃÓŚŹŻ) in the main UI font, strings in Unicode. A base for translations |
| `lang_pl` *(optional, needs `polish_font`)* | Polish UI: the 500 sound and 100 demo names, Touch and reverb values, style sections, buttons, screen headers and dialogs |
| `doom_demo` *(optional, needs `extra_menu` and `touch_off`)* | DOOM in Extra (an unofficial port, `doom/`): one map of its own, Hangar, with [Freedoom](https://freedoom.github.io)'s textures, sprites and music (BSD license, in the patch file), the keys move and shoot. The file grows to about 303 KB. DOOM is a trademark of id Software; not affiliated with or endorsed by id |

| `custom_voices` *(added with instruments)* | shows the names of instruments you add to the soundbank (below), in English or, with `lang_pl`, in Polish |

All of them were tested on a real NEK-100. Presets saved with the stock firmware keep working.

**Results: power draw** (NEK-100, measured at the wall socket with a watt meter, battery full, 2026-10-20):

| State | Power |
|---|---|
| on, speaker on | 2.0–2.1 W (about 2.4 W playing at full volume) |
| on, speaker off (`extra_menu` Speaker, or headphones) | about 1 W |
| asleep (`extra_menu` Sleep) | about 0.5 W |
| display backlight on or off | no measurable difference |

The speaker amplifier takes about half of the power while the instrument is on, so switching it off after a silence
saves the most; Sleep halves what is left. Turning the backlight off is about the look, not the battery.

## Add instruments

Both the web page and the command line can put new instruments in place of any of the 500 sounds (up to 4).
For that you also give them the official soundbank file from the same update package
(`NEK100_SBANK_V1.0.4.bin`, SHA-256 `59d5c23b…313b646`), and you get two files to flash: the DSP firmware
and the soundbank. The new sound shows its own name (`500.Cat Piano`). Flashing the official soundbank brings
the original sound back.

Instruments are **SoundFont 2** files (`.sf2`), the common format of free sample libraries; choose one of
the file's presets (`nuxdsp instruments FILE.sf2` lists them, the web page shows a list). Taken over: key ranges,
root keys, tuning, sample rate and loops (sounds that sustain while the key is held). Of several velocity layers
the one at velocity 100 is used; of layers sounding together (e.g. a second one an octave up) each key takes the
first; stereo is mixed to mono. The volume envelope (attack, decay, sustain, release) is the SoundFont's,
converted to the device's own (its rates measured on the NEK-100). The rest of the zone settings come from a
template sound of your own soundbank (a plucked one for one-shots, an organ for looped instruments, for pianos, i.e.
presets on General MIDI programs 1–8, the loudest velocity layer of the Grand Piano, made to follow velocity over the
whole range with its filter open at soft hits, on which they sound much closer to the SoundFont), so the
instruments contain no NUX data; the SoundFont's filters, LFOs and chorus are **not supported yet** (a pad that is
a filtered string sample sounds like the strings). It looks doable: the device's zones have a second envelope in
the same format (flat in pianos and organs, falling in synth basses: most likely the filter's) and blocks that look
like LFO settings, but their meaning is not decoded yet. Drum kits and effects that play the same pitch on every key are
not supported. A loop that clicks on the device but not in the page's preview is in the SoundFont itself (e.g.
loops whose end is louder than their start); the sample layout follows the vendor's rules that keep loops clean. Bundled, in [`instruments/`](instruments):

| Instrument | What | Samples |
|---|---|---|
| `cat_piano` | **Cat Piano** (*Kocie piano*): a toy cat piano meowing, 29 zones over the whole keyboard | "Cat Piano Note C" by Meku A, [Freesound.org](https://freesound.org) via creazilla.com, **CC0 1.0** (public domain); pitched to each key and the attack trimmed |

```sh
python3 -m nuxdsp instruments GeneralUser.sf2               # its presets: @N, zones, size, looped or not
python3 -m nuxdsp build NEK100_DSP_V1.0.7.bin NEK100_DSP_V1.0.7B_mod.bin \
    --sbank NEK100_SBANK_V1.0.4.bin --sbank-out NEK100_SBANK_V1.0.4_mod.bin \
    --voice 500=cat_piano --voice 2=GeneralUser.sf2@19,"Organ","Organy"
python3 -m nuxdsp pack samples/ my.sf2 --name "My Sound" --author ... --license ... --comment "source..."
python3 -m nuxdsp export-sound NEK100_DSP_V1.0.7.bin NEK100_SBANK_V1.0.4.bin 462 pad.sf2   # local tests only
```

`export-sound` turns an official sound into a SoundFont, to compare a conversion with the original. Its samples
are NUX's: keep the file to yourself, do not share or publish it.

**Longer sustain for 1.Grand Piano** (`--sustain 3`, on the page a box in step 3): the factory grand decays in
9–25 s while the key or the pedal is held (the high keys of its velocity 75–84 layer in 2–3 s); the option makes
that N times slower (3: 27–76 s), first evening out zones faster than 9 s. Key release works as before. It changes
only the soundbank (flash it as for instruments); chosen by ear on the NEK-100.

```sh
python3 -m nuxdsp build NEK100_DSP_V1.0.7.bin NEK100_DSP_V1.0.7B_mod.bin \
    --sbank NEK100_SBANK_V1.0.4.bin --sbank-out NEK100_SBANK_V1.0.4_mod.bin --sustain 3 --voice 500=cat_piano
```

**Grander Piano** (`--grander SLOT`, on the page a box in step 3): from F#4 up the factory grand's samples are
one-shots that fade 30 dB within a second, so high notes die out early even with the key or the pedal held. Grander
Piano is 1.Grand Piano with those samples given a loop (0.6 s, starting about 1 s after the hit, its end crossfaded
into the loop's start and levelled so that no repeat is heard), the level before it raised towards one falling with
pitch, and decaying 3 times slower like `--sustain 3`. On sound 1 it replaces 1.Grand Piano in place and takes no
room; on any other sound (e.g. `--grander 2`) it is a copy and 1.Grand Piano stays as it was, at the cost of 11 MB
of the soundbank. It is named "Grander Piano" (custom_voices) unless you give `--grander 2,NAME,POLISH_NAME`; an empty
name keeps the sound's own. The loop's level is evened out every 20 ms, so the beating of the strings does not
pulse with each repeat; attacks quieter or louder than the zones around them (the factory C6 and D#6) are evened out
by up to 3 dB; from C#3 to F4 the envelopes fall slower, up to the time of F#4. C3 and below are as they were.
Chosen by ear on the NEK-100.

```sh
python3 -m nuxdsp build NEK100_DSP_V1.0.7.bin NEK100_DSP_V1.0.7B_mod.bin \
    --sbank NEK100_SBANK_V1.0.4.bin --sbank-out NEK100_SBANK_V1.0.4_mod.bin --grander 2 --voice 500=cat_piano
```

### Where to get SoundFonts

- **[GeneralUser GS](https://github.com/mrbumpy409/GeneralUser-GS)** (`GeneralUser-GS.sf2`, ~30 MB, 261
  instruments): a good all-round General MIDI bank, free to use. A good first choice.
- **FluidR3_GM** (~140 MB, MIT license): the Linux package `fluid-soundfont-gm` (file
  `/usr/share/sounds/sf2/FluidR3_GM.sf2`), also bundled with many players.
- **[Polyphone's soundfont library](https://www.polyphone.io/en/soundfonts)**: single instruments by category
  (pianos, organs, strings, …), with license filters.
- **[Musical Artifacts](https://musical-artifacts.com)**: a catalogue of free SoundFonts and other instruments.
- Single samples (e.g. [Freesound](https://freesound.org), filter by license): make a SoundFont with `pack` below.

A big General MIDI bank is fine: only the chosen preset's samples go into the soundbank, and the page (or
`nuxdsp instruments`) shows their size before you build. For organs, strings, pads and other sounds that should
last while the key is held, choose presets marked *looped*. For your own instrument any SoundFont will do; to
share the result, check its license.

`pack` makes a SoundFont from `r<midi>.wav` files (mono, 16-bit, 44.1 kHz), each sample at its root key, e.g.
`r60.wav`. The soundbank grows by the size of the samples (the cat: 2 MB). Its flash partition holds 223 MB and the
official soundbank takes 208 MB, so about 15 MB are left for everything added (the tools refuse a bigger result).
Names: at most 11 characters, and with the sound number at most 15.

> **Use at your own risk.** Unofficial, not affiliated with NUX or Dream. Modified firmware may void your
> warranty. Keep the official file: flashing it back restores the original firmware.

## Use it

**Web (no installation):** open **https://jmarianski.github.io/nux-dsp-mod/**, or `web/index.html` from a
download of this repository (it works offline, your file never leaves the browser). Select the official DSP file from
the NUX update package; the page recognises the model and version, shows its patches, and gives you the
patched file.

**Command line (Python 3.8+, no dependencies):**

```sh
python3 -m nuxdsp targets                                   # supported firmware files
python3 -m nuxdsp verify NEK100_DSP_V1.0.7.bin
python3 -m nuxdsp list
python3 -m nuxdsp build NEK100_DSP_V1.0.7.bin NEK100_DSP_V1.0.7B_mod.bin      # default patches
python3 -m nuxdsp build NEK100_DSP_V1.0.7.bin out.bin -p boot_preset -p version_tag --param BOOT_PRESET=2
```

Both detect the target from the file's SHA-256 and refuse anything else.

**Flashing:** use the official NUX update tool and procedure for the DSP firmware, selecting the patched
file instead of the original. Make sure the tool reports a non-zero amount programmed. Afterwards check
*version* on the instrument: it should say `DSP:1.0.7B`. To go back, flash the official file the same way.

**Flashing on Linux (or macOS), without the Windows tool:** `nuxdsp flash` speaks the instrument's update
protocol (Dream RPC) over USB; it needs `pip install pyusb`. Switch the instrument on in update mode (hold
Power + VOL+ + VOL- for about half a second), then:

```sh
sudo cp udev/70-nux-dfu.rules /etc/udev/rules.d/ && sudo udevadm control --reload   # once, Linux: no root needed after
python3 -m nuxdsp dfu-info                                   # what the instrument offers (read only)
python3 -m nuxdsp flash --dry-run NEK100_DSP_V1.0.7B_mod.bin # checks the file against the instrument, sends nothing
python3 -m nuxdsp flash NEK100_DSP_V1.0.7B_mod.bin
```

The range comes from the file (DSP firmware, soundbank or style); a DSP file must pass its checksum. When it
is done, switch the instrument off and on and check *version*. Tested with the DSP firmware; the soundbank
and style the same way, but not yet tried.

**Usage log (`telemetry`, opt-in):** with that patch the instrument keeps a log in flash pages the stock firmware does not use: 5-minute
windows with time played, average volume, silence with the speaker on and off, time asleep and the battery
reading at the window's end (about 17 days, the oldest overwritten). Read it with the instrument connected over
USB (Linux, find the port with `amidi -l`):

```sh
amidi -p hw:2,0,0 -S 'AF 7D 4E' -r log.syx -t 30     # the request, then 30 s of the dump
python3 -m nuxdsp telemetry log.syx                  # summary; --csv log.csv for every window
```

Or in the browser, without installing anything: **https://jmarianski.github.io/nux-dsp-mod/log.html** (Web MIDI:
Chrome, Edge, Firefox) sends the request, shows the summary and every window, and saves CSV. It also estimates battery drain
(ADC per hour asleep and per hour switched on, playing vs pauses once the sessions allow it) and the hours from
full to the low-battery power-off; a saved `.syx` can be opened there too.
The request is a poly pressure on channel 16, the dump comes as channel 16 messages (one packet per 10 ms tick,
so about 1 s per written page and up to ~16 min for a full ring; `-t` is how many seconds of silence end amidi).

## Make your own patches

`disasm` produces an annotated listing of *your* firmware that assembles back byte for byte. Keep it
local and don't share it. `asm` builds it back, and `extract` turns a working experiment into a small
`.patch` file you can share.
See [docs/PATCHING.md](docs/PATCHING.md), [docs/ISA.md](docs/ISA.md),
[docs/FIRMWARE_MAP.md](docs/FIRMWARE_MAP.md) and [CONTRIBUTING.md](CONTRIBUTING.md).

```
nuxdsp/            the tools (container, ISA, assembler, disassembler, patcher, simulator, port, web export)
targets/<id>/      one directory per supported firmware file: target.map + patches/
web/               the patcher page: index.html, patcher.js, generated targets/<id>.js
docs/              ISA, map format, writing patches, adding a target, legal notes
doom/              the doom_demo patch's source: our C compiler for the P16, the engine, the Hangar map, the
                   browser simulator (formerly the doom-piano repo; see doom/README.md and doom/docs/DOOM.md)
```

Tests: `python3 -m unittest discover -s tests -t .`. Set `NEK100_FW=/path/to/NEK100_DSP_V1.0.7.bin`
for the firmware tests; the web test needs `node`; `NUXDSP_SLOW=1` adds the slow ones (soundbank rendering,
every patch subset). `doom/` has its own suite: `cd doom && uv run pytest -q`
(Freedoom Phase 1 at `doom/wad/freedoom1.wad`); after changing it, `python3 doom/tools/exportpatch.py` writes
`doom_demo.patch` and `python3 -m nuxdsp web NEK100_DSP_V1.0.7.bin` the web data.

Legal background: [docs/LEGAL.md](docs/LEGAL.md). License: MIT.

---

## Po polsku

Poprawki społeczności do firmware DSP pianin cyfrowych **NUX**. Projekt nie rozpowszechnia kodu NUX:
oficjalny plik firmware masz u siebie, a patcher dokłada do niego funkcje.

**Obsługiwane:** NUX NEK-100, plik `NEK100_DSP_V1.0.7.bin` z oficjalnej paczki aktualizacji
([nuxaudio.com/product/nek100](https://nuxaudio.com/product/nek100/), sekcja Support → Firmware). Inne modele (NEK-110 i pozostałe) mają ten sam
DSP i podobny firmware. Jak dodać kolejny model, opisuje [docs/NEW_TARGET.md](docs/NEW_TARGET.md).

| Patch | Co robi |
|---|---|
| `boot_preset` | ładuje user preset (domyślnie 1) przy włączeniu. Fabrycznie ładuje się ustawienie domyślne. Na ekranie presetów nazywa się `Default`, a pozostałe `User1`..`User4`; `PRESET_LABELS` wybiera styl (z numerem slotu `1.` lub bez, albo nazwy fabryczne) |
| `touch_off` | nowe ustawienie Touch **OFF**: każda nuta ze stałą siłą (domyślnie 127), pierwsze w menu |
| `touch_custom` *(opcjonalny, nie domyślny; wymaga `touch_off`)* | **CUSTOM** za MOCNY+: korzysta z MOCNEGO+ jako wejścia, zachowuje ciche velocity i wcześniej podnosi środek/górę. Domyślnie 1–32 bez zmian, 48 → 64, 64 → 96, 80 → 127; parametr `CUSTOM_KNEE`. Sprawdzony na NEK-100 z domyślnym progiem. [Opis](docs/TOUCH_CUSTOM.md) |
| `sustain_in_preset` | wartość **Sustain** (poziom pedału) zapisuje się w user presetach |
| `sustain_midi_out` *(opcjonalny)* | **pedał sustain** dochodzi też do bezprzewodowego dongla NUX. Fabrycznie CC64 pedału idzie do wewnętrznego brzmienia i na USB (raz na partię: kanały 1–3), ale nie do dongla, a przycisk **Sustain** na panelu dochodzi tu i tu; z tym patchem CC64 pedału idzie też do dongla, tą samą drogą co przycisku i z tym, co dostaje USB. Inne kontrolery bez zmian. Pedał i przycisk Sustain nie są łączone: każdy wysyła swoje, więc przy włączonym przycisku puszczenie pedału wysyła CC64 0 i zwalnia sustain w środku i na zewnątrz tak samo, jak fabrycznie w środku |
| `octave_per_part` | osobna **oktawa** dla MAIN, DUAL i SPLIT, zakres -3..+3, wybór partii przyciskami pod ekranem jak w menu Sustain. W splicie lewa ręka sięga najniższych basów, a prawa gra wyżej. Zapisuje się w user presetach |
| `extra_menu` | **Extra** (po polsku „Dodatki” z `lang_pl`) w miejscu Info w menu funkcji, na trzech stronach: **Auto Off** (osobny czas wyłączenia na baterii i na kablu: Off, 5, 10, 15, 30, 60, 90, 120 min; fabrycznie 30 min na baterii, a na kablu nigdy, i to są ustawienia domyślne), **Start** (co ładuje się po włączeniu: *Default* = preset z `boot_preset`, *Autozapis* = ustawienia sprzed wyłączenia przyciskiem lub przez Auto Off, trzymane w ukrytym slocie, więc User1..User5 zostają nietknięte, razem ze stanem przycisku **Sustain** (włączony akompaniament i Live Music nie wracają: trzyma je MCU panelu; wygląda to na wykonalne, ale jeszcze tego nie zrobiliśmy), a reset fabryczny z panelu kasuje zapisany stan i przywraca domyślne Auto Off i Start, albo *Fabryczne*), **Podświetlenie** (światło ekranu gaśnie po 5 s, 10 s, 15 s, 30 s, 1 min lub 5 min bez przycisku panelu i pokrętła, także w trakcie grania, i wraca przy następnym; albo zawsze wyłączone, albo zawsze włączone jak fabrycznie), **Głośnik** (wzmacniacz głośnika wyłącza się 5 s, 30 s lub 1 min po ostatnim dźwięku — włączony trzymają go wciśnięte klawisze, akompaniament, demo, metronom i MIDI, a przyciski panelu nie; z włączonym Sustain albo wciśniętym pedałem czeka co najmniej 20 s, póki nuty wybrzmiewają; znika szum w ciszy — i wraca z następną nutą; albo zawsze włączony, jak fabrycznie i domyślnie), **Uśpienie** (po 30 s, 1 min lub 5 min, w których nic nie gra (liczone jak przy Głośniku), instrument pokazuje UŚPIENIE i baterię, wyłącza podświetlenie i głośnik i zwalnia zegar do kwarcu z zatrzymaną pętlą PLL; według karty katalogowej układ DSP pobiera wtedy 6 mA zamiast 76 mA; budzi go dowolny klawisz, przycisk panelu lub pokrętło, a to pierwsze naciśnięcie tylko budzi; domyślnie wyłączone; Auto Off i inne czasy liczą we śnie czas rzeczywisty, choć zegar chodzi wtedy 32 razy wolniej), **Patche** (które z tych patchy są wgrane) i fabryczne **Info** |
| `version_tag` | ekran wersji pokazuje `DSP:1.0.7B`, więc widać, że mod jest wgrany |
| `short_welcome` *(opcjonalny)* | krótszy ekran powitalny po włączeniu: poniżej 1 s zamiast ok. 3 s (resztę zajmuje uruchamianie instrumentu; do ustawienia) |
| `welcome_cat` *(opcjonalny)* | dwa kotki obok powitania na ekranie startowym |
| `telemetry` *(opcjonalny, wyłączony, dopóki go nie wybierzesz)* | dziennik użycia do mierzenia czasu pracy na baterii: okna po 5 minut z czasem grania, średnią głośnością, ciszą z włączonym i wyłączonym głośnikiem, czasem uśpienia i odczytem baterii (uśpienie i wyłączony głośnik pochodzą z `extra_menu`; bez niego zostają 0), w stronach flasha nieużywanych przez fabryczny firmware (około 17 dni). Nic nie wychodzi z instrumentu samo: odczyt tylko na żądanie przez USB (niżej). Widoczny na ekranie Dodatki → Patche, gdy jest wgrany (z `extra_menu`) |
| `polish_font` *(opcjonalny)* | polskie litery w głównym foncie UI, napisy w Unicode. Baza pod tłumaczenia |
| `lang_pl` *(opcjonalny, wymaga `polish_font`)* | polski interfejs: 500 nazw brzmień i 100 dem, wartości Touch i pogłosu, sekcje stylów, przyciski, nagłówki ekranów i okna dialogowe |
| `doom_demo` *(opcjonalny, wymaga `extra_menu` i `touch_off`)* | DOOM w Dodatkach (nieoficjalny port, `doom/`): jedna własna mapa, Hangar, z teksturami, sprite'ami i muzyką [Freedoom](https://freedoom.github.io) (licencja BSD, w pliku patcha), klawisze chodzą i strzelają. Plik rośnie do ok. 303 KB. DOOM to znak towarowy id Software; projekt nie jest z nim związany |

| `custom_voices` *(dodawany z instrumentami)* | pokazuje nazwy instrumentów dodanych do soundbanku (niżej), po angielsku albo z `lang_pl` po polsku |

Wszystkie patche są przetestowane na prawdziwym NEK-100. Presety zapisane na oryginalnym
firmware dalej działają.

**Wyniki: pobór mocy** (NEK-100, pomiar watomierzem z gniazdka, bateria naładowana, 2026-10-20):

| Stan | Pobór |
|---|---|
| włączony, głośnik włączony | 2,0–2,1 W (ok. 2,4 W przy grze na pełnej głośności) |
| włączony, głośnik wyłączony (`extra_menu` Głośnik albo słuchawki) | ok. 1 W |
| uśpienie (`extra_menu` Uśpienie) | ok. 0,5 W |
| podświetlenie ekranu włączone lub wyłączone | bez mierzalnej różnicy |

Wzmacniacz głośnika to mniej więcej połowa poboru na włączonym instrumencie, więc najwięcej daje wyłączanie go po
ciszy, a uśpienie zmniejsza resztę o połowę. Gaszenie podświetlenia to kwestia wygody, nie baterii.

**Własne instrumenty:** strona i linia poleceń potrafią wstawić nowe instrumenty w miejsce dowolnego z 500 brzmień
(do 4). Trzeba im dać też oryginalny plik soundbanku z tej samej paczki aktualizacji (`NEK100_SBANK_V1.0.4.bin`)
i wgrać dwa pliki wynikowe: firmware DSP i soundbank. Nowe brzmienie ma własną nazwę (`500.Kocie piano`), a
wgranie oryginalnego soundbanku przywraca dawne brzmienie. Instrumenty to pliki **SoundFont 2** (`.sf2`), popularny format darmowych bibliotek
sampli. Z pliku wybierasz jeden preset; przenoszone są zakresy klawiszy, strojenie, częstotliwość próbkowania i pętle
(dźwięk trwa, dopóki trzymasz klawisz). Z warstw dynamiki brana jest ta dla siły 100, z warstw grających razem (np. druga o oktawę wyżej) każdy klawisz
bierze pierwszą, a stereo jest miksowane do mono.
Obwiednia głośności (atak, opadanie, podtrzymanie, wybrzmienie) pochodzi z pliku SF2, przeliczona na obwiednię
urządzenia (jej tempa zmierzone na NEK-100). Pozostałe ustawienia strefy pochodzą z brzmienia-szablonu Twojego soundbanku
(szarpanego dla dźwięków bez pętli, organów dla tych z pętlą, a dla pianin, czyli presetów na programach General MIDI 1–8,
najgłośniejsza warstwa velocity Grand Piano, reagująca na siłę uderzenia w całym zakresie, z filtrem otwartym także
przy cichych uderzeniach, na której brzmią dużo bliżej oryginału), więc instrumenty nie zawierają danych NUX. Filtrów, LFO i
chorusa z SF2 **jeszcze nie obsługujemy** (pad zrobiony z przefiltrowanych smyczków zabrzmi jak smyczki). Wygląda to na
wykonalne: strefy urządzenia mają drugą obwiednię w tym samym formacie (płaską w pianinach i organach, opadającą w
syntezatorowych basach, więc najpewniej filtra) i bloki przypominające ustawienia LFO, ale ich znaczenia jeszcze nie
rozszyfrowaliśmy. Jeśli pętla stuka na
urządzeniu tak samo jak w podglądzie na stronie, to cecha samego pliku SF2 (np. koniec pętli głośniejszy niż początek);
ułożenie sampli trzyma się reguł producenta, przy których pętle grają czysto.
Perkusje i efekty grające tę samą wysokość na każdym klawiszu nie są obsługiwane. W repozytorium jest **Kocie piano**
(`cat_piano`): miauczące zabawkowe pianino, nagranie „Cat Piano Note C” autorstwa Meku A z Freesound.org (przez
creazilla.com), licencja **CC0** (domena publiczna), przestrojone na każdy klawisz, z przyciętym atakiem. **Skąd brać pliki
.sf2:** na początek [GeneralUser GS](https://github.com/mrbumpy409/GeneralUser-GS) (ok. 30 MB, 261 instrumentów, darmowy),
dalej FluidR3_GM (licencja MIT, w Linuksie pakiet `fluid-soundfont-gm`), pojedyncze instrumenty w
[bibliotece Polyphone](https://www.polyphone.io/en/soundfonts) (kategorie i filtr licencji) albo katalog
[Musical Artifacts](https://musical-artifacts.com). Duży bank GM nie przeszkadza, bo do soundbanku trafiają tylko sample
wybranego presetu, a strona pokazuje ich rozmiar. Do organów, smyczków i padów wybieraj presety oznaczone jako „z pętlą”.
SoundFont z własnych sampli (np. z [Freesound](https://freesound.org)) robi `python3 -m nuxdsp pack` (opis wyżej). `nuxdsp export-sound` zapisuje fabryczne brzmienie jako SF2 do porównań; to sample NUX, więc taki plik zostaje u Ciebie, nie udostępniaj go. Soundbank rośnie o rozmiar sampli.
Partycja flash mieści 223 MB, a oryginalny soundbank zajmuje 208 MB, więc na wszystko, co dodajesz, zostaje około 15 MB
(narzędzia odmówią, jeśli wynik będzie większy).

**Dłuższe wybrzmiewanie 1.Grand Piano** (`--sustain 3`, na stronie pole w kroku 3): fabryczny fortepian przy
trzymanym klawiszu lub pedale wygasa w 9–25 s (a wysokie dźwięki warstwy velocity 75–84 w 2–3 s); opcja zwalnia to
N razy (3: 27–76 s), wcześniej wyrównując strefy szybsze niż 9 s. Puszczenie klawisza działa jak dotąd. Zmienia
tylko soundbank (wgrywasz go jak instrumenty); brzmienie dobrane na słuch na NEK-100.

**Grander Piano** (`--grander SLOT`, na stronie pole w kroku 3): od F#4 w górę fabryczne sample fortepianu
wybrzmiewają tylko raz i cichną o 30 dB w ciągu sekundy, więc wysokie dźwięki gasną szybko nawet przy trzymanym
klawiszu albo pedale. Grander Piano to 1.Grand Piano, w którym te sample dostały pętlę: 0,6 s, zaczyna się ok. 1 s po
uderzeniu, a jej koniec płynnie przechodzi w początek i ma wyrównany poziom, żeby nie było słychać powtórzeń.
Poziom przed pętlą jest podniesiony do wartości, która maleje z wysokością dźwięku, a całość wybrzmiewa 3 razy wolniej, jak
z `--sustain 3`. Na brzmieniu 1 zastępuje 1.Grand Piano i nie zajmuje miejsca. Na innym brzmieniu (np.
`--grander 2`) jest kopią, a 1.Grand Piano zostaje bez zmian, kosztem 11 MB soundbanku. Nazywa się „Grander Piano”
(custom_voices), chyba że podasz `--grander 2,NAZWA,NAZWA_PL`; pusta nazwa zostawia nazwę brzmienia. Poziom
w pętli jest wyrównywany co 20 ms, żeby dudnienie strun nie pulsowało przy każdym powtórzeniu. Ataki cichsze lub
głośniejsze od sąsiednich stref (fabrycznie C6 i D#6) są wyrównane o najwyżej 3 dB. Od C#3 do F4 obwiednie gasną
wolniej, stopniowo do czasu z F#4. C3 i niżej zostają bez zmian. Brzmienie dobrane na słuch na NEK-100.

> **Na własne ryzyko.** To nieoficjalny projekt, niezwiązany z NUX ani Dream. Zmodyfikowany firmware może
> naruszać warunki gwarancji. Zachowaj oryginalny plik: wgranie go z powrotem przywraca fabryczny stan.

**Przeglądarka:** otwórz **https://jmarianski.github.io/nux-dsp-mod/** albo `web/index.html` z pobranego repozytorium
(działa offline, plik nie opuszcza przeglądarki). Wskaż plik DSP z oficjalnej paczki aktualizacji NUX:
strona rozpozna model i wersję, pokaże dostępne poprawki i da gotowy plik.
**Linia poleceń:** `python3 -m nuxdsp build NEK100_DSP_V1.0.7.bin wynik.bin`, a pozostałe polecenia
są opisane wyżej.
**Wgrywanie:** oficjalnym narzędziem NUX, tak samo jak zwykłą aktualizację DSP. Narzędzie musi pokazać
niezerową ilość zaprogramowanych danych. Na ekranie wersji powinno być `DSP:1.0.7B`.
**Wgrywanie pod Linuksem (albo macOS), bez windowsowego narzędzia:** `python3 -m nuxdsp flash plik.bin`
(potrzebuje `pip install pyusb`). Instrument włącz w trybie aktualizacji (Power + VOL+ + VOL− przez około pół
sekundy); pod Linuksem raz skopiuj `udev/70-nux-dfu.rules` do `/etc/udev/rules.d/`, wtedy root nie jest potrzebny.
`--dry-run` sprawdza plik z instrumentem i niczego nie wysyła. Po wgraniu wyłącz i włącz instrument.
Sprawdzone z firmware DSP; soundbank i style idą tak samo, ale jeszcze ich nie próbowaliśmy.
**Dziennik użycia (`telemetry`, tylko gdy go wybierzesz):** instrument z tym patchem zapisuje we flashu, w stronach nieużywanych przez fabryczny firmware,
okna po 5 minut: czas grania, średnią głośność, ciszę z włączonym i wyłączonym głośnikiem, czas uśpienia i odczyt
baterii (około 17 dni, najstarsze są nadpisywane). Odczyt przez USB: `amidi -p hw:2,0,0 -S 'AF 7D 4E' -r log.syx -t 30`
(port z `amidi -l`), potem `python3 -m nuxdsp telemetry log.syx`, albo w przeglądarce:
**https://jmarianski.github.io/nux-dsp-mod/log.html** (tam też szacunek zużycia baterii: ADC na godzinę
uśpienia i włączenia, granie kontra pauzy, godziny od pełnej do wyłączenia; można też otworzyć zapisany `.syx`).
Każda zapisana strona to około 1 s transmisji, pełny ring do ~16 min (`-t` = po ilu sekundach ciszy amidi kończy).
