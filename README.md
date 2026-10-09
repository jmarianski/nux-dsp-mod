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
| `extra_menu` | **Extra** in place of Info in the function menu (in Polish with `lang_pl`), with four items: **Auto Off** (separate times on battery and on cable: Off, 5, 10, 15, 30, 60, 90, 120 min; stock is 30 min on battery and never on cable, those stay the defaults), **Startup** (what power-on loads: *Default* = the `boot_preset` preset, *Autosave* = the settings you had when you switched off with the power key or by Auto Off, kept in a hidden slot so User1..User5 stay untouched, the **Sustain** key's on/off state included (accompaniment and Live Music on/off are not: the panel's MCU keeps them, and restoring them looks doable but is not done yet), or *Factory*), **Patches** (which of these patches are installed) and the stock **Info** |
| `version_tag` | version screen shows `DSP:1.0.7B`, so you can see the mod is installed |
| `short_welcome` *(optional)* | shorter welcome screen at power-on: 1 s instead of 3 s (adjustable) |
| `welcome_cat` *(optional)* | two cats beside the welcome text on the power-on screen |
| `polish_font` *(optional)* | Polish letters (ąćęłńóśźż ĄĆĘŁŃÓŚŹŻ) in the main UI font, strings in Unicode. A base for translations |
| `lang_pl` *(optional, needs `polish_font`)* | Polish UI: the 500 sound and 100 demo names, Touch and reverb values, style sections, buttons, screen headers and dialogs |

| `custom_voices` *(added with instruments)* | shows the names of instruments you add to the soundbank (below), in English or, with `lang_pl`, in Polish |

All of them were tested on a real NEK-100. Presets saved with the stock firmware keep working.

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
template sound of your own soundbank (a plucked one for one-shots, an organ for looped instruments), so the
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
`r60.wav`. The soundbank grows by the size of the samples (the cat: 2 MB); how much room the instrument's flash
has is not known yet, so start small.
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
| `extra_menu` | **Extra** (po polsku „Dodatki” z `lang_pl`) w miejscu Info w menu funkcji, z czterema pozycjami: **Auto Off** (osobny czas wyłączenia na baterii i na kablu: Off, 5, 10, 15, 30, 60, 90, 120 min; fabrycznie 30 min na baterii, a na kablu nigdy, i to są ustawienia domyślne), **Start** (co ładuje się po włączeniu: *Default* = preset z `boot_preset`, *Autozapis* = ustawienia sprzed wyłączenia przyciskiem lub przez Auto Off, trzymane w ukrytym slocie, więc User1..User5 zostają nietknięte, razem ze stanem przycisku **Sustain** (włączony akompaniament i Live Music nie wracają: trzyma je MCU panelu; wygląda to na wykonalne, ale jeszcze tego nie zrobiliśmy), albo *Fabryczne*), **Patche** (które z tych patchy są wgrane) i fabryczne **Info** |
| `version_tag` | ekran wersji pokazuje `DSP:1.0.7B`, więc widać, że mod jest wgrany |
| `short_welcome` *(opcjonalny)* | krótszy ekran powitalny po włączeniu: 1 s zamiast 3 s (do ustawienia) |
| `welcome_cat` *(opcjonalny)* | dwa kotki obok powitania na ekranie startowym |
| `polish_font` *(opcjonalny)* | polskie litery w głównym foncie UI, napisy w Unicode. Baza pod tłumaczenia |
| `lang_pl` *(opcjonalny, wymaga `polish_font`)* | polski interfejs: 500 nazw brzmień i 100 dem, wartości Touch i pogłosu, sekcje stylów, przyciski, nagłówki ekranów i okna dialogowe |

| `custom_voices` *(dodawany z instrumentami)* | pokazuje nazwy instrumentów dodanych do soundbanku (niżej), po angielsku albo z `lang_pl` po polsku |

Wszystkie patche są przetestowane na prawdziwym NEK-100. Presety zapisane na oryginalnym
firmware dalej działają.

**Własne instrumenty:** strona i linia poleceń potrafią wstawić nowe instrumenty w miejsce dowolnego z 500 brzmień
(do 4). Trzeba im dać też oryginalny plik soundbanku z tej samej paczki aktualizacji (`NEK100_SBANK_V1.0.4.bin`)
i wgrać dwa pliki wynikowe: firmware DSP i soundbank. Nowe brzmienie ma własną nazwę (`500.Kocie piano`), a
wgranie oryginalnego soundbanku przywraca dawne brzmienie. Instrumenty to pliki **SoundFont 2** (`.sf2`), popularny format darmowych bibliotek
sampli. Z pliku wybierasz jeden preset; przenoszone są zakresy klawiszy, strojenie, częstotliwość próbkowania i pętle
(dźwięk trwa, dopóki trzymasz klawisz). Z warstw dynamiki brana jest ta dla siły 100, z warstw grających razem (np. druga o oktawę wyżej) każdy klawisz
bierze pierwszą, a stereo jest miksowane do mono.
Obwiednia głośności (atak, opadanie, podtrzymanie, wybrzmienie) pochodzi z pliku SF2, przeliczona na obwiednię
urządzenia (jej tempa zmierzone na NEK-100). Pozostałe ustawienia strefy pochodzą z brzmienia-szablonu Twojego soundbanku
(szarpanego dla dźwięków bez pętli, organów dla tych z pętlą), więc instrumenty nie zawierają danych NUX. Filtrów, LFO i
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
SoundFont z własnych sampli (np. z [Freesound](https://freesound.org)) robi `python3 -m nuxdsp pack` (opis wyżej). `nuxdsp export-sound` zapisuje fabryczne brzmienie jako SF2 do porównań; to sample NUX, więc taki plik zostaje u Ciebie, nie udostępniaj go. Soundbank rośnie o rozmiar sampli, a ile miejsca ma
flash, jeszcze nie wiadomo, więc lepiej zaczynać od małych instrumentów.

> **Na własne ryzyko.** To nieoficjalny projekt, niezwiązany z NUX ani Dream. Zmodyfikowany firmware może
> naruszać warunki gwarancji. Zachowaj oryginalny plik: wgranie go z powrotem przywraca fabryczny stan.

**Przeglądarka:** otwórz **https://jmarianski.github.io/nux-dsp-mod/** albo `web/index.html` z pobranego repozytorium
(działa offline, plik nie opuszcza przeglądarki). Wskaż plik DSP z oficjalnej paczki aktualizacji NUX:
strona rozpozna model i wersję, pokaże dostępne poprawki i da gotowy plik.
**Linia poleceń:** `python3 -m nuxdsp build NEK100_DSP_V1.0.7.bin wynik.bin`, a pozostałe polecenia
są opisane wyżej.
**Wgrywanie:** oficjalnym narzędziem NUX, tak samo jak zwykłą aktualizację DSP. Narzędzie musi pokazać
niezerową ilość zaprogramowanych danych. Na ekranie wersji powinno być `DSP:1.0.7B`.
