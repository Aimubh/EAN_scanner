"""Local admin panel: add products to products.xlsx and browse the catalogue.  Run:  python admin.py
Serves this folder on http://localhost:8000 - the scanner at /, the panel at /admin.html.
Adding a product writes the row into products.xlsx and reruns build.py, so products.js is current on reload.
Going live still needs a git push; this only edits the sheet on this machine.

It answers /api/admin exactly as api/admin.py does on Vercel, so the panel has one code path either way.
The difference: this one writes a file, that one commits to GitHub. The row itself goes through
build.add_row in both, so a product added here and one added from the live page follow the same rules.
"""
import json, shutil, tempfile, threading, webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from openpyxl import load_workbook

import build  # the EAN rules, the colour guess, the row validation and the products.js writer all live there

HERE = Path(__file__).parent
XLSX = HERE / "products.xlsx"
PORT = 8000
writing = threading.Lock()  # one browser on localhost, but a half-written sheet would lose 217 products


def save_product(form):
    """Write the row into products.xlsx, rebuild products.js, return (ean, the product as the page shows it).
    form['replacing'] is the EAN of the product being edited; without it this is a new product."""
    with writing:
        wb = load_workbook(XLSX)
        ean = build.save_row(wb.active, form, form.get("replacing") or None)  # raises before anything is written
        wb.save(XLSX)
        products = build.build(XLSX)
    return ean, products[ean]


class Admin(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0] == "/api/admin":
            # no key here: the server is bound to localhost, so reaching it at all is the permission
            return self.reply(200, {"colours": sorted(build.COLOURS), "write": True, "where": "this PC"})
        super().do_GET()

    def do_POST(self):
        if self.path.split("?")[0] != "/api/admin":
            return self.send_error(404)
        try:
            form = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            ean, product = save_product(form)
            self.reply(200, {"ean": ean, "product": product, "replaced": form.get("replacing") or "",
                             "note": "Saved to products.xlsx. Run git push to reach the phones."})
        except ValueError as e:
            self.reply(400, {"error": str(e)})
        except Exception as e:  # a locked sheet (open in Excel) or a broken workbook: say which, do not just 500
            self.reply(500, {"error": f"{type(e).__name__}: {e}. Close {XLSX.name} in Excel if it is open."})

    def reply(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")  # products.js changes under the page; a cached copy hides the new product
        super().end_headers()


def self_check():
    """Add a product to a copy of the sheet in a temp folder, and check it reaches products.js."""
    global XLSX
    try:
        with tempfile.TemporaryDirectory() as tmp:
            XLSX, build.HERE = Path(tmp) / "products.xlsx", Path(tmp)
            shutil.copy(HERE / "products.xlsx", XLSX)
            ean, product = save_product({"name": "Test Bag (Rose Red)", "ean": "0 999 000 111 222", "sku": "zztest"})
            assert ean == "999000111222", ean
            assert product == {"name": "Test Bag (Rose Red)", "sku": "zztest", "colour": "rose red",
                               "hex": "#c21e56", "image": ""}, product
            # and it reached the file the browser actually reads, not just the return value
            made = json.loads((Path(tmp) / "products.js").read_text(encoding="utf-8").split("=", 1)[1].rstrip().rstrip(";"))
            assert made[ean] == product, made[ean]
            # the override beats the guess, on a name with no colour in it
            assert save_product({"name": "Plain Box", "ean": "999000111333", "sku": "zzbox", "colour": "teal"})[1]["hex"] == "#1f8a8a"

            # editing: same row rewritten, not a second one, and a cleared field really clears
            total = len(build.catalogue(XLSX))
            ean, product = save_product({"name": "Renamed Bag", "ean": "999000111222", "sku": "zzrenamed",
                                         "colour": "black", "image": "", "replacing": "999000111222"})
            assert ean == "999000111222", ean
            assert product == {"name": "Renamed Bag", "sku": "zzrenamed", "colour": "black",
                               "hex": "#1b1c1f", "image": ""}, product
            assert len(build.catalogue(XLSX)) == total, "an edit must not add a row"
            # an edit may move the product to a new EAN, and the old key goes away
            moved = save_product({"name": "Renamed Bag", "ean": "999000111999", "sku": "zzrenamed",
                                  "replacing": "999000111222"})[0]
            after = build.catalogue(XLSX)
            assert moved == "999000111999" and "999000111222" not in after and len(after) == total

            for bad, why in (({"name": "", "ean": "1", "sku": "s"}, "name"), ({"name": "n", "ean": "1", "sku": ""}, "SKU"),
                             ({"name": "n", "ean": "", "sku": "s"}, "EAN"), ({"name": "n", "ean": "abc", "sku": "s"}, "digit"),
                             ({"name": "n", "ean": "1", "sku": "s", "colour": "puce"}, "colour"),
                             ({"name": "n", "ean": "5949998498176", "sku": "s"}, "already"),
                             # editing a product that is not there, and moving one onto a taken EAN
                             ({"name": "n", "ean": "1", "sku": "s", "replacing": "404404404"}, "nothing to update"),
                             ({"name": "n", "ean": "5949998498176", "sku": "s", "replacing": "999000111333"}, "another product")):
                try:
                    save_product(bad)
                    raise AssertionError(f"accepted {bad}")
                except ValueError as e:
                    assert why in str(e), f"{bad} -> {e}"
    finally:
        XLSX, build.HERE = HERE / "products.xlsx", HERE
    print("self-check ok")


if __name__ == "__main__":
    import sys
    if "--check" in sys.argv:
        self_check()
    else:
        print(f"panel    http://localhost:{PORT}/admin.html\nscanner  http://localhost:{PORT}/\nCtrl+C to stop")
        webbrowser.open(f"http://localhost:{PORT}/admin.html")
        # localhost only: this one writes to the sheet, so it has no business being reachable from the network
        ThreadingHTTPServer(("127.0.0.1", PORT), partial(Admin, directory=str(HERE))).serve_forever()
