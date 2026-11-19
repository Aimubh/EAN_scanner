"""The catalogue's rules, and Google Sheet -> products.js.  Refresh the offline copy:  python build.py
Columns: Product Name | EAN | SKU | Images (or "Image Link") | Colour (optional, overrides the guess)

Nothing here touches the network or the disk except build(); it is plain functions over the sheet's
rows, so the local panel (admin.py), the live one (api/admin.py) and this CLI all apply identical
rules. The sheet is the database - see sheet.py - and products.js is the copy baked into the deploy
so the scanner still works on a phone with no signal.
"""
import json, re, sys
from pathlib import Path

HERE = Path(__file__).parent

# name -> swatch hex. Multi-word names first so "dark blue" wins over "blue".
# ponytail: colour is guessed from the name/SKU text; fill the Colour column when the guess falls short.
COLOURS = {
    "dark blue": "#1f2f5c", "light blue": "#9cc4e4", "baby pink": "#f4c2d0", "pista green": "#93c572",
    "dark green": "#1f5e3a", "rose red": "#c21e56", "multi color": "", "multi-color": "", "multicolor": "",
    "black": "#1b1c1f", "grey": "#8a8d91", "blue": "#2f5fa8", "white": "#f4f4f2", "cream": "#ece2cc",
    "pink": "#e8a0bf", "purple": "#6b3fa0", "green": "#3a8f4a", "cyan": "#3ec1d3", "teal": "#1f8a8a",
    "red": "#c62828", "brown": "#6e4b2a", "peach": "#f7c6a3", "lavender": "#b7a3d9", "silver": "#c0c4c8",
    "gold": "#d4af37", "golden": "#d4af37",  # not "transparent"/"clear": they describe windows and displays, not the item
}
IN_NAME = re.compile(r"\b(" + "|".join(COLOURS) + r")\b", re.I)
IMAGE_HEADERS = ("images", "image link", "image")  # whichever one the sheet uses


def colour_of(name, sku):
    found = IN_NAME.findall(name)
    if found:
        return found[-1].lower()  # variant colour is the last one mentioned
    return next((c for c in COLOURS if sku.lower().endswith(c.replace(" ", ""))), "")


def ean_key(ean):
    # Sheets hands back display text, but a pasted EAN may carry spaces or leading zeros. Drop both,
    # everywhere, so the same product is the same key however it was typed.
    if isinstance(ean, float):
        ean = int(ean)
    return re.sub(r"\D", "", str(ean)).lstrip("0")


def image_url(link):
    drive = re.search(r"/d/([\w-]+)", link or "")
    return f"https://drive.google.com/thumbnail?id={drive[1]}&sz=w1000" if drive else (link or "")


def columns(rows):
    """{header, lowercased: its column index} from the sheet's first row."""
    return {str(h).strip().lower(): i for i, h in enumerate(rows[0]) if str(h).strip()}


def cell(row, col, header):
    """One cell by header name, blank when the sheet is short or has no such column."""
    at = col.get(header)
    return str(row[at]).strip() if at is not None and at < len(row) else ""


def catalogue(rows):
    """{ean: product} from the sheet's rows, exactly as the browser will see them."""
    col = columns(rows)
    products = {}
    for row in rows[1:]:
        key = ean_key(cell(row, col, "ean"))
        if not key:
            continue
        if key in products:
            print(f"warning: duplicate EAN {key}, keeping the last row")
        name, sku = cell(row, col, "product name"), cell(row, col, "sku")
        colour = (cell(row, col, "colour") or cell(row, col, "color")).lower() or colour_of(name, sku)
        image = next((cell(row, col, h) for h in IMAGE_HEADERS if cell(row, col, h)), "")
        products[key] = {"name": name, "sku": sku, "colour": colour,
                         "hex": COLOURS.get(colour, ""), "image": image_url(image)}
    return products


def index_of(rows, ean):
    """The zero-based data row holding this EAN, or None."""
    col = columns(rows)
    for i, row in enumerate(rows[1:]):
        if ean and ean_key(cell(row, col, "ean")) == ean:
            return i
    return None


