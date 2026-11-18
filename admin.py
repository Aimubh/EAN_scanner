"""Local admin panel: add products to products.xlsx and browse the catalogue.  Run:  python admin.py
Serves this folder on http://localhost:8000 - the scanner at /, the panel at /admin.html.
Adding a product writes the row into products.xlsx and reruns build.py, so products.js is current on reload.
Going live still needs a git push; this only edits the sheet on this machine.
"""
import json, shutil, tempfile, threading, webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from openpyxl import load_workbook

import build  # the EAN rules, the colour guess and the products.js writer all live there already

HERE = Path(__file__).parent
XLSX = HERE / "products.xlsx"
PORT = 8000
IMAGE_HEADERS = ("images", "image link", "image")  # whichever one the sheet uses; build.py reads all three
writing = threading.Lock()  # one browser on localhost, but a half-written sheet would lose 217 products


def add_product(form):
    """Append the row to products.xlsx, rebuild products.js, return the EAN as build.py keys it."""
    get = lambda f: str(form.get(f) or "").strip()
    name, sku, image, colour = get("name"), get("sku"), get("image"), get("colour").lower()
    ean = build.ean_key(get("ean"))
    for field, value in (("name", name), ("SKU", sku), ("EAN", get("ean"))):
        if not value:
            raise ValueError(f"{field} cannot be empty")
    if not ean:
        raise ValueError("the EAN needs at least one digit")
    if colour and colour not in build.COLOURS:
        raise ValueError(f"unknown colour {colour!r}")
    with writing:
        wb = load_workbook(XLSX)
        ws = wb.active
        col = {str(c.value).strip().lower(): c.column for c in ws[1] if c.value}
        for required in ("product name", "ean", "sku"):
            if required not in col:
                raise ValueError(f"{XLSX.name} has no {required!r} column")
        taken = {build.ean_key(c.value) for c in ws[ws.cell(1, col["ean"]).column_letter][1:] if c.value}
        if ean in taken:
            raise ValueError(f"EAN {ean} is already in {XLSX.name}")
        row = ws.max_row + 1
        if colour and "colour" not in col:  # build.py reads a Colour column when there is one, so make it on first use
            col["colour"] = ws.max_column + 1
            ws.cell(1, col["colour"], "Colour")
        cells = {"product name": name, "ean": int(ean), "sku": sku, "colour": colour,
                 next((h for h in IMAGE_HEADERS if h in col), "images"): image}
        for header, value in cells.items():
            if header in col and value != "":
                ws.cell(row, col[header], value)
        wb.save(XLSX)
        build.build(XLSX)
    return ean


class Admin(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/colours":
            return self.reply(200, sorted(build.COLOURS))  # the dropdown, so the names never drift from build.py
        super().do_GET()

    def do_POST(self):
        if self.path != "/add":
            return self.send_error(404)
        try:
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            self.reply(200, {"ean": add_product(json.loads(body))})
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
            assert add_product({"name": "Test Bag (Rose Red)", "ean": "0 999 000 111 222", "sku": "zztest"}) == "999000111222"
            made = json.loads((Path(tmp) / "products.js").read_text(encoding="utf-8").split("=", 1)[1].rstrip().rstrip(";"))
            assert made["999000111222"] == {"name": "Test Bag (Rose Red)", "sku": "zztest", "colour": "rose red",
                                            "hex": "#c21e56", "image": ""}, made["999000111222"]
            assert add_product({"name": "Plain Box", "ean": "999000111333", "sku": "zzbox", "colour": "teal"}) == "999000111333"
            assert json.loads((Path(tmp) / "products.js").read_text(encoding="utf-8").split("=", 1)[1].rstrip().rstrip(";")
                              )["999000111333"]["hex"] == "#1f8a8a"  # the override beat the guess (no colour in the name)
            for bad, why in (({"name": "", "ean": "1", "sku": "s"}, "name"), ({"name": "n", "ean": "1", "sku": ""}, "SKU"),
                             ({"name": "n", "ean": "", "sku": "s"}, "EAN"), ({"name": "n", "ean": "abc", "sku": "s"}, "digit"),
                             ({"name": "n", "ean": "1", "sku": "s", "colour": "puce"}, "colour"),
                             ({"name": "n", "ean": "5949998498176", "sku": "s"}, "already")):
                try:
                    add_product(bad)
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
