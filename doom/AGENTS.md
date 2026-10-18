# doom-piano working rules

- Preserve unrelated work. Keep changes within this repo unless a sibling dependency actually needs a fix.
- Iterate locally with `python3 tools/webserve.py` and http://localhost:8017/. R rebuilds firmware C/Python,
  compiler, WAD/map and sibling ISA sources. Restart the server after changing `tools/webserve.py` itself.
- The browser runs compiled P16 code. Keep gameplay/rendering in C shared with the target; host natives simulate
  firmware farcopy, synth and diagnostics. Browser frame timing is not evidence of hardware timing or read integrity.
- Run `.venv/bin/python -m pytest -q` (or `uv run pytest`). Node and local `wad/freedoom1.wad` are required for BSP
  pixel parity; missing prerequisites skip those tests and must be reported as unverified, not as passing parity.
- Optional UI gate: with the server running, `node tools/webcheck.cjs` using installed Playwright and Chrome.
  `PLAYWRIGHT_MODULE` may point to an existing installation. It mocks MIDI, checks movement/pause/reload,
  failed-build/runtime recovery and engine switching, and saves the ignored `build/webcheck.png`.
- The demo plays our own map, Hangar (`tools/makemap.py` -> `maps/hangar.wad`, nodes by zdbsp), with Freedoom
  assets: four enemy slots, simplified sprites/AI, shared ammo and doors that stay open. Keep the
  scope distinct from the long-term full Doom plan. Floors/ceilings deliberately share the plain background.
- Build/audit firmware with `python3 tools/builddemo.py`; it enforces 482 C RAM words, the target far pool
  [0x1a280,0x3ffc0), non-overlap and the entire 0x40000-word partition including checksum/padding. The separate
  24-word glue reserve and 1024-word framebuffer are part of the RAM report. Never bypass an overflow gate.
- `python3 tools/playthrough.py` creates a full route; replay the actual firmware-decoded artifact with
  `node tools/playthrough.cjs web/p16.js build/linked-game.json build/route.json`. The replay uses key/game ticks,
  no teleports or inventory edits, and guards every RAM write. It must finish alive with WIN. Pytest repeats
  the linked-firmware replay when the official local NUX firmware is available.
- Keep NUX firmware, WADs and generated builds local; do not add them to git (only `maps/hangar.wad` is ours).
  Builds from Freedoom + Hangar may be shared; builds with `PIANODOOM_WAD`/`PIANODOOM_MAP` set to DOOM1.WAD may not.
- Hardware flash and real MIDI tests are separate from browser checks. State which actually ran; do not infer
  device behavior or diagnose device music corruption solely from host-native simulation.