def save(rows, form, replacing=None):
    """Check the form against the sheet and work out the write: (index, values, ean).

    index is the data row to overwrite, or None to append. Raises ValueError on anything the sheet
    should not take, before any write is attempted.
    """
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
    col = columns(rows)
    for required in ("product name", "ean", "sku"):
        if required not in col:
            raise ValueError(f"the sheet has no {required!r} column")
    if colour and "colour" not in col:
        raise ValueError("the sheet has no 'Colour' column, so a colour cannot be set")
    holder = index_of(rows, ean)
    if replacing is None:
        if holder is not None:
            raise ValueError(f"EAN {ean} is already in the catalogue")
        index = None
    else:
        index = index_of(rows, ean_key(replacing))
        if index is None:
            raise ValueError(f"EAN {replacing} is not in the catalogue, so there is nothing to update")
        if holder is not None and holder != index:  # the EAN was edited onto one another product owns
            raise ValueError(f"EAN {ean} already belongs to another product")
    values = [""] * len(rows[0])
    for header, value in (("product name", name), ("ean", ean), ("sku", sku), ("colour", colour),
                          (next((h for h in IMAGE_HEADERS if h in col), "images"), image)):
        if header in col:  # written even when blank, so clearing a colour or an image on an edit sticks
            values[col[header]] = value
    return index, values, ean


def removal(rows, ean):
    """The data row to delete for this EAN. Raises ValueError when there is no such product."""
    key = ean_key(ean)
    index = index_of(rows, key)
    if index is None:
        raise ValueError(f"EAN {ean} is not in the catalogue")
    return index, key


def render(products):
    """products.js, exactly as the browser expects to find it."""
    return "var PRODUCTS = " + json.dumps(products, indent=1, ensure_ascii=False) + ";\n"


def build(rows=None):
    """Refresh products.js, the copy that works with no signal, from the sheet."""
    import sheet
    products = catalogue(rows if rows is not None else sheet.rows())
    out = HERE / "products.js"
    out.write_text(render(products), encoding="utf-8")
    print(f"{len(products)} products -> {out.name}")
    return products


def self_check():
    sheet_rows = [
        ["Product Name", "EAN", "SKU", "Images", "Colour"],
        ["Organizer Bag (Dark Blue)", "5949998498176", "obag", "https://drive.google.com/file/d/ABC/view", ""],
        ["Plain Box", "0 8906 2093 5020 0", "sqboxcream", "", "teal"],
    ]
    made = catalogue(sheet_rows)
    assert set(made) == {"5949998498176", "8906209350200"}, sorted(made)
    assert made["5949998498176"] == {"name": "Organizer Bag (Dark Blue)", "sku": "obag", "colour": "dark blue",
                                     "hex": "#1f2f5c", "image": "https://drive.google.com/thumbnail?id=ABC&sz=w1000"}
    assert made["8906209350200"]["colour"] == "teal", "the Colour column beats the guess"
    assert colour_of("Black zipper bag - Grey", "x") == "grey"
    assert colour_of("Jewellery Organiser", "jcasegolden") == "golden"
    assert ean_key(8906209350897.0) == ean_key("0 8906209350897") == "8906209350897"

    # a new product is appended, and lands in the sheet's own column order
    index, values, ean = save(sheet_rows, {"name": "New Pouch", "ean": "999 000 111", "sku": "zznew", "colour": "red"})
    assert (index, ean) == (None, "999000111"), (index, ean)
    assert values == ["New Pouch", "999000111", "zznew", "", "red"], values
    # an edit rewrites the row it names, and a blank field really blanks
    index, values, ean = save(sheet_rows, {"name": "Renamed", "ean": "5949998498176", "sku": "obag"},
                              replacing="5949998498176")
    assert (index, ean) == (0, "5949998498176"), (index, ean)
    assert values == ["Renamed", "5949998498176", "obag", "", ""], values
    # an edit may move a product to a free EAN
    assert save(sheet_rows, {"name": "Moved", "ean": "777", "sku": "obag"}, replacing="5949998498176")[0] == 0
    assert removal(sheet_rows, "0 8906209350200") == (1, "8906209350200")

    for bad, why, replacing in (
            ({"name": "", "ean": "1", "sku": "s"}, "name", None),
            ({"name": "n", "ean": "1", "sku": ""}, "SKU", None),
            ({"name": "n", "ean": "", "sku": "s"}, "EAN", None),
            ({"name": "n", "ean": "abc", "sku": "s"}, "digit", None),
            ({"name": "n", "ean": "1", "sku": "s", "colour": "puce"}, "colour", None),
            ({"name": "n", "ean": "5949998498176", "sku": "s"}, "already", None),
            ({"name": "n", "ean": "1", "sku": "s"}, "nothing to update", "404404"),
            ({"name": "n", "ean": "8906209350200", "sku": "s"}, "another product", "5949998498176")):
        try:
            save(sheet_rows, bad, replacing)
            raise AssertionError(f"accepted {bad}")
        except ValueError as e:
            assert why in str(e), f"{bad} -> {e}"
    try:
        removal(sheet_rows, "404404404")
        raise AssertionError("accepted a delete of a product that is not there")
    except ValueError as e:
        assert "not in the catalogue" in str(e), e
    print("build.py self-check ok")


if __name__ == "__main__":
    self_check()
    if "--check" not in sys.argv:
        build()
