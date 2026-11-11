"""Bounded offline JSON/JSONL and OOXML readers. No formula or link evaluation.

OOXML support intentionally decodes stored values, not Excel display formatting.
"""
import io
import json
import posixpath
import re
import zipfile
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

MAX_BYTES = 20 * 1024 * 1024
MAX_EXPANDED = 40 * 1024 * 1024
MAX_ROWS = 100_000
MAX_CELLS = 1_000_000
MAX_COLUMNS = 128
MAX_CELL = 65_536
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


class ParseError(ValueError):
    pass


def text(data):
    if len(data) > MAX_BYTES:
        raise ParseError("LIMIT: input exceeds 20 MiB")
    try:
        value = data.decode("utf-8-sig")
    except UnicodeError:
        raise ParseError("ENCODING: only UTF-8 / UTF-8 BOM is supported") from None
    if "\x00" in value:
        raise ParseError("INPUT: NUL bytes refused")
    return value


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ParseError("JSON: duplicate object keys refused")
        result[key] = value
    return result


def constant(_):
    raise ParseError("JSON: non-finite numbers refused")


def load_json(value):
    try:
        return json.loads(value, object_pairs_hook=pairs, parse_int=str,
                          parse_float=str, parse_constant=constant)
    except (json.JSONDecodeError, RecursionError):
        raise ParseError("JSON: invalid syntax or excessive nesting; no partial plan") from None


def scalar(value):
    if value is None:
        return ""
    if type(value) is bool:
        return "true" if value else "false"
    if not isinstance(value, str):
        raise ParseError("JSON: nested values refused; supply flat objects only")
    if len(value) > MAX_CELL or "\x00" in value:
        raise ParseError("LIMIT: oversized or NUL-containing cell")
    return value


def read_json(data, lines=False):
    value = text(data)
    if lines:
        records = []
        skipped = 0
        for line in value.splitlines():
            if not line.strip():
                skipped += 1
                continue
            if len(records) >= MAX_ROWS:
                raise ParseError("LIMIT: more than 100,000 records")
            records.append(load_json(line))
    else:
        records = load_json(value)
        records = [records] if isinstance(records, dict) else records
        skipped = 0
    if not isinstance(records, list) or not records:
        raise ParseError("JSON: expected a nonempty array of flat objects or a single flat object")
    if len(records) > MAX_ROWS:
        raise ParseError("LIMIT: more than 100,000 records")
    header, seen = [], set()
    for record in records:
        if not isinstance(record, dict) or not record:
            raise ParseError("JSON: every record must be a nonempty flat object")
        for key, val in record.items():
            scalar(val)
            if key not in seen:
                seen.add(key)
                header.append(key)
        if len(header) > MAX_COLUMNS:
            raise ParseError("LIMIT: more than 128 columns")
    if (len(records) + 1) * len(header) > MAX_CELLS:
        raise ParseError("LIMIT: more than 1,000,000 cells")
    rows = [[scalar(record.get(key)) for key in header] for record in records]
    return header, rows, {"format": "jsonl" if lines else "json", "blank_lines_skipped": skipped, "cell_issues": []}


def xml(data):
    try:
        from defusedxml import ElementTree
        from defusedxml.common import DefusedXmlException
    except ImportError:
        raise ParseError("DEPENDENCY: install the declared defusedxml==0.7.1 dependency for XLSX") from None
    try:
        return ElementTree.fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except (ElementTree.ParseError, DefusedXmlException):
        raise ParseError("XLSX: unsafe or malformed XML refused") from None


def column_index(ref, row_no):
    match = re.fullmatch(r"([A-Z]{1,3})([1-9][0-9]{0,6})", ref)
    if not match or int(match[2]) != row_no:
        raise ParseError("XLSX: invalid cell coordinate")
    index = 0
    for char in match[1]:
        index = index * 26 + ord(char) - 64
    if index > MAX_COLUMNS:
        raise ParseError("LIMIT: worksheet exceeds 128 columns")
    return index - 1


def excel_date(value, epoch1904):
    try:
        number = Decimal(value)
        if not number.is_finite() or number != number.to_integral_value() or number < 0 or number > 2958465:
            return None  # time-bearing / invalid dates are not silently truncated
        days = int(number)
        if not epoch1904 and days in (0, 60):
            return None  # Excel's fictitious 1900-02-29 is not a real date
        origin = date(1904, 1, 1) if epoch1904 else date(1899, 12, 30)
        return (origin + timedelta(days=days + (1 if not epoch1904 and days < 60 else 0))).isoformat()
    except (InvalidOperation, ValueError, OverflowError):
        return None


