# Contributing

Welcome: new patches, map entries, new models and firmware versions, test reports from real
instruments.

- **Never commit vendor material**: firmware files, generated listings (`.s`), patched builds, updater
  tools. `.gitignore` covers the usual names. The map and the patches contain only addresses, our own
  descriptions and our own code ([docs/LEGAL.md](docs/LEGAL.md)).
- **Map entries**: describe in your own words, mark `(C)` only what you confirmed on the instrument and
  `(H)` for guesses.
- **Patches**: see [docs/PATCHING.md](docs/PATCHING.md). Simulate new code (`nuxdsp/sim.py`, examples in
  `tests/`), test it on hardware with `version_tag` on, and say in the pull request what you tested.
- **Another model or version**: see [docs/NEW_TARGET.md](docs/NEW_TARGET.md).
- After changing a target's patches, regenerate its web data (`python3 -m nuxdsp web FILE.bin`) and
  update `ALL_SHA` in its firmware test. Run the tests:
  `NEK100_FW=/path/to/NEK100_DSP_V1.0.7.bin python3 -m unittest discover -s tests -t .`

Firmware-dependent tests are skipped without the file, so CI runs only the rest. Run them locally.
