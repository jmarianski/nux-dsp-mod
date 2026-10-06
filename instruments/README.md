# Bundled instruments

SoundFont 2 files for `nuxdsp build --voice SLOT=NAME` and the web patcher. Each one says in its INFO
(author `IENG`, license `ICOP`, comment `ICMT`) who recorded the samples, where they come from and under which
license; `index.json` adds the Polish name, which SoundFonts have no field for.

| Instrument | Samples | License |
|---|---|---|
| `cat_piano.sf2` | "Cat Piano Note C" (C note recorded from a toy cat piano) by Meku A, Freesound.org, via creazilla.com. Pitched to 29 root keys (24..108, every 3 semitones) and the attack trimmed (each sample starts 5 ms before reaching 25 % of its peak level, 1 ms fade-in) | CC0 1.0, public domain |

Adding one: only samples you may share (CC0, or CC-BY with the author named). A SoundFont from a sample
directory: `python3 -m nuxdsp pack DIR NAME.sf2 --name ... --author ... --license ... --comment ...`. Then
run `python3 -m nuxdsp web NEK100_DSP_V1.0.7.bin` to update the web page's copy.
