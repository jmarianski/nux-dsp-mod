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
| `sustain_in_preset` | the **Sustain** value (pedal level) is saved in user presets |
| `octave_per_part` | **Octave** for each part: MAIN, DUAL and SPLIT get their own octave, -3..+3, chosen with the keys under the display like on the Sustain screen. Lets the split's left hand reach the lowest bass while the right plays higher. Saved in user presets |
| `extra_menu` | **Extra** in place of Info in the function menu (in Polish with `lang_pl`), with four items: **Auto Off** (separate times on battery and on cable: Off, 5, 10, 15, 30, 60, 90, 120 min; stock is 30 min on battery and never on cable, those stay the defaults), **Startup** (what power-on loads: *Default* = the `boot_preset` preset, *Autosave* = the settings you had when you switched off with the power key or by Auto Off, kept in a hidden slot so User1..User5 stay untouched, or *Factory*), **Patches** (which of these patches are installed) and the stock **Info** |
| `version_tag` | version screen shows `DSP:1.0.7B`, so you can see the mod is installed |
| `polish_font` *(optional)* | Polish letters (ąćęłńóśźż ĄĆĘŁŃÓŚŹŻ) in the main UI font, strings in Unicode. A base for translations |
| `lang_pl` *(optional, needs `polish_font`)* | Polish UI: the 500 sound and 100 demo names, Touch and reverb values, style sections, buttons, screen headers and dialogs |

All of them were tested on a real NEK-100. Presets saved with the stock firmware keep working.

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
```

Tests: `python3 -m unittest discover -s tests -t .`. Set `NEK100_FW=/path/to/NEK100_DSP_V1.0.7.bin`
for the firmware tests; the web test needs `node`.

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
| `sustain_in_preset` | wartość **Sustain** (poziom pedału) zapisuje się w user presetach |
| `octave_per_part` | osobna **oktawa** dla MAIN, DUAL i SPLIT, zakres -3..+3, wybór partii przyciskami pod ekranem jak w menu Sustain. W splicie lewa ręka sięga najniższych basów, a prawa gra wyżej. Zapisuje się w user presetach |
| `extra_menu` | **Extra** (po polsku „Dodatki” z `lang_pl`) w miejscu Info w menu funkcji, z czterema pozycjami: **Auto Off** (osobny czas wyłączenia na baterii i na kablu: Off, 5, 10, 15, 30, 60, 90, 120 min; fabrycznie 30 min na baterii, a na kablu nigdy, i to są ustawienia domyślne), **Start** (co ładuje się po włączeniu: *Default* = preset z `boot_preset`, *Autozapis* = ustawienia sprzed wyłączenia przyciskiem lub przez Auto Off, trzymane w ukrytym slocie, więc User1..User5 zostają nietknięte, albo *Fabryczne*), **Patche** (które z tych patchy są wgrane) i fabryczne **Info** |
| `version_tag` | ekran wersji pokazuje `DSP:1.0.7B`, więc widać, że mod jest wgrany |
| `polish_font` *(opcjonalny)* | polskie litery w głównym foncie UI, napisy w Unicode. Baza pod tłumaczenia |
| `lang_pl` *(opcjonalny, wymaga `polish_font`)* | polski interfejs: 500 nazw brzmień i 100 dem, wartości Touch i pogłosu, sekcje stylów, przyciski, nagłówki ekranów i okna dialogowe |

Wszystkie patche są przetestowane na prawdziwym NEK-100. Presety zapisane na oryginalnym
firmware dalej działają.

> **Na własne ryzyko.** To nieoficjalny projekt, niezwiązany z NUX ani Dream. Zmodyfikowany firmware może
> naruszać warunki gwarancji. Zachowaj oryginalny plik: wgranie go z powrotem przywraca fabryczny stan.

**Przeglądarka:** otwórz **https://jmarianski.github.io/nux-dsp-mod/** albo `web/index.html` z pobranego repozytorium
(działa offline, plik nie opuszcza przeglądarki). Wskaż plik DSP z oficjalnej paczki aktualizacji NUX:
strona rozpozna model i wersję, pokaże dostępne poprawki i da gotowy plik.
**Linia poleceń:** `python3 -m nuxdsp build NEK100_DSP_V1.0.7.bin wynik.bin`, a pozostałe polecenia
są opisane wyżej.
**Wgrywanie:** oficjalnym narzędziem NUX, tak samo jak zwykłą aktualizację DSP. Narzędzie musi pokazać
niezerową ilość zaprogramowanych danych. Na ekranie wersji powinno być `DSP:1.0.7B`.
