#!/usr/bin/env python3
"""Build and validate a private NEK-100 demo ZIP. Never flashes or publishes.

Run with the repository's test environment: .venv/bin/python tools/packdemo.py.
Includes the target's default patches and a matching no-Doom recovery image.
All vendor/WAD-derived files stay in the ignored build/packages/ directory.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import builddemo
import playthrough
import wad
from nuxdsp import container, fwmap, patcher


def digest(data):
    return hashlib.sha256(data).hexdigest()


def command(args):
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout.strip()


def instructions(params, ram, program, firmware):
    patches = ", ".join(params["patches"])
    return f"""DOOM NA NUX NEK-100 — diagnostyka pętli E1M1

Wersja diagnostyczna wycisza muzykę i efekty gry; sterowanie zostaje bez zmian.
Sprawdza porcje renderowania zamiast całej klatki w ticku, z podniesionym
limitem emulatora do 1 miliona instrukcji na tick. Zawiera znaczniki diagnostyczne.
Przeszła testy automatyczne i pełne przejście poziomu na kodzie z tego pliku.
Test instrumentu sprawdzi, czy brak muzyki i efektów zmienia zawieszanie.
Znaczniki diagnostyczne idą kanałem USB MIDI, lecz nie przez syntezator.

CO WGRAĆ
NEK100_DSP_DOOM_E1M1.bin — firmware DSP z grą i Twoim zwykłym zestawem poprawek.
Pozostałe pliki BIN są wariantami powrotu w katalogu rollback.

DOMYŚLNA KONFIGURACJA
Dołączone patche: {patches}.
BOOT_PRESET={params['parameters']['BOOT_PRESET']} — start z zapisanego presetu Default, slot 1.
PRESET_LABELS={params['parameters']['PRESET_LABELS']} — Default, User1..User4.
OFF_VELOCITY={params['parameters']['OFF_VELOCITY']} — stała dynamika po wybraniu Touch OFF.
Zostają Sustain w presetach, osobna oktawa MAIN/DUAL/SPLIT i ustawienia Extra:
Auto Off, Startup, Backlight, Speaker i Sleep. Zapisane wartości instrument czyta
ze swojej pamięci presetów. Paczka nie zawiera resetu fabrycznego, banku brzmień
ani stylów; aktualizujesz wyłącznie DSP. Pełne parametry: default-settings.json.

WINDOWS
1. Rozpakuj ZIP. RPC-DFUForWin.exe oraz DREAM-Rpc.dll muszą być obok siebie.
2. Podłącz pianino przez USB. Włącz tryb aktualizacji: Power + VOL+ + VOL−
   przytrzymane razem przez około pół sekundy.
3. Uruchom RPC-DFUForWin.exe z tej paczki. Wskaż NEK100_DSP_DOOM_E1M1.bin
   i wykonaj zwykłą aktualizację firmware DSP. Sprawdź, że program zgłasza
   niezerową ilość zaprogramowanych danych. Nie odłączaj zasilania podczas zapisu.
4. Po zakończeniu wyłącz i włącz pianino. Ekran wersji: DSP:1.0.7B.
5. Otwórz menu funkcji → Extra → trzecia strona → DOOM (ikona czaszki).

LINUX / macOS Z ISTNIEJĄCYM REPOZYTORIUM nek100-mod
W trybie aktualizacji, z katalogu nek100-mod, użyj sprawdzonego polecenia:
  python3 -m nuxdsp flash --dry-run /ścieżka/do/NEK100_DSP_DOOM_E1M1.bin
  python3 -m nuxdsp flash /ścieżka/do/NEK100_DSP_DOOM_E1M1.bin
Potrzebne są pyusb/libusb oraz dostęp do USB zgodnie z README nek100-mod.
Te polecenia wykonujesz sam; przygotowanie paczki niczego nie wgrywa.

