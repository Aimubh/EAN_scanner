"""/api/admin on Vercel: see, add, change and remove products from the live page.

The Google Sheet is the database (sheet.py talks to it, sheet.gs guards it). Every rule - what a
valid row is, which colours exist, how an EAN is keyed - lives in build.py, so this and the local
admin.py behave identically and there is one copy of the thinking.

Needs three environment variables on the Vercel project:
  SHEET_URL     the Apps Script web app's /exec URL
  SHEET_SECRET  the SECRET script property you set on that script
  ADMIN_KEY     the secret that makes the form appear: /admin.html#key=<this>
Without them the endpoint still answers, read-only, so a half-configured deploy degrades to the
browse-only catalogue rather than a 500.
"""
import hmac, json, os, sys, urllib.error
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.getcwd())  # Vercel runs functions from the project root, where build.py lives
import build, sheet

KEY = os.environ.get("ADMIN_KEY", "")


def allowed(key):
    return bool(KEY) and hmac.compare_digest(key, KEY)


def apply(form):
    """Carry out one change and return what the page should show. Raises ValueError on a bad form."""
    rows = sheet.rows()
    if form.get("delete"):
        index, ean = build.removal(rows, form["delete"])
        rows = sheet.delete(index)
        return {"ean": ean, "deleted": True, "products": build.catalogue(rows)}
    index, values, ean = build.save(rows, form, form.get("replacing") or None)
    rows = sheet.write(index, values)
    products = build.catalogue(rows)
    return {"ean": ean, "product": products.get(ean), "replaced": form.get("replacing") or "",
            "products": products}


class handler(BaseHTTPRequestHandler):
    # the key travels in a header, never the query string, so it stays out of Vercel's request logs
    def key(self):
        return self.headers.get("X-Admin-Key", "")

    def do_GET(self):
        ready = sheet.configured()
        self.reply(200, {"colours": sorted(build.COLOURS), "where": "the Google Sheet",
                         "write": allowed(self.key()) and ready,
                         "why": "" if ready else "SHEET_URL and SHEET_SECRET are not set on this deployment"})

    def do_POST(self):
        try:
            form = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self.reply(400, {"error": "the request body was not valid JSON"})
        if not allowed(self.key()):
            # the same answer whether the key is wrong or unset, so this cannot be used to probe
            return self.reply(401, {"error": "wrong or missing key. Open the panel with #key=... on the end of the link."})
        try:
            out = apply(form)
            out["note"] = ("Removed from the sheet." if out.get("deleted") else "Saved to the sheet.") \
                + f" {len(out['products'])} products, live on the phones on the next page load."
            self.reply(200, out)
        except ValueError as e:
            self.reply(400, {"error": str(e)})
        except urllib.error.HTTPError as e:
            self.reply(502, {"error": f"the sheet's script answered {e.code}. Check SHEET_URL is the /exec URL "
                                      f"and the deployment is set to 'Anyone'."})
        except Exception as e:
            self.reply(500, {"error": f"{type(e).__name__}: {e}"})

    def reply(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # Vercel captures stdout; the default access log just doubles it