def read_xlsx(data, sheet=None):
    if len(data) > MAX_BYTES:
        raise ParseError("LIMIT: input exceeds 20 MiB")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError):
        raise ParseError("XLSX: invalid ZIP container") from None
    with archive:
        members = archive.infolist()
        names = [info.filename for info in members]
        if len(members) > 1024 or len(names) != len(set(names)):
            raise ParseError("XLSX: too many or duplicate ZIP entries")
        total = 0
        for info in members:
            name = info.filename
            if name.startswith("/") or "\\" in name or ".." in name.split("/") or info.flag_bits & 1:
                raise ParseError("XLSX: unsafe or encrypted ZIP entry")
            if "vbaproject" in name.lower():
                raise ParseError("XLSX: macros refused")
            total += info.file_size
            if total > MAX_EXPANDED or info.file_size > 32 * 1024 * 1024 or info.file_size > max(1024 * 1024, info.compress_size * 200):
                raise ParseError("LIMIT: XLSX expanded-size or compression-ratio budget exceeded")

        def part(name, optional=False):
            if name not in names:
                if optional:
                    return None
                raise ParseError("XLSX: required workbook part missing")
            try:
                content = archive.read(name)
            except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError):
                raise ParseError("XLSX: corrupt or unsupported ZIP member") from None
            return xml(content)

        book = part("xl/workbook.xml")
        available = book.findall("s:sheets/s:sheet", NS)
        if not available:
            raise ParseError("XLSX: workbook has no worksheets")
        if not sheet and len(available) != 1:
            raise ParseError("XLSX: multiple worksheets; set an explicit contract.sheet / sheet argument")
        chosen = next((s for s in available if s.get("name") == sheet), None) if sheet else available[0]
        if chosen is None:
            raise ParseError("XLSX: selected worksheet not found")
        rels = part("xl/_rels/workbook.xml.rels")
        relationship = next((r for r in rels if r.get("Id") == chosen.get("{" + REL + "}id")), None)
        if relationship is None or relationship.get("TargetMode") == "External":
            raise ParseError("XLSX: invalid/external worksheet relationship")
        target = relationship.get("Target", "")
        target = posixpath.normpath(target.lstrip("/") if target.startswith("/") else "xl/" + target)
        if not target.startswith("xl/worksheets/") or not target.endswith(".xml"):
            raise ParseError("XLSX: unsupported worksheet relationship")
        shared, shared_cells = [], 0
        strings = part("xl/sharedStrings.xml", True)
        if strings is not None:
            for si in strings.findall("s:si", NS):
                val = "".join(t.text or "" for t in si.findall(".//s:t", NS))
                shared_cells += 1
                if shared_cells > MAX_CELLS or len(val) > MAX_CELL:
                    raise ParseError("LIMIT: XLSX shared-string budget exceeded")
                shared.append(val)
        styles = part("xl/styles.xml", True)
        date_styles = set()
        if styles is not None:
            custom = {int(n.get("numFmtId")): n.get("formatCode", "") for n in styles.findall("s:numFmts/s:numFmt", NS)}
            for i, xf in enumerate(styles.findall("s:cellXfs/s:xf", NS)):
                fmt = int(xf.get("numFmtId", "0"))
                # Conservative date-only formats; no currency/grouping/locale guesses.
                if fmt in {14, 15, 16, 17} or custom.get(fmt, "").lower() in {"yyyy-mm-dd", "dd/mm/yyyy", "mm/dd/yyyy"}:
                    date_styles.add(i)
        pr = book.find("s:workbookPr", NS)
        epoch1904 = pr is not None and pr.get("date1904") in ("1", "true")
        worksheet = part(target)
        rows, issues, total_cells = [], [], 0
        for row in worksheet.findall("s:sheetData/s:row", NS):
            try:
                row_no = int(row.get("r", str(len(rows) + 1)))
            except ValueError:
                raise ParseError("XLSX: invalid row coordinate") from None
            if row_no <= len(rows) or row_no > MAX_ROWS + 1:
                raise ParseError("LIMIT: unordered or excessive worksheet rows")
            while len(rows) < row_no - 1:
                rows.append([])
            values, occupied = [], set()
            for cell in row.findall("s:c", NS):
                idx = column_index(cell.get("r", ""), row_no)
                if idx in occupied:
                    raise ParseError("XLSX: duplicate cell coordinates")
                occupied.add(idx)
                while len(values) <= idx:
                    values.append("")
                kind = cell.get("t", "n")
                raw = cell.find("s:v", NS)
                value = raw.text or "" if raw is not None else ""
                if cell.find("s:f", NS) is not None:
                    value = "=" + (cell.find("s:f", NS).text or "EXCEL_FORMULA")
                    issues.append({"row": row_no, "index": idx, "code": "EXCEL_FORMULA"})
                elif kind == "inlineStr":
                    value = "".join(t.text or "" for t in cell.findall("s:is//s:t", NS))
                elif kind == "s":
                    try:
                        if not value.isdigit() or int(value) >= len(shared):
                            raise ValueError
                        value = shared[int(value)]
                    except (ValueError, IndexError):
                        raise ParseError("XLSX: invalid shared-string index") from None
                elif kind == "b":
                    if value not in ("0", "1"):
                        raise ParseError("XLSX: invalid boolean cell")
                    value = "true" if value == "1" else "false"
                elif kind == "e":
                    issues.append({"row": row_no, "index": idx, "code": "EXCEL_ERROR"})
                elif kind not in ("n", "str", "d"):
                    raise ParseError("XLSX: unsupported cell type")
                elif kind == "n" and int(cell.get("s", "0")) in date_styles and value:
                    decoded = excel_date(value, epoch1904)
                    if decoded is None:
                        issues.append({"row": row_no, "index": idx, "code": "EXCEL_DATE"})
                    else:
                        value = decoded
                if len(value) > MAX_CELL or "\x00" in value:
                    raise ParseError("LIMIT: oversized or NUL-containing XLSX cell")
                values[idx] = value
            total_cells += len(values)
            if total_cells > MAX_CELLS:
                raise ParseError("LIMIT: more than 1,000,000 cells")
            rows.append(values)
        if not rows or not rows[0]:
            raise ParseError("HEADER: worksheet row 1 must contain a header")
        header = rows[0]
        body = [r + [""] * max(0, len(header) - len(r)) for r in rows[1:]]
        if (len(body) + 1) * len(header) > MAX_CELLS:
            raise ParseError("LIMIT: more than 1,000,000 cells")
        if any(i["row"] == 1 for i in issues):
            raise ParseError("HEADER: formula/error/date-invalid header cell refused")
        return header, body, {"format": "xlsx", "sheet": chosen.get("name"), "worksheets": [s.get("name") for s in available], "cell_issues": issues}
