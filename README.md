# nux-dsp-mod

Community patches for the DSP firmware of **NUX digital pianos**, without distributing any NUX code.
You bring the official firmware file, the patcher adds the features.
*[Polski poniżej](#po-polsku).*

## Supported firmware

| Instrument | Official file | Target |
|---|---|---|
| NUX NEK-100 | `NEK100_DSP_V1.0.7.bin` (SHA-256 `b072b6bd…3bffc0`) | [`targets/nek100-dsp-1.0.7`](targets/nek100-dsp-1.0.7) |

Other models (NEK-110, …) use the same DSP and a similar firmware. Adding one is described in
[docs/NEW_TARGET.md](docs/NEW_TARGET.md), and `nuxdsp port` does most of the address hunting.

## Patches (NEK-100 1.0.7)

| Patch | What it does |
|---|---|
| `boot_preset` | loads a user preset (default 1) at power-on, where the stock firmware loads the factory default. The preset screen calls it `1.Default` instead of `1.User1` (`DEFAULT_LABEL=0` turns that off) |
| `touch_off` | new Touch setting **OFF**: every note at a fixed velocity (default 127), first in the menu |
| `sustain_in_preset` | the **Sustain** value (pedal level) is saved in user presets |
| `version_tag` | version screen shows `DSP:1.0.7B`, so you can see the mod is installed |
| `polish_font` *(optional, example)* | Polish letters (ąćęłńóśźż ĄĆĘŁŃÓŚŹŻ) in the main UI font, strings in Unicode. A base for translations |
| `lang_pl` *(optional, example)* | buttons and headers ZAPISZ / WCZYTAJ, as a translation proof of concept |

Tested on a real NEK-100, except the new `1.Default` label. Presets saved with the stock firmware keep working.

> **Use at your own risk.** Unofficial, not affiliated with NUX or Dream. Modified firmware may void your
> warranty. Keep the official file: flashing it back restores the original firmware.

## Use it

**Web (no installation):** open the project's GitHub Pages site, or `web/index.html` from a download of
this repository (it works offline, your file never leaves the browser). Select the official DSP file from
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

**Obsługiwane:** NUX NEK-100, plik `NEK100_DSP_V1.0.7.bin`. Inne modele (NEK-110 i pozostałe) mają ten sam
DSP i podobny firmware. Jak dodać kolejny model, opisuje [docs/NEW_TARGET.md](docs/NEW_TARGET.md).

| Patch | Co robi |
|---|---|
| `boot_preset` | ładuje user preset (domyślnie 1) przy włączeniu. Fabrycznie ładuje się ustawienie domyślne. Na ekranie presetów nazywa się `1.Default` zamiast `1.User1` (`DEFAULT_LABEL=0` to wyłącza) |
| `touch_off` | nowe ustawienie Touch **OFF**: każda nuta ze stałą siłą (domyślnie 127), pierwsze w menu |
| `sustain_in_preset` | wartość **Sustain** (poziom pedału) zapisuje się w user presetach |
| `version_tag` | ekran wersji pokazuje `DSP:1.0.7B`, więc widać, że mod jest wgrany |
| `polish_font` *(opcjonalny, przykład)* | polskie litery w głównym foncie UI, napisy w Unicode. Baza pod tłumaczenia |
| `lang_pl` *(opcjonalny, przykład)* | przyciski i nagłówki ZAPISZ / WCZYTAJ jako dowód, że tłumaczenie jest wykonalne |

Przetestowane na prawdziwym NEK-100, poza nową etykietą `1.Default`. Presety zapisane na oryginalnym
firmware dalej działają.

> **Na własne ryzyko.** To nieoficjalny projekt, niezwiązany z NUX ani Dream. Zmodyfikowany firmware może
> naruszać warunki gwarancji. Zachowaj oryginalny plik: wgranie go z powrotem przywraca fabryczny stan.

**Przeglądarka:** otwórz stronę projektu na GitHub Pages albo `web/index.html` z pobranego repozytorium
(działa offline, plik nie opuszcza przeglądarki). Wskaż plik DSP z oficjalnej paczki aktualizacji NUX:
strona rozpozna model i wersję, pokaże dostępne poprawki i da gotowy plik.
**Linia poleceń:** `python3 -m nuxdsp build NEK100_DSP_V1.0.7.bin wynik.bin`, a pozostałe polecenia
są opisane wyżej.
**Wgrywanie:** oficjalnym narzędziem NUX, tak samo jak zwykłą aktualizację DSP. Narzędzie musi pokazać
niezerową ilość zaprogramowanych danych. Na ekranie wersji powinno być `DSP:1.0.7B`.
