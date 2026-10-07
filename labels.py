"""Label PDFs -> labels/*.png + labels.js, so the app reads ASIN labels and shows each product's labels.
Run when the labels change:  python labels.py <labels folder>
The folder holds one subfolder per label set, and the sheet that lists each set's SKUs ("lable and sku, images.xlsx").
"""
import json, re, sys
from pathlib import Path
import pymupdf
from openpyxl import load_workbook

HERE = Path(__file__).parent
CODE = re.compile(r"\b(B0[0-9A-Z]{8}|\d{13})\b")  # every label prints its barcode's value: an Amazon ASIN or an EAN-13
SETS = {"3x2 inch lables": "E-trade", "3x2 lable Bigbasket": "Bigbasket", "3x2 lable UAE LABELS PRODUCT WISE": "UAE"}  # folder -> caption


def norm(sku):
    return re.sub(r"[\W_]", "", sku.lower())  # labels say "fstool-pack-2", products.xlsx says "fstool-pack2"


def sheet_skus(xlsx):
    found = set()
    for ws in load_workbook(xlsx, read_only=True, data_only=True).worksheets:
        col = None
        for row in ws.iter_rows(values_only=True):
            cells = [str(c or "").strip().lower() for c in row]
            if col is not None and col < len(cells) and cells[col]:
                found.add(cells[col])
            elif col is None and "sku" in cells:
                col = cells.index("sku")
    return found


def sku_on(label, known):
    """The one known SKU written on the label or in its file name, else None."""
    hits = {s for s in known if re.search(rf"(?<![\w-]){re.escape(s)}(?![\w-])", label)}
    return hits.pop() if len(hits) == 1 else None


def main(root):
    products = json.loads((HERE / "products.js").read_text(encoding="utf-8").split("=", 1)[1].rstrip().rstrip(";"))
    product_sku = {norm(p["sku"]): p["sku"].lower() for p in products.values()}
    known = set(product_sku.values()).union(*(sheet_skus(x) for x in root.glob("*.xlsx")))
    (HERE / "labels").mkdir(exist_ok=True)
    for old in (HERE / "labels").glob("*.png"):
        old.unlink()
    labels = {}
    for pdf in sorted(root.rglob("*.pdf")):
        group = SETS.get(pdf.relative_to(root).parts[0], pdf.relative_to(root).parts[0])
        for page in pymupdf.open(pdf):
            text = page.get_text()
            codes, sku = set(CODE.findall(text)), sku_on(f"{pdf.stem} {text}".lower(), known)
            if len(codes) != 1 or not sku:
                print(f"skipped {pdf.name} page {page.number + 1}: codes {codes or 'none'}, SKU {sku or 'not found'}")
                continue
            code = codes.pop()
            src = f"labels/{norm(group)}-{code}.png"
            if src not in labels:  # most labels are both in their own PDF and in the combined one
                page.get_pixmap(dpi=200, colorspace=pymupdf.csGRAY).save(HERE / src)
                labels[src] = {"code": code, "sku": product_sku.get(norm(sku), sku), "set": group, "src": src}
    for label in labels.values():
        if norm(label["sku"]) not in product_sku:
            print(f"no product for SKU {label['sku']} ({label['set']} label {label['code']}): add it to products.xlsx")
    (HERE / "labels.js").write_text("const LABELS = " + json.dumps(list(labels.values()), indent=1) + ";\n", encoding="utf-8")
    print(f"{len(labels)} labels -> labels/, labels.js")


if __name__ == "__main__":
    assert sku_on("lazer stool, pack of 2 | fstool-pack-2 b0ghr7kjq6", {"fstool", "fstool-pack-2"}) == "fstool-pack-2"
    assert sku_on("pcblack label uae", {"pcblack", "pc"}) == "pcblack"
    assert norm("fstool-pack-2") == norm("fstool-Pack2")
    main(Path(sys.argv[1]))
