"""Excel -> products.js.  Run after editing the sheet:  python build.py [path.xlsx]
Columns: Product Name | EAN | SKU | Images (or "Image Link") | Colour (optional, overrides the guess)
"""
import json, re, sys
from pathlib import Path
from openpyxl import load_workbook

HERE = Path(__file__).parent

# name -> swatch hex. Multi-word names first so "dark blue" wins over "blue".
# ponytail: colour is guessed from the name/SKU text; add a "Colour" column when the guess falls short.
COLOURS = {
    "dark blue": "#1f2f5c", "light blue": "#9cc4e4", "baby pink": "#f4c2d0", "pista green": "#93c572",
    "dark green": "#1f5e3a", "rose red": "#c21e56", "multi color": "", "multi-color": "", "multicolor": "",
    "black": "#1b1c1f", "grey": "#8a8d91", "blue": "#2f5fa8", "white": "#f4f4f2", "cream": "#ece2cc",
    "pink": "#e8a0bf", "purple": "#6b3fa0", "green": "#3a8f4a", "cyan": "#3ec1d3", "teal": "#1f8a8a",
    "red": "#c62828", "brown": "#6e4b2a", "peach": "#f7c6a3", "lavender": "#b7a3d9", "silver": "#c0c4c8",
    "gold": "#d4af37", "golden": "#d4af37",  # not "transparent"/"clear": they describe windows and displays, not the item
}
IN_NAME = re.compile(r"\b(" + "|".join(COLOURS) + r")\b", re.I)


def colour_of(name, sku):
    found = IN_NAME.findall(name)
    if found:
        return found[-1].lower()  # variant colour is the last one mentioned
    return next((c for c in COLOURS if sku.lower().endswith(c.replace(" ", ""))), "")


def ean_key(ean):
    # Excel stores EANs as numbers, which drops leading zeros - so drop them everywhere.
    if isinstance(ean, float):
        ean = int(ean)
    return re.sub(r"\D", "", str(ean)).lstrip("0")


def image_url(link):
    drive = re.search(r"/d/([\w-]+)", link or "")
    return f"https://drive.google.com/thumbnail?id={drive[1]}&sz=w1000" if drive else (link or "")


IMAGE_HEADERS = ("images", "image link", "image")  # whichever one the sheet uses


def add_row(ws, form):
    """Validate the form and append it to the open worksheet, returning the EAN as this module keys it.
    Raises ValueError on anything the sheet should not take. Shared by admin.py and api/admin.py, so a
    product added on this PC and one added from the live page go in under exactly the same rules."""
    get = lambda f: str(form.get(f) or "").strip()
    name, sku, image, colour = get("name"), get("sku"), get("image"), get("colour").lower()
    ean = ean_key(get("ean"))
    for field, value in (("name", name), ("SKU", sku), ("EAN", get("ean"))):
        if not value:
            raise ValueError(f"{field} cannot be empty")
    if not ean:
        raise ValueError("the EAN needs at least one digit")
    if colour and colour not in COLOURS:
        raise ValueError(f"unknown colour {colour!r}")
    col = {str(c.value).strip().lower(): c.column for c in ws[1] if c.value}
    for required in ("product name", "ean", "sku"):
        if required not in col:
            raise ValueError(f"the sheet has no {required!r} column")
    taken = {ean_key(c.value) for c in ws[ws.cell(1, col["ean"]).column_letter][1:] if c.value}
    if ean in taken:
        raise ValueError(f"EAN {ean} is already in the catalogue")
    row = ws.max_row + 1
    if colour and "colour" not in col:  # this module reads a Colour column when there is one, so make it on first use
        col["colour"] = ws.max_column + 1
        ws.cell(1, col["colour"], "Colour")
    cells = {"product name": name, "ean": int(ean), "sku": sku, "colour": colour,
             next((h for h in IMAGE_HEADERS if h in col), "images"): image}
    for header, value in cells.items():
        if header in col and value != "":
            ws.cell(row, col[header], value)
    return ean


def catalogue(xlsx):
    """{ean: product} from the sheet. xlsx is a path, or a file-like object when it came over the wire."""
    wb = load_workbook(xlsx, read_only=True)  # read_only holds the file open: close it, or the next save is blocked on Windows
    rows = wb.active.iter_rows(values_only=True)
    col = {str(h).strip().lower(): i for i, h in enumerate(next(rows)) if h}
    products = {}
    for row in rows:
        get = lambda h: str(row[col[h]] or "").strip() if h in col else ""
        key = ean_key(row[col["ean"]] or "")
        if not key:
            continue
        if key in products:
            print(f"warning: duplicate EAN {key}, keeping the last row")
        colour = (get("colour") or get("color")).lower() or colour_of(get("product name"), get("sku"))
        products[key] = {
            "name": get("product name"), "sku": get("sku"), "colour": colour,
            "hex": COLOURS.get(colour, ""), "image": image_url(get("images") or get("image link") or get("image")),
        }
    wb.close()
    return products


def render(products):
    """products.js, exactly as the browser expects to find it."""
    return "const PRODUCTS = " + json.dumps(products, indent=1, ensure_ascii=False) + ";\n"


def build(xlsx):
    products = catalogue(xlsx)
    out = HERE / "products.js"
    out.write_text(render(products), encoding="utf-8")
    print(f"{len(products)} products -> {out.name}")
    return products


if __name__ == "__main__":
    assert colour_of("Organizer Bag (Dark Blue)", "x") == "dark blue"
    assert colour_of("Black zipper bag - Grey", "x") == "grey"
    assert colour_of("Jewellery Organiser", "sqboxcream") == "cream"
    assert colour_of("Foldable Bag (Rose Red)", "fbag") == "rose red"
    assert colour_of("Jewellery Organiser", "jcasegolden") == "golden"
    assert ean_key(8906209350897.0) == ean_key("0 8906209350897") == "8906209350897"
    build(sys.argv[1] if len(sys.argv) > 1 else HERE / "products.xlsx")
