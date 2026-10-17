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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
GAME = os.path.join(WEB, "build", "game.json")
sys.path.insert(0, os.path.join(ROOT, "tools"))


def sources():
    pats = ["firmware/*.c", "firmware/*.py", "cc/*.py", "tools/webbuild.py", "tools/wad.py", "tools/doommap.py"]
    return [p for pat in pats for p in glob.glob(os.path.join(ROOT, pat))]


def stale():
    if not os.path.exists(GAME):
        return True
    t = os.path.getmtime(GAME)
    return any(os.path.getmtime(p) > t for p in sources())


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=WEB, **k)

    def do_GET(self):
        if self.path.split("?")[0] == "/build/game.json" and stale():
            try:
                import importlib
                for name in ("p16cc", "ray", "webbuild"):
                    if name in sys.modules:
                        importlib.reload(sys.modules[name])
                import webbuild
                webbuild.main([GAME])
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
    print("http://localhost:%d/" % port)
    http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
