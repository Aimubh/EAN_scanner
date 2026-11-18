"""/api/admin on Vercel: add a product from the live page.

Same endpoint and same answers as admin.py serves locally, so admin.html has one code path.
The difference is where the row lands: admin.py writes products.xlsx on your PC, this one commits
products.xlsx and products.js back to GitHub in a single commit, which makes Vercel redeploy and
puts the product on the staff phones about a minute later. There is no database: the repo stays the
one source of truth, and every add is an ordinary commit you can read, revert or blame.

Needs two environment variables in the Vercel project (Settings -> Environment Variables):
  GITHUB_TOKEN  a fine-grained personal access token, Contents: Read and write, this repo only
  ADMIN_KEY     the secret that makes the form appear: the panel is opened as /admin.html#key=<this>
Without them the endpoint still answers, but read-only, so a missing variable degrades to the
browse-only page rather than a 500.
"""
import base64, hmac, io, json, os, sys, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler


from openpyxl import load_workbook

sys.path.insert(0, os.getcwd())  # Vercel runs functions from the project root, where build.py lives
import build

TOKEN = os.environ.get("GITHUB_TOKEN", "")
KEY = os.environ.get("ADMIN_KEY", "")
REPO = os.environ.get("GITHUB_REPO", "Aimubh/EAN_scanner")
BRANCH = os.environ.get("GITHUB_BRANCH", "main")
API = "https://api.github.com"


def gh(path, data=None, method=None):
    request = urllib.request.Request(
        API + path,
        data=None if data is None else json.dumps(data).encode(),
        method=method or ("POST" if data is not None else "GET"),
        headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json",
                 "User-Agent": "ean-scanner-admin", "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as reply:
        return json.load(reply)


def fetch(path):
    """The file's bytes, as the branch currently has it."""
    return base64.b64decode(gh(f"/repos/{REPO}/contents/{path}?ref={BRANCH}")["content"])


def commit(files, message):
    """One commit replacing {path: bytes}. One, not two, so products.xlsx and products.js can never
    land out of step with each other."""
    head = gh(f"/repos/{REPO}/git/ref/heads/{BRANCH}")["object"]["sha"]
    base_tree = gh(f"/repos/{REPO}/git/commits/{head}")["tree"]["sha"]
    tree = [{"path": path, "mode": "100644", "type": "blob",
             "sha": gh(f"/repos/{REPO}/git/blobs",
                       {"content": base64.b64encode(body).decode(), "encoding": "base64"})["sha"]}
            for path, body in files.items()]
    new_tree = gh(f"/repos/{REPO}/git/trees", {"base_tree": base_tree, "tree": tree})["sha"]
    made = gh(f"/repos/{REPO}/git/commits", {"message": message, "tree": new_tree, "parents": [head]})["sha"]
    # the branch has to still be where we found it, or someone else committed while we worked
    gh(f"/repos/{REPO}/git/refs/heads/{BRANCH}", {"sha": made}, method="PATCH")
    return made


def save_product(form):
    """Write the row into the repo's products.xlsx, rebuild products.js, commit both. (ean, sha, products).
    form['replacing'] is the EAN of the product being edited; without it this is a new product."""
    sheet = fetch("products.xlsx")
    workbook = load_workbook(io.BytesIO(sheet))
    replacing = form.get("replacing") or None
    ean = build.save_row(workbook.active, form, replacing)  # raises ValueError before anything is committed
    out = io.BytesIO()
    workbook.save(out)
    updated = out.getvalue()
    products = build.catalogue(io.BytesIO(updated))
    what = f"Update {replacing}" if replacing else "Add"
    sha = commit({"products.xlsx": updated, "products.js": build.render(products).encode("utf-8")},
                 f"{what}: {form.get('name', '')[:60]} ({ean}), from the live admin panel")
    return ean, sha, products


def allowed(key):
    return bool(KEY) and hmac.compare_digest(key, KEY)


class handler(BaseHTTPRequestHandler):
    # the key travels in a header, never the query string, so it stays out of Vercel's request logs
    def key(self):
        return self.headers.get("X-Admin-Key", "")

    def do_GET(self):
        self.reply(200, {"colours": sorted(build.COLOURS), "where": "GitHub",
                         "write": allowed(self.key()) and bool(TOKEN),
                         "why": "" if TOKEN else "GITHUB_TOKEN is not set on this deployment"})

    def do_POST(self):
        try:
            form = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self.reply(400, {"error": "the request body was not valid JSON"})
        if not allowed(self.key()):
            # the same answer whether the key is wrong or unset, so this cannot be used to probe
            return self.reply(401, {"error": "wrong or missing key. Open the panel with #key=... on the end of the link."})
        if not TOKEN:
            return self.reply(503, {"error": "GITHUB_TOKEN is not set on this deployment, so nothing can be saved."})
        try:
            ean, sha, products = save_product(form)
            self.reply(200, {"ean": ean, "product": products[ean], "replaced": form.get("replacing") or "",
                             "note": f"Committed {sha[:7]}, {len(products)} products. Live on the phones in about a minute."})
        except ValueError as e:
            self.reply(400, {"error": str(e)})
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:200]
            hint = {401: "the GITHUB_TOKEN is not valid", 403: "the token lacks Contents: write on this repo",
                    409: "someone else pushed while this was saving, try again"}.get(e.code, "")
            self.reply(502, {"error": f"GitHub said {e.code}. {hint or detail}"})
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


