# nek100-mod

Community patches for the **NUX NEK-100** digital piano DSP firmware **V1.0.7** — without distributing
any NUX code. You bring the official firmware file, the patcher adds the features.
*[Polski poniżej](#po-polsku).*

| Patch | What it does |
|---|---|
| `boot_preset` | loads a user preset (default 1) at power-on — the stock firmware loads the factory default |
| `touch_off` | new Touch setting **OFF**: every note at a fixed velocity (default 127), first in the menu |
| `sustain_in_preset` | the **Sustain** value (pedal level) is saved in user presets |
| `version_tag` | version screen shows `DSP:V9.0.7`, so you can see the mod is installed |

All of them were tested on a real NEK-100. Presets saved with the stock firmware keep working.

> **Use at your own risk.** Unofficial, not affiliated with NUX or Dream. Modified firmware may void your
> warranty. Keep the official file — flashing it back restores the original firmware.

## Use it

**Web (no installation):** open [`web/nek100-patcher.html`](web/nek100-patcher.html) in a browser (it works
offline), select `NEK100_DSP_V1.0.7.bin` from the official NUX update package, choose the patches,
download the result.

**Command line (Python 3.8+, no dependencies):**

```sh
python3 -m nek100mod verify NEK100_DSP_V1.0.7.bin
python3 -m nek100mod list
python3 -m nek100mod build NEK100_DSP_V1.0.7.bin NEK100_DSP_mod.bin                 # all patches
python3 -m nek100mod build NEK100_DSP_V1.0.7.bin out.bin -p boot_preset -p version_tag --param BOOT_PRESET=2
```

Both refuse any input other than the official V1.0.7 file (SHA-256 `b072b6bd…3bffc0`).

**Flashing:** use the official NUX update tool and procedure for the DSP firmware, selecting the patched
file instead of the original. Make sure the tool reports a non-zero amount programmed. Afterwards check
*version* on the instrument: it should say `DSP:V9.0.7`. To go back, flash the official file the same way.

## Make your own patches

`disasm` produces an annotated, re-assemblable listing of *your* firmware (for local use — don't share
it); `asm` builds it back byte-for-byte; `extract` turns a working experiment into a small `.patch` file
you can share. See [docs/PATCHING.md](docs/PATCHING.md), [docs/ISA.md](docs/ISA.md),
[docs/FIRMWARE_MAP.md](docs/FIRMWARE_MAP.md). Contributions to the map and new patches are welcome.

Tests: `python3 -m unittest discover -s tests -t .` (set `NEK100_FW=/path/to/NEK100_DSP_V1.0.7.bin` for the
firmware tests; the web test needs `node`). After changing a patch, regenerate the page with
`python3 -m nek100mod web NEK100_DSP_V1.0.7.bin web/nek100-patcher.html`.

Legal background: [docs/LEGAL.md](docs/LEGAL.md). License: MIT.

---

## Po polsku

Poprawki społeczności do firmware DSP pianina **NUX NEK-100** w wersji **V1.0.7**. Projekt nie
rozpowszechnia kodu NUX: oficjalny plik firmware masz u siebie, a patcher dokłada do niego funkcje.

| Patch | Co robi |
|---|---|
| `boot_preset` | ładuje user preset (domyślnie 1) przy włączeniu. Fabrycznie ładuje się ustawienie domyślne |
| `touch_off` | nowe ustawienie Touch **OFF**: każda nuta ze stałą siłą (domyślnie 127), pierwsze w menu |
| `sustain_in_preset` | wartość **Sustain** (poziom pedału) zapisuje się w user presetach |
| `version_tag` | ekran wersji pokazuje `DSP:V9.0.7`, więc widać, że mod jest wgrany |

Wszystkie patche są przetestowane na prawdziwym NEK-100. Presety zapisane na oryginalnym firmware dalej działają.

> **Na własne ryzyko.** To nieoficjalny projekt, niezwiązany z NUX ani Dream. Zmodyfikowany firmware może
> naruszać warunki gwarancji. Zachowaj oryginalny plik: wgranie go z powrotem przywraca fabryczny stan.

**Przeglądarka:** otwórz `web/nek100-patcher.html` (działa offline) i wskaż `NEK100_DSP_V1.0.7.bin`
z oficjalnej paczki aktualizacji NUX. Zaznacz poprawki i pobierz wynik.
**Linia poleceń:** `python3 -m nek100mod build NEK100_DSP_V1.0.7.bin wynik.bin`, a pozostałe polecenia
są opisane wyżej.

**Wgrywanie:** użyj oficjalnego narzędzia i procedury aktualizacji DSP od NUX, wskazując zmodyfikowany
plik. Sprawdź, czy narzędzie zgłasza niezerową ilość zaprogramowanych danych. Na instrumencie ekran wersji
powinien pokazać `DSP:V9.0.7`. Powrót do oryginału to wgranie oficjalnego pliku w ten sam sposób.

Własne patche, mapa firmware i ISA są opisane w `docs/` (po angielsku). Podstawy prawne: `docs/LEGAL.md`.
