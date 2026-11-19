"""Local copy of the panel, for working on it.  Run:  python admin.py
Serves this folder on http://localhost:8000 - the scanner at /, the panel at /admin.html - and
answers /api/admin and /api/products exactly as the two functions in api/ do live, by calling the
same build.py and sheet.py. The Google Sheet is the database either way, so a change made here is
the same change made from the live page.

Needs SHEET_URL and SHEET_SECRET in the environment (see sheet.py). Without them the panel still
opens, read-only, on whatever products.js currently holds.
"""
import json, os, webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import build, sheet
from api.admin import apply  # the one implementation of a change, shared with the live function

HERE = Path(__file__).parent
PORT = 8000


class Admin(SimpleHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/admin":
            # no key here: the server is bound to localhost, so reaching it at all is the permission
            ready = sheet.configured()
            return self.reply(200, {"colours": sorted(build.COLOURS), "where": "the Google Sheet (from this PC)",
                                    "write": ready,
                                    "why": "" if ready else "SHEET_URL and SHEET_SECRET are not set in this shell"})
        if path == "/api/products":
            try:
                products = build.catalogue(sheet.rows())
                return self.reply(200, {"products": products, "count": len(products)})
            except Exception as e:
                return self.reply(503, {"error": f"{type(e).__name__}: {e}"})
        super().do_GET()

    def do_POST(self):
        if self.path.split("?")[0] != "/api/admin":
            return self.send_error(404)
        try:
            form = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            out = apply(form)
            out["note"] = ("Removed from the sheet." if out.get("deleted") else "Saved to the sheet.") \
                + f" {len(out['products'])} products."
            self.reply(200, out)
        except ValueError as e:
            self.reply(400, {"error": str(e)})
        except Exception as e:
            self.reply(500, {"error": f"{type(e).__name__}: {e}"})

    def reply(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")  # products.js changes under the page
        super().end_headers()


if __name__ == "__main__":
    if not sheet.configured():
        print("note: SHEET_URL and SHEET_SECRET are not set, so the panel will be read-only.\n")
    print(f"panel    http://localhost:{PORT}/admin.html\nscanner  http://localhost:{PORT}/\nCtrl+C to stop")
    webbrowser.open(f"http://localhost:{PORT}/admin.html")
    # localhost only: this one can change the catalogue, so it has no business being on the network
    ThreadingHTTPServer(("127.0.0.1", PORT), partial(Admin, directory=str(HERE))).serve_forever()