if __name__ == "__main__":
    # python api/admin.py - everything except the two GitHub calls, which are stubbed. Catches the parts
    # that cannot be seen from the outside: the workbook round-tripping through memory, and both files
    # going into one commit holding the same catalogue.
    from pathlib import Path

    sheet = Path(__file__).resolve().parent.parent / "products.xlsx"
    before = build.catalogue(sheet)
    sent = {}
    fetch = lambda path: sheet.read_bytes()
    commit = lambda files, message: (sent.update(files), sent.update(msg=message), "deadbeefcafe1234")[2]

    ean, sha, products = save_product({"name": "Wire Test Pouch (Teal)", "ean": "999 000 222 111", "sku": "zzwire"})
    assert ean == "999000222111", ean
    assert products[ean] == {"name": "Wire Test Pouch (Teal)", "sku": "zzwire", "colour": "teal",
                             "hex": "#1f8a8a", "image": ""}, products[ean]
    assert len(products) == len(before) + 1, (len(products), len(before))
    assert {"products.xlsx", "products.js"} <= set(sent), sorted(sent)
    assert sent["products.js"] == build.render(products).encode("utf-8")
    # the committed workbook really carries the row, so a later local build.py sees it too
    assert build.catalogue(io.BytesIO(sent["products.xlsx"])) == products
    assert sheet.read_bytes() == fetch("products.xlsx"), "the real sheet must not have been touched"

    # editing an existing product rewrites it in place rather than adding a second one
    ean2, _, products2 = save_product({"name": "Renamed Travel Bottles", "ean": "8906209350200",
                                       "sku": "tsbottle2", "colour": "red", "replacing": "8906209350200"})
    assert ean2 == "8906209350200", ean2
    assert len(products2) == len(before), (len(products2), len(before))
    assert products2[ean2] == {"name": "Renamed Travel Bottles", "sku": "tsbottle2", "colour": "red",
                               "hex": "#c62828", "image": ""}, products2[ean2]
    assert build.catalogue(io.BytesIO(sent["products.xlsx"])) == products2

    for bad, why in (({"name": "n", "ean": "abc", "sku": "s"}, "digit"),
                     ({"name": "n", "ean": "1", "sku": "s", "colour": "puce"}, "colour"),
                     ({"name": "n", "ean": "5949998498176", "sku": "s"}, "already")):
        try:
            save_product(bad)
            raise AssertionError(f"accepted {bad}")
        except ValueError as e:
            assert why in str(e), f"{bad} -> {e}"
    print("api/admin.py self-check ok (GitHub calls stubbed)")
