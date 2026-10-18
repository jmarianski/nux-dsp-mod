#!/usr/bin/env python3
"""Serve web/ on localhost (WebMIDI needs localhost or https) and rebuild build/game.json whenever the page asks
for it and a source (firmware/*.c, firmware/*.py, cc/, tools/webbuild.py) is newer. Build errors go to the page
as a 500 with the message, and to this terminal.

Usage: python3 tools/webserve.py [PORT]      then open http://localhost:8017/
"""
import glob
import http.server
import os
import sys
import traceback
import threading
from urllib.parse import urlsplit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
GAME = os.path.join(WEB, "build", "game.json")
BUILDS = {"/build/game.json": (GAME, "doom"), "/build/ray.json": (os.path.join(WEB, "build", "ray.json"), "ray")}
BUILD_LOCK = threading.Lock()
sys.path.insert(0, os.path.join(ROOT, "tools"))


def sources():
    pats = ["firmware/*.c", "firmware/*.py", "cc/*.py", "tools/*.py", "wad/*.WAD", "wad/*.wad", "maps/*.wad", "art/*.txt",
            "../nuxdsp/*.py", "../nuxdsp/*.toml"]
    return [p for pat in pats for p in glob.glob(os.path.join(ROOT, pat))]


def stale(out=GAME):
    if not os.path.exists(out):
        return True
    t = os.path.getmtime(out)
    return any(os.path.getmtime(p) > t for p in sources())


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=WEB, **k)

    def do_GET(self):
        build = BUILDS.get(urlsplit(self.path).path)
        if build:
            try:
                with BUILD_LOCK:
                    out, engine = build
                    if stale(out):
                        import importlib
                        importlib.invalidate_caches()
                        # Every module of this repo and the sibling nuxdsp is imported afresh, in dependency order.
                        ours = (ROOT, os.path.join(ROOT, "..", "nuxdsp"))
                        for name, mod in list(sys.modules.items()):
                            f = os.path.abspath(getattr(mod, "__file__", None) or "")
                            if any(f.startswith(os.path.abspath(r) + os.sep) for r in ours):
                                del sys.modules[name]
                        import webbuild
                        webbuild.main(["--engine", engine, out])
            except Exception:
                msg = traceback.format_exc()
                print(msg, file=sys.stderr)
                self.send_response(500)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(msg.encode())
                return
        super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8017
    # First request rebuilds even if the dependency set changed since the previous server run.
    for out, _ in BUILDS.values():
        if os.path.exists(out):
            os.utime(out, (0, 0))
    print("http://localhost:%d/" % port)
    http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