DIAGNOSTYKA PO WGRANIU
Przed wejściem do DOOM uruchom w repozytorium doom-piano:
  .venv/bin/python tools/trace_listen.py NEK
Do wyrenderowania trzech klatek (i przez co najmniej pierwsze 63 callbacki)
wysyła etap przez USB MIDI: 0x601 start pętli, 0x602 logika,
0x603 porcja renderowania, 0x600 powrót z callbacku. Potem 0x600 co 64 ticki.
Ostatni znacznik przy zawieszeniu pozwoli wskazać podejrzaną ścieżkę.
Limit emulatora: 1000000 instrukcji P16 na tick (wcześniej 135000).
Nie obejmuje czasu usług firmware i nie zastępuje pomiaru na urządzeniu.

STEROWANIE NA PIANINIE (C4 = MIDI 60)
C3 / E3              obrót w lewo / prawo
C#3 lub D#3          naprzód
D3                   wstecz
B2 / F3              krok w bok w lewo / prawo
C5                   strzał
D5                   otwórz drzwi / użyj przycisku — podejdź blisko i stań przodem
E5                   bieg (trzymaj wraz z kierunkiem ruchu)
B0                   restart po śmierci lub wygranej
VOL+ / VOL−          głośność
Inny przycisk panelu kończy grę i wraca do menu Extra.

Cel: dotrzyj do przycisku wyjścia w E1M1 i użyj D5.
H = zdrowie, A = amunicja, K = pokonani przeciwnicy. Drzwi podnoszą się do góry
i zostają otwarte. Pomocnicza mapa z przeglądarki jest dostępna w symulatorze.

POWRÓT
rollback/NEK100_DSP_DEFAULTS_BEZ_DOOM.bin: te same domyślne poprawki bez gry.
rollback/NEK100_DSP_V1.0.7.bin: oryginalny firmware NUX.
Wybierz odpowiedni plik i wgraj go tą samą procedurą DSP.

