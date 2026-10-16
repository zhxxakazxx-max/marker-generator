"""Read the supplied workbook without rewriting it; extract only app catalog assets.

WPS DISPIMG images are resolved by their embedded IDs and relationship targets.
No workbook formulas are evaluated and no external image links are fetched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

NS = {
    "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "p": "http://schemas.openxmlformats.org/package/2006/relationships",
    "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
}
PALETTE = [
    ("light_blue", "浅蓝 / Light blue", "#AABED0"),
    ("royal_blue", "宝蓝 / Royal blue", "#354E97"),
    ("ivory", "米白 / Ivory", "#D9D9C9"),
    ("navy", "藏青 / Navy", "#262642"),
    ("teal", "湖蓝 / Teal", "#167F95"),
    ("black", "黑色 / Black", "#262627"),
    ("green", "绿色 / Green", "#2E7149"),
    ("burgundy", "酒红 / Burgundy", "#522333"),
    ("white", "白色 / White", "#F5F3EB"),
    ("grey", "灰色 / Grey", "#7B7A7C"),
    ("red", "红色 / Red", "#BD0925"),
    ("orange", "橙色 / Orange", "#F6A352"),
]
SKIP_VALUES = {"成分", "成份", "(空白)", "（空白）", "总计", "Grand Total"}


def internal_target(base: str, target: str) -> str:
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(base), target))
    if target.startswith("/"):
        resolved = target.lstrip("/")
    if not resolved.startswith("xl/") or "/../" in resolved:
        raise ValueError(f"Unexpected workbook relationship target: {target}")
    return resolved


def relationships(archive: ZipFile, base: str) -> dict[str, str]:
    rel_path = posixpath.join(posixpath.dirname(base), "_rels", posixpath.basename(base) + ".rels")
    tree = ET.fromstring(archive.read(rel_path))
    return {
        item.attrib["Id"]: internal_target(base, item.attrib["Target"])
        for item in tree
        if item.attrib.get("TargetMode") != "External"
    }


def read_source(archive: ZipFile, sheet_name: str) -> tuple[dict, list[dict]]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    sheet = next(
        (s for s in workbook.findall("s:sheets/s:sheet", NS) if s.attrib["name"] == sheet_name),
        None,
    )
    if sheet is None:
        raise ValueError(f"Worksheet not found: {sheet_name}")
    sheet_path = relationships(archive, "xl/workbook.xml")[sheet.attrib[f"{{{NS['r']}}}id"]]
    strings = []
    if "xl/sharedStrings.xml" in archive.namelist():
        strings = [
            "".join(si.itertext())
            for si in ET.fromstring(archive.read("xl/sharedStrings.xml")).findall("s:si", NS)
        ]
    cells, records = {}, []
    tree = ET.fromstring(archive.read(sheet_path))
    for cell in tree.findall("s:sheetData/s:row/s:c", NS):
        address = cell.attrib["r"]
        value = cell.findtext("s:v", default="", namespaces=NS)
        if cell.attrib.get("t") == "s":
            value = strings[int(value)]
        elif cell.attrib.get("t") == "inlineStr":
            value = "".join(cell.find("s:is", NS).itertext())
        formula = cell.findtext("s:f", default="", namespaces=NS)
        cells[address] = {"value": value, "formula": formula}
        if re.fullmatch(r"C\d+", address) and value.strip() and value not in SKIP_VALUES:
            if formula:
                raise ValueError(f"Composition is a formula, not literal data: {sheet_name}!{address}")
            records.append({"source": f"{sheet_name}!{address}", "row": int(address[1:]), "label": value})
    return cells, records


def extract_images(archive: ZipFile, cells: dict, assets: Path, sheet_name: str) -> list[dict]:
    image_xml = "xl/cellimages.xml"
    image_rels = relationships(archive, image_xml)
    image_targets = {}
    for pic in ET.fromstring(archive.read(image_xml)).findall(".//xdr:pic", NS):
        props = pic.find("xdr:nvPicPr/xdr:cNvPr", NS)
        blip = pic.find("xdr:blipFill/a:blip", NS)
        if props is None or blip is None:
            continue
        embed_id = blip.attrib.get(f"{{{NS['r']}}}embed")
        if embed_id in image_rels:
            image_targets[props.attrib["name"]] = image_rels[embed_id]
    fabric_dir = assets / "fabrics"
    fabric_dir.mkdir(parents=True, exist_ok=True)
    colors = []
    for index, (color_id, name, hex_value) in enumerate(PALETTE):
        address = f"{chr(ord('D') + index)}11"
        formula = cells.get(address, {}).get("formula", "")
        match = re.fullmatch(r'(?:_xlfn\.)?DISPIMG\("([A-Za-z0-9_]+)",\s*1\)', formula)
        if match is None:
            raise ValueError(f"Expected WPS DISPIMG reference in {sheet_name}!{address}: {formula!r}")
        dispimg_id = match.group(1)
        target = image_targets[dispimg_id]
        suffix = Path(target).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise ValueError(f"Unsupported original image type: {target}")
        raw = archive.read(target)
        file_name = f"{color_id}{suffix}"
        destination = fabric_dir / file_name
        destination.write_bytes(raw)
        assert destination.read_bytes() == raw
        colors.append({
            "id": color_id,
            "name": name,
            "hex": hex_value,
            "reference": f"fabrics/{file_name}",
            "source": f"{sheet_name}!{address}",
            "reference_role": "color_and_fabric" if index < 8 else "color",
            "image_id": dispimg_id,
            "workbook_media": target,
            "sha256": hashlib.sha256(raw).hexdigest(),
        })
    return colors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--assets", type=Path, default=ROOT / "assets")
    parser.add_argument("--sheet", default="Sheet1")
    parser.add_argument("--images-only", action="store_true", help="Inspect image extraction before the domain parser is available")
    args = parser.parse_args()
    before_hash = hashlib.sha256(args.workbook.read_bytes()).hexdigest()
    with ZipFile(args.workbook) as archive:
        cells, records = read_source(archive, args.sheet)
        colors = extract_images(archive, cells, args.assets, args.sheet)
    if args.images_only:
        print(json.dumps({"composition_count": len(records), "colors": colors}, ensure_ascii=False, indent=2))
        return

    from studio.domain import parse_composition

    compositions, errors = [], []
    for record in records:
        try:
            parts = parse_composition(record["label"])
            compositions.append({"source": record["source"], "label": record["label"], "parts": parts})
        except ValueError as error:
            errors.append({"row": record["row"], "source": record["source"], "value": record["label"], "error": str(error)})
    catalog = {
        "compositions": compositions,
        "errors": errors,
        "colors": colors,
        "provenance": {
            "workbook": args.workbook.name,
            "workbook_sha256": before_hash,
            "compositions_range": f"{args.sheet}!C4:C124",
            "colors_range": f"{args.sheet}!D11:O11",
            "record_count": len(records),
            "swatch_note": "Hex values are approximate UI swatches; the original embedded photographs are the generation references.",
        },
    }
    assert len(compositions) + len(errors) == len(records)
    assert hashlib.sha256(args.workbook.read_bytes()).hexdigest() == before_hash, "Source workbook changed during extraction"
    (args.assets / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"valid": len(compositions), "review_required": len(errors), "colors": len(colors), "errors": errors}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
