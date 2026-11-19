"""/api/products: the catalogue as the Google Sheet has it right now.

The scanner and the panel both ship with products.js baked in, so they work instantly and with no
signal. They then ask here and swap in the live answer when it arrives, which is what makes an edit
in the sheet show up without a rebuild. If this is slow, unset, or the phone is offline, the baked
copy is what everyone keeps using - so this failing is a non-event, not an outage.

No key: the scanner has always shipped the whole catalogue to every phone, so this reveals nothing
products.js does not. The secret that reaches the sheet stays here on the server.
"""
import json, os, sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.getcwd())
import build, sheet


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            products = build.catalogue(sheet.rows())
            self.reply(200, {"products": products, "count": len(products)})
        except Exception as e:
            # the page falls back to products.js, so say what went wrong and let it carry on
            self.reply(503, {"error": f"{type(e).__name__}: {e}"})

    def reply(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # a few seconds of edge cache takes the load off a shift of staff opening the page at once,
        # while still showing an edit from the sheet almost immediately
        self.send_header("Cache-Control", "public, max-age=10, stale-while-revalidate=60")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass
