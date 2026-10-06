# Instrument packs

`.nxi` packs for `nuxdsp build --voice` and the web patcher (format: `nuxdsp/instrument.py`). Each one says
in its header who recorded the samples, where they come from and under which license.

| Pack | Samples | License |
|---|---|---|
| `cat_piano.nxi` | "Cat Piano Note C" (C note recorded from a toy cat piano) by Meku A, Freesound.org, via creazilla.com. Pitched to 29 root keys (24..108, every 3 semitones) and the attack trimmed (each sample starts 5 ms before reaching 25 % of its peak level, 1 ms fade-in) | CC0 1.0, public domain |

Adding a pack: make it with `python3 -m nuxdsp pack`, with samples you may share (fill in `--author`,
`--source`, `--license`), then run `python3 -m nuxdsp web NEK100_DSP_V1.0.7.bin` to update the web page's copy.