PAMIĘĆ I WERYFIKACJA
C RAM: {ram['used']}/{ram['limit']} słów, zapas {ram['free']}.
Osobno: {ram['glue_reserved']} słowa glue i {ram['framebuffer']} słowa framebuffera.
Kod i dane demo: {program['used']}/{program['limit']} słów.
Cały firmware: {firmware['used']}/{firmware['limit']} słów.
Raporty: memory-budget.json, playthrough-result.json, validation.json.
SHA256SUMS.txt pozwala sprawdzić integralność plików po rozpakowaniu.
"""


def main():
    official = ROOT.parent / "NEK100_DSP_V1.0.7.bin"
    helpers = [ROOT.parent / name for name in ("RPC-DFUForWin.exe", "DREAM-Rpc.dll")]
    for path in [official, *helpers]:
        if not path.is_file():
            raise FileNotFoundError(path)
    now = datetime.now(timezone.utc)
    packages = ROOT / "build" / "packages"
    packages.mkdir(parents=True, exist_ok=True)
    name = "NEK100_DOOM_E1M1_SILENT_" + now.strftime("%Y%m%dT%H%M%S%fZ")
    output = packages / name
    print("Running repository tests…", flush=True)
    test_log = command([sys.executable, "-m", "pytest", "-q"])
    print(test_log.splitlines()[-1], flush=True)
    target = fwmap.load()
    defaults = [patcher.load(p, target) for p in target.defaults]
    settings = {"patches": list(target.defaults),
                "parameters": {param.name: param.default for patch in defaults for param in patch.params}}
    with tempfile.TemporaryDirectory(prefix="packdemo-", dir=ROOT / "build") as temp:
        work = Path(temp)
        print("Building current demo with default patches…", flush=True)
        summary = builddemo.build(official, work, silent_audio=True)
        (work / "route.json").write_text(json.dumps(playthrough.route()))
        print("Replaying the exact linked firmware…", flush=True)
        replay_log = command(["node", str(ROOT / "tools" / "playthrough.cjs"), str(ROOT / "web" / "p16.js"),
                              str(work / "linked-game.json"), str(work / "route.json")])
        result = json.loads((work / "playthrough-result.json").read_text())
        if result["result"] != "WIN" or result["kills"] != 4 or result["health"] <= 0:
            raise RuntimeError("linked firmware did not finish E1M1 alive")
        print(replay_log.splitlines()[-1], flush=True)
        # Same defaults and canonical addresses as the demo, with no game patch.
        canonical = patcher.canonical_layout(target)
        layout = {key: canonical[key] for p in defaults for key, _lines, _n in patcher.code_blocks(p)
                  if key in canonical}
        layout = patcher.allocate(defaults, target, layout)
        recovery, _ = patcher.build(official.read_bytes(), target, defaults, layout=layout)
        builddemo.budget.check_firmware(recovery)
        output.mkdir()
        rollback = output / "rollback"; rollback.mkdir()
        shutil.copyfile(work / "NEK100_DSP_demo.bin", output / "NEK100_DSP_DOOM_E1M1.bin")
        (rollback / "NEK100_DSP_DEFAULTS_BEZ_DOOM.bin").write_bytes(recovery)
        shutil.copyfile(official, rollback / official.name)
        for path in helpers:
            shutil.copyfile(path, output / path.name)
        for filename in ("memory-budget.json", "playthrough-result.json", "firmware-build.txt"):
            shutil.copyfile(work / filename, output / filename)
    (output / "default-settings.json").write_text(json.dumps(settings, indent=2) + "\n")
    (output / "PRZECZYTAJ.txt").write_text(instructions(settings, summary["ram"], summary["program"], summary["firmware"]), encoding="utf-8")
    (output / "tests.txt").write_text(test_log + "\n")
    inputs = [*sorted((ROOT / "firmware").glob("*.c")), ROOT / "firmware" / "doom.py",
              ROOT / "firmware" / "ray.py", ROOT / "cc" / "p16cc.py", *sorted((ROOT / "tools").glob("*.py")),
              ROOT / "web" / "p16.js", Path(wad.WAD), Path(wad.MAP)]
    validation = {"built_utc": now.isoformat(), "device": target.device, "status": "silent-hardware-diagnostic",
                  "official_sha256": digest(official.read_bytes()), "default_settings": settings,
                  "container_checks": {}, "tests": test_log.splitlines()[-1], "linked_firmware_replay": result,
                  "silent_audio": True, "synthesizer_messages_during_gameplay": 0,
                  "hardware_flashed": False, "hardware_timing_verified": False,
                  "git_head": command(["git", "rev-parse", "HEAD"]),
                  "working_tree_dirty": bool(command(["git", "status", "--porcelain"])),
                  "source_sha256": {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in inputs}}
    for path in output.rglob("*.bin"):
        errors = container.validate(path.read_bytes())
        if errors:
            raise ValueError(f"{path.name}: {errors}")
        validation["container_checks"][str(path.relative_to(output))] = "PASS"
    (output / "validation.json").write_text(json.dumps(validation, indent=2) + "\n")
    files = sorted(p for p in output.rglob("*") if p.is_file())
    checksums = {str(p.relative_to(output)): digest(p.read_bytes()) for p in files}
    (output / "SHA256SUMS.txt").write_text("".join(f"{value}  {filename}\n" for filename, value in checksums.items()))
    archive = output.with_suffix(".zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for path in sorted(p for p in output.rglob("*") if p.is_file()):
            z.write(path, str(Path(name) / path.relative_to(output)))
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:
            raise ValueError("ZIP integrity check failed")
        for filename, expected in checksums.items():
            if digest(z.read(str(Path(name) / filename))) != expected:
                raise ValueError(f"ZIP digest mismatch: {filename}")
    print("Package verified:", archive, flush=True)


if __name__ == "__main__":
    main()
