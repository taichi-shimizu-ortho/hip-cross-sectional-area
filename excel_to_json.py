"""Export Excel cell data before creating a separate, conservative cleaned JSON.

The raw stage reads OOXML directly, avoiding inflated worksheet dimensions.
The clean stage reads only that saved JSON and never changes the workbook.
No clinical eligibility decisions or patient-level merges are performed.
"""

import argparse
from collections import Counter
from datetime import date, datetime, time, timedelta
import hashlib
import json
import math
from pathlib import Path
import posixpath
import re
import unicodedata
from xml.etree import ElementTree as ET
from zipfile import ZipFile, is_zipfile
from zoneinfo import ZoneInfo

from openpyxl.styles.numbers import BUILTIN_FORMATS, is_date_format, is_timedelta_format
from openpyxl.utils.datetime import CALENDAR_MAC_1904, CALENDAR_WINDOWS_1900, from_excel

from hip_paths import INPUT_DIR, JOA_DIR, from_home

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def stamp():
    return datetime.now(ZoneInfo("Asia/Tokyo")).isoformat()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(data, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Existing exports are review artifacts. Do not silently replace them.
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def rich_text(element):
    if element is None:
        return ""
    return "".join(node.text or "" for node in element.findall("m:t", NS)
                   + element.findall("m:r/m:t", NS))


def export_raw(source):
    if not is_zipfile(source):
        raise ValueError("The workbook is encrypted or is not an OOXML workbook. An unlocked copy is required.")
    source_hash = digest(source)
    with ZipFile(source) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = [rich_text(si) for si in ET.fromstring(
                archive.read("xl/sharedStrings.xml")).findall("m:si", NS)]
        styles = ET.fromstring(archive.read("xl/styles.xml"))
        formats = dict(BUILTIN_FORMATS)
        formats.update({int(n.attrib["numFmtId"]): n.attrib["formatCode"]
                        for n in styles.findall("m:numFmts/m:numFmt", NS)})
        style_formats = [int(x.attrib.get("numFmtId", 0))
                         for x in styles.findall("m:cellXfs/m:xf", NS)]
        properties = workbook.find("m:workbookPr", NS)
        date1904 = properties is not None and properties.attrib.get("date1904", "0") in {"1", "true"}
        sheets = []
        for sheet in workbook.findall("m:sheets/m:sheet", NS):
            target = targets[sheet.attrib[REL_ID]]
            member = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
            root = ET.fromstring(archive.read(member))
            dimension = root.find("m:dimension", NS)
            rows = []
            omitted = 0
            for row in root.findall("m:sheetData/m:row", NS):
                cells = []
                for cell in row.findall("m:c", NS):
                    value_node = cell.find("m:v", NS)
                    inline_node = cell.find("m:is", NS)
                    formula_node = cell.find("m:f", NS)
                    if value_node is None and inline_node is None and formula_node is None:
                        omitted += 1
                        continue
                    value = value_node.text if value_node is not None else None
                    cell_type = cell.attrib.get("t", "n")
                    resolved = value
                    kind = "text"
                    if cell_type == "s" and value is not None:
                        resolved = strings[int(value)]
                    elif cell_type == "inlineStr":
                        resolved = rich_text(inline_node)
                    elif cell_type == "b":
                        resolved, kind = (value == "1" if value is not None else None), "boolean"
                    elif cell_type == "n":
                        kind = "number"
                        if value is not None:
                            resolved = int(value) if re.fullmatch(r"[+-]?\d+", value) else float(value)
                            if isinstance(resolved, float) and not math.isfinite(resolved):
                                raise ValueError("Non-finite numeric cell encountered.")
                    elif cell_type == "e":
                        kind = "error"
                    elif cell_type == "d":
                        kind = "iso_date"
                    cells.append({
                        "address": cell.attrib["r"], "attributes": dict(cell.attrib),
                        "stored_value": value, "value": resolved, "kind": kind,
                        "formula": None if formula_node is None else {
                            "text": formula_node.text, "attributes": dict(formula_node.attrib)},
                    })
                if cells:
                    rows.append({"source_row": int(row.attrib["r"]), "cells": cells})
            sheets.append({
                "name": sheet.attrib["name"], "state": sheet.attrib.get("state", "visible"),
                "xml_member": member,
                "declared_dimension": None if dimension is None else dimension.attrib.get("ref"),
                "merged_ranges": [x.attrib["ref"] for x in root.findall("m:mergeCells/m:mergeCell", NS)],
                "omitted_formatting_only_cell_count": omitted,
                "rows": rows,
            })
    if digest(source) != source_hash:
        raise ValueError("Source workbook changed during export. Retry with a stable source file.")
    return {
        "schema_version": 1, "stage": "raw_excel_cell_data", "created_at": stamp(),
        "source": {"path": from_home(source), "sha256": source_hash},
        "preservation": "Cell-data export, not a full workbook backup. Cell values, formula text and attributes, cached results, coordinates, sheet visibility and merged ranges are retained. Formatting-only cells, charts, images, comments and other workbook presentation objects are not exported; the source workbook is retained unchanged.",
        "date_system": "1904" if date1904 else "1900",
        "style_number_format_ids": style_formats,
        "number_formats": {str(key): value for key, value in formats.items()},
        "sheets": sheets,
    }


def normalize_text(value):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()


HEADER_FIELDS = {
    "手術日": "surgery_date", "date of surgery": "surgery_date",
    "氏名": "patient_name", "patient name": "patient_name",
    "患者id": "patient_id", "id": "patient_id",
    "生年月日": "date_of_birth", "date of birth": "date_of_birth",
    "年齢": "age", "年": "age", "性": "sex", "左右": "laterality",
    "部位": "anatomical_site", "joint": "anatomical_site",
    "疾患名": "diagnosis", "病名": "diagnosis", "preope dx": "diagnosis",
    "術式": "procedure", "surgical procedure": "procedure",
}


def clean_raw(raw, raw_path):
    epoch = CALENDAR_MAC_1904 if raw["date_system"] == "1904" else CALENDAR_WINDOWS_1900
    changes = Counter()
    all_flags = Counter()
    sheets = []
    for sheet in raw["sheets"]:
        rows = []
        active_header = {}
        seen = {}
        for row in sheet["rows"]:
            values, kinds, formulas, row_changes, flags = {}, {}, {}, {}, []
            for cell in row["cells"]:
                column = re.sub(r"\d+$", "", cell["address"])
                value, kind = cell["value"], cell["kind"]
                transformations = []
                style_id = int(cell["attributes"].get("s", "0"))
                format_id = raw["style_number_format_ids"][style_id]
                fmt = raw["number_formats"].get(str(format_id), "General")
                if isinstance(value, str) and kind == "text":
                    normalized = normalize_text(value)
                    if normalized != value:
                        transformations.append("NFKC_and_whitespace_normalization")
                    value = normalized
                    if not value:
                        value, kind = None, "null"
                        transformations.append("empty_text_to_null")
                elif isinstance(value, (int, float)) and not isinstance(value, bool) and kind == "number" and is_date_format(fmt):
                    if raw["date_system"] == "1900" and 60 <= value < 61:
                        flags.append({"code": "excel_fictitious_1900_02_29", "column": column})
                    else:
                        try:
                            converted = from_excel(value, epoch, timedelta=is_timedelta_format(fmt))
                            if isinstance(converted, timedelta):
                                value, kind = converted.total_seconds(), "duration_seconds"
                            elif isinstance(converted, datetime):
                                value, kind = converted.isoformat(), "datetime"
                            elif isinstance(converted, time):
                                value, kind = converted.isoformat(), "time"
                            elif isinstance(converted, date):
                                value, kind = converted.isoformat(), "date"
                            transformations.append("excel_serial_to_ISO_or_duration")
                        except (ValueError, OverflowError):
                            flags.append({"code": "invalid_excel_date", "column": column})
                if cell["formula"] is not None:
                    formulas[column] = cell["formula"]
                    flags.append({"code": "formula_cache_not_recalculated", "column": column})
                    if value is None:
                        flags.append({"code": "formula_missing_cached_value", "column": column})
                if kind == "error":
                    flags.append({"code": "source_excel_error", "column": column})
                values[column], kinds[column] = value, kind
                if transformations:
                    row_changes[column] = transformations
                    changes.update(transformations)
            detected = {col: HEADER_FIELDS[v.lower()] for col, v in values.items()
                        if isinstance(v, str) and v.lower() in HEADER_FIELDS}
            is_header = len(detected) >= 3
            if is_header:
                active_header = detected
            else:
                inverse = {field: col for col, field in active_header.items()}
                identity_present = any(values.get(inverse.get(field)) is not None
                                       for field in ["patient_id", "patient_name"] if field in inverse)
                if identity_present:
                    for field, allowed in [("sex", {"M", "F", "男", "女", "男性", "女性", "male", "female"}),
                                           ("laterality", {"R", "L", "B", "両", "両側", "右", "左", "右側", "左側", "right", "left", "bilateral"})]:
                        col = inverse.get(field)
                        if col and values.get(col) is not None and values[col] not in allowed:
                            flags.append({"code": f"unexpected_{field}_or_shifted_columns", "column": col})
                    col = inverse.get("age")
                    if col and values.get(col) is not None:
                        age = values[col]
                        if isinstance(age, bool) or not (isinstance(age, (int, float)) or (isinstance(age, str) and re.fullmatch(r"\d+(\.\d+)?", age))):
                            flags.append({"code": "non_numeric_age_or_shifted_columns", "column": col})
                signature = json.dumps(values, ensure_ascii=False, sort_keys=True)
                if signature in seen:
                    flags.append({"code": "duplicate_normalized_row_retained", "first_source_row": seen[signature]})
                else:
                    seen[signature] = row["source_row"]
            all_flags.update(flag["code"] for flag in flags)
            rows.append({"source_row": row["source_row"],
                         "row_kind": "header" if is_header else "data_or_note",
                         "values": values, "value_types": kinds,
                         "header_field_map": dict(active_header),
                         "formulas": formulas, "transformations": row_changes, "flags": flags})
        sheets.append({"name": sheet["name"], "declared_dimension": sheet["declared_dimension"],
                       "merged_ranges": sheet["merged_ranges"], "rows": rows})
    return {
        "schema_version": 1, "stage": "structurally_cleaned_excel_cell_data",
        "created_at": stamp(), "source_raw_json": {"path": from_home(raw_path), "sha256": digest(raw_path)},
        "source_excel": raw["source"],
        "rules": ["NFKC text normalization and collapse/trim whitespace; keep raw text in the raw JSON.",
                  "Convert empty text to null; preserve numeric zero and boolean false.",
                  "Convert numeric dates/times only when the original number format denotes a date/time; preserve original serials in raw JSON.",
                  "Identify header rows and header-based field mappings without dropping rows or guessing missing headers.",
                  "Retain duplicates, ambiguous values and column shifts with flags; do not impute, merge patients, assign cohorts or exclude cases.",
                  "Retain formula text and cached values without recalculation; flag caches for review."],
        "summary": {"sheet_count": len(sheets), "row_count": sum(len(s["rows"]) for s in sheets),
                    "transformation_counts": dict(changes), "flag_counts": dict(all_flags)},
        "sheets": sheets,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["raw", "clean"])
    parser.add_argument("--source", type=Path)
    parser.add_argument("--raw-json", type=Path, default=JOA_DIR / "surgery_schedule.raw.json")
    parser.add_argument("--clean-json", type=Path, default=JOA_DIR / "surgery_schedule.normalized.json")
    args = parser.parse_args()
    if args.stage == "raw":
        source = args.source
        if source is None:
            candidates = sorted(p for p in INPUT_DIR.glob("*.xlsx") if not p.name.startswith("~$"))
            if len(candidates) != 1:
                parser.error("Specify exactly one source workbook with --source.")
            source = candidates[0]
        result = export_raw(source.expanduser())
        destination = args.raw_json.expanduser()
    else:
        raw_path = args.raw_json.expanduser()
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        if raw.get("stage") != "raw_excel_cell_data":
            parser.error("The cleaning input must be a raw Excel JSON export.")
        result = clean_raw(raw, raw_path)
        destination = args.clean_json.expanduser()
    dump(result, destination)
    print(json.dumps({"saved": from_home(destination), "stage": result["stage"],
                      "sheets": len(result["sheets"]),
                      "rows": sum(len(s["rows"]) for s in result["sheets"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
