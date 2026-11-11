"""Deterministic offline table-contract engine; no model calls or network I/O."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import uuid
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

try:
    from . import formats, drafting, audit
except ImportError:  # documented standalone CLI / unittest entrypoint
    import formats, drafting, audit

VERSION = "0.2.0"
MAX_BYTES = 20 * 1024 * 1024
MAX_ROWS = 100_000
MAX_COLUMNS = 128
MAX_CELL = 65_536
MAX_EVIDENCE = 250
MAX_CELLS = 1_000_000
MAX_CONTRACT_BYTES = 65_536
FORMATS = {"%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"}


class Refusal(ValueError):
    """Expected fail-closed result. Messages never contain cell contents."""


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(data):
    return hashlib.sha256(data).hexdigest()


# Bind unexported plans to the exact reviewable engine source as well as the policy.
ENGINE_SHA256 = digest(b"\0".join((Path(__file__).parent / name).read_bytes() for name in ("core.py", "formats.py", "drafting.py", "audit.py")))


def now():
    return datetime.now(timezone.utc).isoformat()


def private_dir(path):
    path = Path(path)
    # State is operator-owned. Refuse existing symlink components, including parents.
    for p in [path, *path.parents]:
        if p.is_symlink():
            raise Refusal("SYMLINK: state/output directories must not be symlinks")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def validate_contract(contract):
    if not isinstance(contract, dict) or set(contract) - {"columns", "unique_key", "delimiter", "sheet"}:
        raise Refusal("CONTRACT: allowed keys are columns, unique_key, delimiter, sheet")
    delimiter = contract.get("delimiter", ",")
    if delimiter not in (",", ";", "\t", "|"):
        raise Refusal("CONTRACT: delimiter must be comma, semicolon, tab or pipe")
    cols = contract.get("columns")
    if not isinstance(cols, list) or not 1 <= len(cols) <= MAX_COLUMNS:
        raise Refusal("CONTRACT: declare 1–128 ordered columns")
    out = []
    for col in cols:
        if not isinstance(col, dict) or set(col) - {"name", "type", "required", "trim", "enum", "min", "max", "date_format", "decimal_separator"}:
            raise Refusal("CONTRACT: unknown column setting")
        name, kind = col.get("name"), col.get("type", "string")
        if not isinstance(name, str) or not name.strip() or len(name) > 120 or any(ord(x) < 32 for x in name) or formula(name):
            raise Refusal("CONTRACT: invalid/unsafe column name")
        if kind not in ("string", "integer", "decimal", "date"):
            raise Refusal("CONTRACT: type must be string, integer, decimal or date")
        item = {"name": name, "type": kind, "required": col.get("required", True), "trim": col.get("trim", False)}
        if not all(type(item[k]) is bool for k in ("required", "trim")):
            raise Refusal("CONTRACT: required/trim must be booleans")
        if kind == "date":
            if col.get("date_format") not in FORMATS:
                raise Refusal("CONTRACT: date requires an explicit supported date_format")
            item["date_format"] = col["date_format"]
        elif "date_format" in col:
            raise Refusal("CONTRACT: date_format only applies to dates")
        if kind == "decimal":
            if col.get("decimal_separator", ".") not in (".", ","):
                raise Refusal("CONTRACT: decimal_separator must be dot or comma")
            item["decimal_separator"] = col.get("decimal_separator", ".")
        elif "decimal_separator" in col:
            raise Refusal("CONTRACT: decimal_separator only applies to decimals")
        for bound in ("min", "max"):
            if bound in col:
                if kind not in ("integer", "decimal") or not isinstance(col[bound], (str, int)) or isinstance(col[bound], bool):
                    raise Refusal("CONTRACT: ranges require numeric types and string/integer bounds")
                try:
                    v = Decimal(str(col[bound]))
                    if not v.is_finite() or len(str(col[bound])) > 64:
                        raise ValueError
                except (InvalidOperation, ValueError):
                    raise Refusal("CONTRACT: invalid numeric bound") from None
                item[bound] = str(col[bound])
        if "min" in item and "max" in item and Decimal(item["min"]) > Decimal(item["max"]):
            raise Refusal("CONTRACT: min exceeds max")
        if "enum" in col:
            if not isinstance(col["enum"], list) or not 1 <= len(col["enum"]) <= 256 or not all(isinstance(v, str) and len(v) <= 1000 for v in col["enum"]):
                raise Refusal("CONTRACT: enum must be a bounded list of strings")
            item["enum"] = col["enum"]
        out.append(item)
    names = [c["name"] for c in out]
    if len(set(names)) != len(names):
        raise Refusal("CONTRACT: duplicate column names")
    key = contract.get("unique_key", [])
    if not isinstance(key, list) or not all(isinstance(x, str) and x in names for x in key) or len(set(key)) != len(key):
        raise Refusal("CONTRACT: unique_key must name distinct declared columns")
    result = {"columns": out, "unique_key": key, "delimiter": delimiter}
    if "sheet" in contract:
        sheet = contract["sheet"]
        if not isinstance(sheet, str) or not sheet or len(sheet) > 100 or any(ord(c) < 32 for c in sheet):
            raise Refusal("CONTRACT: sheet must be a bounded nonempty worksheet name")
        result["sheet"] = sheet
    if len(canonical(result).encode("utf-8")) > MAX_CONTRACT_BYTES:
        raise Refusal("CONTRACT: normalized contract exceeds 64 KiB")
    return result


def formula(value):
    return bool(value) and (value[0] in "\t\r\n" or value.lstrip().startswith(("=", "+", "-", "@")))


def parse_csv(data, delimiter=","):
    if len(data) > MAX_BYTES:
        raise Refusal("LIMIT: input exceeds 20 MiB; nothing was sampled")
    try:
        text = data.decode("utf-8-sig", errors="strict")
    except UnicodeError:
        raise Refusal("ENCODING: only UTF-8 / UTF-8 BOM is supported") from None
    if "\x00" in text:
        raise Refusal("CSV: NUL bytes are refused")
    try:
        rows = list_bounded(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True))
    except csv.Error:
        raise Refusal("CSV: malformed quoting or oversized field; no partial plan") from None
    if not rows:
        raise Refusal("CSV: header is required")
    header, body = rows[0], rows[1:]
    if not header or len(header) > MAX_COLUMNS or any(not h.strip() or len(h) > 120 or any(ord(x) < 32 for x in h) or formula(h) for h in header):
        raise Refusal("HEADER: blank, oversized or unsafe column name")
    if len(set(header)) != len(header):
        raise Refusal("HEADER: duplicate column names; rename explicitly before planning")
    return header, body


def list_bounded(reader):
    rows, cells = [], 0
    for row in reader:
        cells += len(row)
        if cells > MAX_CELLS:
            raise Refusal("LIMIT: more than 1,000,000 cells; nothing was sampled")
        if len(rows) > MAX_ROWS:
            raise Refusal("LIMIT: more than 100,000 records; nothing was sampled")
        if len(row) > MAX_COLUMNS or any(len(v) > MAX_CELL for v in row):
            raise Refusal("LIMIT: maximum 128 fields and 65,536 characters per cell")
        rows.append(row)
    return rows


def convert(raw, col):
    value = raw.strip() if col["trim"] else raw
    codes = []
    if not value.strip():
        codes = ["REQUIRED"] if col["required"] else []
        if formula(value):
            codes.append("FORMULA")
        return value, codes
    kind = col["type"]
    numeric = False
    if kind in ("integer", "decimal"):
        sep = re.escape(col.get("decimal_separator", "."))
        pattern = r"[+-]?[0-9]+" if kind == "integer" else rf"[+-]?[0-9]+(?:{sep}[0-9]+)?"
        if len(value) > 64 or not re.fullmatch(pattern, value):
            codes.append("TYPE")
        else:
            number = Decimal(value.replace(col.get("decimal_separator", "."), "."))
            numeric = True
            if any(k in col and (number < Decimal(col[k]) if k == "min" else number > Decimal(col[k])) for k in ("min", "max")):
                codes.append("RANGE")
            # Decimal normalization only replaces an explicitly selected separator.
            # No binary float, rounding, exponent, grouping, currency or locale guessing.
            value = value.replace(col.get("decimal_separator", "."), ".")
    elif kind == "date":
        try:
            value = datetime.strptime(value, col["date_format"]).date().isoformat()
        except ValueError:
            codes.append("DATE_FORMAT")
    if formula(raw) and not numeric:
        codes.append("FORMULA")
    if "enum" in col and value not in col["enum"]:
        codes.append("ENUM")
    return value, codes


def read_table(data, suffix=".csv", delimiter=",", sheet=None):
    try:
        if suffix == ".csv":
            header, rows = parse_csv(data, delimiter)
            metadata = {"format": "csv", "cell_issues": []}
        elif suffix in (".json", ".jsonl", ".ndjson"):
            header, rows, metadata = formats.read_json(data, suffix != ".json")
        elif suffix == ".xlsx":
            header, rows, metadata = formats.read_xlsx(data, sheet)
        else:
            raise Refusal("FORMAT: supported inputs are CSV, XLSX, JSON and JSONL")
    except Refusal:
        raise
    except (formats.ParseError, RecursionError, OverflowError):
        import sys
        error = sys.exception()
        raise Refusal(str(error) if isinstance(error, formats.ParseError) else "FORMAT: malformed or excessive input") from None
    except (ValueError, TypeError, IndexError, KeyError):
        raise Refusal("FORMAT: malformed cell/workbook metadata") from None
    if not header or len(header) > MAX_COLUMNS or any(not isinstance(h, str) or not h.strip() or len(h) > 120 or any(ord(c) < 32 for c in h) or formula(h) for h in header):
        raise Refusal("HEADER: blank, oversized or unsafe column name")
    if len(set(header)) != len(header):
        raise Refusal("HEADER: duplicate column names")
    return header, rows, metadata


def analyze(data, contract, suffix=".csv"):
    header, rows, metadata = read_table(data, suffix, contract["delimiter"], contract.get("sheet"))
    return analyze_rows(header, rows, contract, metadata)


def analyze_rows(header, rows, contract, metadata=None):
    metadata = metadata or {"format": "csv", "cell_issues": []}
    expected = [c["name"] for c in contract["columns"]]
    if header != expected:
        raise Refusal("SCHEMA: columns/order differ from contract; make a new explicit contract")
    records, keys = [], Counter()
    indexes = [header.index(n) for n in contract["unique_key"]]
    forced = {}
    for event in metadata.get("cell_issues", []):
        forced.setdefault(event["row"], []).append({"row": event["row"], "column": header[event["index"]] if event["index"] < len(header) else "(record)", "code": event["code"]})
    for no, raw in enumerate(rows, 2):
        issues, transformed = list(forced.get(no, [])), []
        if len(raw) != len(header):
            issues.append({"row": no, "column": "(record)", "code": "ROW_WIDTH"})
        else:
            for val, col in zip(raw, contract["columns"]):
                value, codes = convert(val, col)
                transformed.append(value)
                issues.extend({"row": no, "column": col["name"], "code": c} for c in codes)
        key = tuple(transformed[i] for i in indexes) if indexes and transformed else None
        if key is not None:
            keys[key] += 1
        records.append([no, raw, transformed, issues, key])
    clean, quarantine, evidence, counts, changes = [], [], [], Counter(), Counter()
    totals = {c["name"]: Decimal(0) for c in contract["columns"] if c["type"] == "decimal"}
    for no, raw, transformed, issues, key in records:
        if key is not None and keys[key] > 1:
            issues.append({"row": no, "column": "+".join(contract["unique_key"]), "code": "DUPLICATE_KEY"})
        if issues:
            quarantine.append({"row": no, "cells": raw, "issues": issues})
            counts.update(i["code"] for i in issues)
            evidence.extend(issues[:max(0, MAX_EVIDENCE - len(evidence))])
        else:
            clean.append(transformed)
            for col, before, after in zip(contract["columns"], raw, transformed):
                if before != after:
                    changes[col["name"]] += 1
                if col["name"] in totals and after:
                    # Decimal addition uses the default 28-digit context; raise it to
                    # fit the 64-char numeric ceiling + up to 100k rows exactly.
                    from decimal import localcontext
                    with localcontext() as ctx:
                        ctx.prec = 144
                        totals[col["name"]] += Decimal(after)
    summary = {"engine_version": VERSION, "engine_sha256": ENGINE_SHA256, "input_rows": len(rows), "clean_rows": len(clean), "quarantined_rows": len(quarantine),
               "issue_counts": dict(sorted(counts.items())), "changed_clean_cells": dict(changes),
               "clean_decimal_totals": {k: format(v, "f") for k, v in totals.items()},
               "evidence": evidence, "evidence_truncated": sum(counts.values()) > len(evidence),
               "row_conservation": len(rows) == len(clean) + len(quarantine)}
    summary["input_format"] = metadata.get("format", "csv")
    if metadata.get("sheet"):
        summary["worksheet"] = metadata["sheet"]
    if metadata.get("blank_lines_skipped"):
        summary["blank_lines_skipped"] = metadata["blank_lines_skipped"]
    return header, clean, quarantine, summary


class Engine:
    def __init__(self, data_dir, allowed_roots=()):
        self.data_dir = Path(data_dir).absolute()
        self.allowed_roots = [Path(p).expanduser().resolve() for p in allowed_roots]

    @contextmanager
    def database(self):
        private_dir(self.data_dir)
        path = self.data_dir / "runs.sqlite3"
        if path.is_symlink():
            raise Refusal("SYMLINK: state database refused")
        fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        path.chmod(0o600)
        db = sqlite3.connect(path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("""CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY, created TEXT NOT NULL, source TEXT NOT NULL,
            source_sha TEXT NOT NULL, policy_sha TEXT NOT NULL, contract TEXT NOT NULL,
            header TEXT NOT NULL, summary TEXT NOT NULL, drift TEXT NOT NULL,
            state TEXT NOT NULL, receipt TEXT)""")
        db.execute("""CREATE TABLE IF NOT EXISTS drafts (
            id TEXT PRIMARY KEY, source TEXT NOT NULL, source_sha TEXT NOT NULL,
            state TEXT NOT NULL, payload TEXT NOT NULL)""")
        db.execute("CREATE TABLE IF NOT EXISTS run_inputs (run_id TEXT PRIMARY KEY REFERENCES runs(id), payload TEXT NOT NULL)")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def read_source(self, source):
        if not isinstance(source, str) or not Path(source).is_absolute() or ".." in Path(source).parts:
            raise Refusal("PATH: supply an absolute file path without traversal")
        p = Path(source)
        if not self.allowed_roots:
            raise Refusal("ROOTS: operator must configure allowed_roots first; no input access by default")
        for part in [p, *p.parents]:
            if part.is_symlink():
                raise Refusal("SYMLINK: input symlink components refused")
        p = p.resolve(strict=True)
        if not any(p.is_relative_to(root) for root in self.allowed_roots):
            raise Refusal("PATH: outside operator-configured allowed_roots")
        # Deliberately deny known credential stores even if a broad root was chosen.
        upload_root = self.data_dir / "uploads"
        # Explicitly enabled dashboard uploads live under .hermes/plugin-data, but
        # never grant access to ANY sibling configuration or credential stores.
        input_parts = p.relative_to(upload_root).parts if upload_root in self.allowed_roots and p.is_relative_to(upload_root) else p.parts
        if any(s.lower() in {".ssh", ".aws", ".gnupg", ".config", ".hermes", "auth.json", "credentials", "credentials.json"} or s.lower().startswith(".env") for s in input_parts):
            raise Refusal("PATH: credential/configuration stores are not CSV inputs")
        if p.suffix.lower() not in (".csv", ".xlsx", ".json", ".jsonl", ".ndjson"):
            raise Refusal("PATH: only .csv, .xlsx, .json, .jsonl and .ndjson inputs are supported")
        fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            meta = os.fstat(stream.fileno())
            if not stat.S_ISREG(meta.st_mode):
                raise Refusal("PATH: input must be a regular file")
            if meta.st_size > MAX_BYTES:
                raise Refusal("LIMIT: input exceeds 20 MiB")
            data = stream.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise Refusal("LIMIT: input exceeds 20 MiB")
        return str(p), data

    def inspect(self, source, delimiter=",", sheet=None):
        if delimiter not in (",", ";", "\t", "|"):
            raise Refusal("CSV: unsupported delimiter")
        path, data = self.read_source(source)
        header, rows, metadata = read_table(data, Path(path).suffix.lower(), delimiter, sheet)
        return {"source": path, "source_sha256": digest(data), "columns": header, "input_rows": len(rows),
                "input_format": metadata["format"], "worksheet": metadata.get("sheet"),
                "malformed_width_records": sum(len(r) != len(header) for r in rows),
                "note": "No cell samples returned. Auto-draft is separate and requires explicit human review."}

    def draft(self, source, delimiter=",", sheet=None, sample_rows=1000):
        if type(sample_rows) is not int or not 1 <= sample_rows <= 1000:
            raise Refusal("DRAFT: sample_rows must be 1–1000")
        if delimiter not in (",", ";", "\t", "|"):
            raise Refusal("CSV: unsupported delimiter")
        path, data = self.read_source(source)
        header, rows, metadata = read_table(data, Path(path).suffix.lower(), delimiter, sheet)
        candidate, notes, used = drafting.infer(header, rows, sample_rows, delimiter, metadata.get("sheet"))
        candidate = validate_contract(candidate)
        result = {"draft_id": uuid.uuid4().hex, "status": "DRAFT", "requires_human_review": True,
                  "source": path, "source_sha256": digest(data), "created": now(),
                  "suggested_contract": candidate, "notes": notes, "sample_rows": used,
                  "total_rows": len(rows), "warning": "DRAFT ONLY. Sample inference is not proof. Inspect identifiers, date ambiguity, required fields and category enums. Enums expose observed categories. Nothing is applied until explicit human review."}
        with self.database() as db:
            db.execute("INSERT INTO drafts VALUES (?,?,?,?,?)", (result["draft_id"], path, digest(data), "DRAFT", canonical(result)))
        return result

    def get_draft(self, draft_id):
        if not isinstance(draft_id, str) or not re.fullmatch(r"[a-f0-9]{32}", draft_id):
            raise Refusal("DRAFT: expected a draft ID")
        with self.database() as db:
            row = db.execute("SELECT payload FROM drafts WHERE id=?", (draft_id,)).fetchone()
        if not row:
            raise Refusal("DRAFT: unknown draft")
        return json.loads(row["payload"])

    def review_draft(self, draft_id, contract=None):
        """Only host-approved tool calls or explicit authenticated operator UI review."""
        draft = self.get_draft(draft_id)
        _, data = self.read_source(draft["source"])
        if digest(data) != draft["source_sha256"]:
            raise Refusal("STALE: source changed since drafting; create a new draft")
        reviewed = validate_contract(contract if contract is not None else draft["suggested_contract"])
        # Validate exact schema before recording the human's policy decision.
        analyze(data, reviewed, Path(draft["source"]).suffix.lower())
        if draft["status"] == "REVIEWED":
            if reviewed != draft["reviewed_contract"]:
                raise Refusal("DRAFT: reviewed drafts are immutable; create a new draft for policy edits")
            return draft
        draft.update(status="REVIEWED", requires_human_review=False, reviewed_contract=reviewed,
                     reviewed_at=now(), reviewed_policy_sha256=digest(canonical(reviewed).encode()))
        with self.database() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT state FROM drafts WHERE id=?", (draft_id,)).fetchone()
            if current["state"] != "DRAFT":
                raise Refusal("DRAFT: concurrent review; reload the immutable reviewed contract")
            db.execute("UPDATE drafts SET state='REVIEWED', payload=? WHERE id=?", (canonical(draft), draft_id))
        return draft

    def plan(self, source, contract=None, draft_id=None):
        path, data = self.read_source(source)
        extra = {}
        if draft_id:
            draft = self.get_draft(draft_id)
            if draft["status"] != "REVIEWED" or draft["source"] != path or draft["source_sha256"] != digest(data):
                raise Refusal("DRAFT_REVIEW: review the current source-bound draft first")
            if contract is None:
                contract = draft["reviewed_contract"]
            extra["draft_review"] = {"draft_id": draft_id, "reviewed_at": draft["reviewed_at"], "policy_sha256": draft["reviewed_policy_sha256"]}
        contract = validate_contract(contract)
        policy_sha = digest(canonical(contract).encode())
        header, _, _, summary = analyze(data, contract, Path(path).suffix.lower())
        with self.database() as db:
            drafts = db.execute("SELECT state,payload FROM drafts WHERE source=? AND source_sha=?", (path, digest(data))).fetchall()
        # Even extracting or modifying suggested_contract cannot silently activate a draft.
        if drafts and not any(d["state"] == "REVIEWED" and json.loads(d["payload"])["reviewed_policy_sha256"] == policy_sha for d in drafts):
            raise Refusal("DRAFT_REVIEW: this source has draft proposals; explicitly review this exact contract before planning")
        if draft_id and extra["draft_review"]["policy_sha256"] != policy_sha:
            raise Refusal("DRAFT_REVIEW: policy differs from the immutable reviewed draft")
        summary.update(extra)
        return self._persist(path, data, contract, header, summary, extra)

    def _persist(self, path, data, contract, header, summary, extra):
        policy_sha, source_sha = digest(canonical(contract).encode()), digest(data)
        run = {"id": uuid.uuid4().hex, "created": now(), "source": path, "source_sha256": source_sha,
               "policy_sha256": policy_sha, "contract": contract, "summary": summary, "state": "PLANNED", "receipt": None}
        with self.database() as db:
            db.execute("BEGIN IMMEDIATE")
            prev = db.execute("SELECT * FROM runs WHERE source=? ORDER BY rowid DESC LIMIT 1", (path,)).fetchone()
            drift = {"previous_plan_id": prev["id"] if prev else None, "added_columns": [], "removed_columns": [], "order_changed": False,
                     "contract_changed": bool(prev and prev["policy_sha"] != policy_sha), "issue_delta": {}, "input_rows_delta": None}
            if prev:
                old_header, old = json.loads(prev["header"]), json.loads(prev["summary"])
                drift.update(added_columns=[x for x in header if x not in old_header], removed_columns=[x for x in old_header if x not in header],
                             order_changed=header != old_header, input_rows_delta=summary["input_rows"] - old["input_rows"],
                             issue_delta={k: summary["issue_counts"].get(k, 0) - old["issue_counts"].get(k, 0) for k in sorted(set(summary["issue_counts"]) | set(old["issue_counts"]))})
            run["drift"] = drift
            db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?)", (run["id"], run["created"], path, source_sha, policy_sha,
                canonical(contract), canonical(header), canonical(summary), canonical(drift), "PLANNED", None))
            db.execute("INSERT INTO run_inputs VALUES (?,?)", (run["id"], canonical(extra)))
        return run

    def _extra(self, plan_id):
        with self.database() as db:
            row = db.execute("SELECT payload FROM run_inputs WHERE run_id=?", (plan_id,)).fetchone()
        return json.loads(row["payload"]) if row else {}

    def _stale(self, run, message):
        with self.database() as db:
            db.execute("UPDATE runs SET state='STALE' WHERE id=? AND state='PLANNED'", (run["id"],))
        raise Refusal(message)

    def _source_snapshot(self, run):
        if run["state"] == "STALE":
            raise Refusal("STALE: permanently stale plan; create a new plan")
        if run["summary"].get("engine_sha256") != ENGINE_SHA256:
            self._stale(run, "ENGINE_CHANGED: engine source differs; create a new plan")
        if digest(canonical(run["contract"]).encode()) != run["policy_sha256"]:
            raise Refusal("PLAN: stored policy hash mismatch")
        _, data = self.read_source(run["source"])
        if digest(data) != run["source_sha256"]:
            self._stale(run, "STALE: source bytes changed after review; create a new plan")
        return data

    def _table_for(self, run, data, depth=0):
        if depth > 10:
            raise Refusal("REPLAY: maximum replay depth is 10; start a new explicit source plan")
        extra = self._extra(run["id"])
        replay = extra.get("replay")
        if not replay:
            return read_table(data, Path(run["source"]).suffix.lower(), run["contract"]["delimiter"], run["contract"].get("sheet"))
        parent = self.get(replay["parent_plan_id"])
        if parent["source_sha256"] != run["source_sha256"] or parent["policy_sha256"] != run["policy_sha256"] or parent["source"] != run["source"]:
            raise Refusal("REPLAY: parent source/policy binding mismatch")
        if parent["state"] == "STALE" or parent["summary"].get("engine_sha256") != ENGINE_SHA256:
            self._stale(run, "STALE: replay ancestor is stale or engine changed")
        if replay.get("patch_file"):
            _, patch_bytes = self.read_source(replay["patch_file"])
            if digest(patch_bytes) != replay["patch_file_sha256"]:
                self._stale(run, "STALE: patch file changed after replay planning")
        patch = extra["patch"]
        if digest(canonical(patch).encode()) != replay["patch_sha256"]:
            raise Refusal("REPLAY: patch hash mismatch")
        header, rows, metadata = self._table_for(parent, data, depth + 1)
        return self._apply_patch(header, rows, metadata, patch)

    @staticmethod
    def _normalize_patch(patch, header, quarantine):
        if not isinstance(patch, list) or not 1 <= len(patch) <= 1000:
            raise Refusal("PATCH: provide 1–1000 row corrections")
        permitted, seen, result = {r["row"] for r in quarantine}, set(), []
        for change in patch:
            if not isinstance(change, dict) or set(change) not in ({"row", "set"}, {"row", "cells"}):
                raise Refusal("PATCH: each entry needs row and either set or cells")
            row = change["row"]
            if type(row) is not int or row not in permitted or row in seen:
                raise Refusal("PATCH: only distinct quarantined record numbers may be corrected")
            seen.add(row)
            if "cells" in change:
                cells = change["cells"]
                if not isinstance(cells, list) or len(cells) != len(header):
                    raise Refusal("PATCH: replacement cells must match the exact header width")
                updates = dict(zip(header, cells))
            else:
                updates = change["set"]
                if not isinstance(updates, dict) or not updates or set(updates) - set(header):
                    raise Refusal("PATCH: set must name existing columns only")
            if not all(isinstance(v, str) and len(v) <= MAX_CELL and "\x00" not in v for v in updates.values()):
                raise Refusal("PATCH: corrected values must be bounded strings without NUL")
            result.append({"row": row, "set": updates})
        if len(canonical(result).encode()) > MAX_BYTES:
            raise Refusal("LIMIT: patch exceeds 20 MiB")
        return sorted(result, key=lambda r: r["row"])

    @staticmethod
    def _apply_patch(header, rows, metadata, patch):
        rows = [list(row) for row in rows]
        removed = set()
        for change in patch:
            index = change["row"] - 2
            if not 0 <= index < len(rows):
                raise Refusal("PATCH: record is outside the source")
            raw = rows[index]
            if len(raw) != len(header) and len(change["set"]) != len(header):
                raise Refusal("PATCH: malformed-width records need a complete cells replacement")
            if len(raw) != len(header):
                raw = [""] * len(header)
                rows[index] = raw
            for name, value in change["set"].items():
                col = header.index(name)
                raw[col] = value
                removed.add((change["row"], col))
        if sum(len(value) for row in rows for value in row) > MAX_BYTES:
            raise Refusal("LIMIT: corrected cell text exceeds 20 MiB")
        metadata = {**metadata, "cell_issues": [e for e in metadata.get("cell_issues", []) if (e["row"], e["index"]) not in removed]}
        return header, rows, metadata

    def _evaluate(self, run, data=None):
        data = self._source_snapshot(run) if data is None else data
        header, rows, metadata = self._table_for(run, data)
        header, clean, quarantine, summary = analyze_rows(header, rows, run["contract"], metadata)
        extra = self._extra(run["id"])
        summary.update({k: v for k, v in extra.items() if k != "patch"})
        if summary != run["summary"]:
            raise Refusal("PLAN: engine/policy output differs; create a new plan")
        return header, rows, metadata, clean, quarantine, summary

    def replay(self, plan_id, patch=None, patch_file=None, preview=False):
        run = self.check(plan_id)
        data = self._source_snapshot(run)  # even EXPORTED parents must match current source bytes
        header, rows, metadata, _, quarantine, _ = self._evaluate(run, data)
        if (patch is None) == (patch_file is None):
            raise Refusal("PATCH: supply exactly one of patch or patch_file")
        patch_path, patch_hash = None, None
        if patch_file is not None:
            patch_path, patch_bytes = self.read_source(patch_file)
            if Path(patch_path).suffix.lower() != ".json":
                raise Refusal("PATCH: patch_file must be .json")
            try:
                patch = json.loads(formats.text(patch_bytes), object_pairs_hook=formats.pairs, parse_constant=formats.constant)
            except (ValueError, RecursionError):
                raise Refusal("PATCH: invalid JSON patch file") from None
            patch_hash = digest(patch_bytes)
        normalized = self._normalize_patch(patch, header, quarantine)
        header, corrected, metadata = self._apply_patch(header, rows, metadata, normalized)
        _, _, _, summary = analyze_rows(header, corrected, run["contract"], metadata)
        replay = {"parent_plan_id": run["id"], "patch_sha256": digest(canonical(normalized).encode()),
                  "patch_file": patch_path, "patch_file_sha256": patch_hash,
                  "corrected_records": [p["row"] for p in normalized]}
        extra = {"replay": replay, "patch": normalized}
        summary["replay"] = replay
        if preview:
            return {"summary": summary, "patch": normalized, "requires_export_approval": True, "persisted": False}
        child = self._persist(run["source"], data, run["contract"], header, summary, extra)
        try:
            self._evaluate(child)  # catches concurrent source/patch changes before returning a reviewable plan
        except Refusal:
            self._stale(child, "STALE: input changed while replay planning; create a new replay plan")
        return child

    def quarantine(self, plan_id, offset=0, limit=50, query="", code=""):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100 or not isinstance(query, str) or len(query) > 200 or not isinstance(code, str) or len(code) > 40:
            raise Refusal("QUERY: invalid quarantine pagination/filter")
        run = self.check(plan_id)
        if run["state"] == "EXPORTED":
            records = json.loads((self.data_dir / "exports" / plan_id / "quarantine.json").read_text())["records"]
        else:
            records = self._evaluate(run)[4]
        if query:
            records = [r for r in records if query.casefold() in canonical(r).casefold()]
        if code:
            records = [r for r in records if any(e["code"] == code for e in r["issues"])]
        return {"records": records[offset:offset + limit], "total": len(records), "offset": offset,
                "limit": limit, "columns": [c["name"] for c in run["contract"]["columns"]]}

    def report(self, plan_id):
        run = self.check(plan_id)
        if run["receipt"]:
            return (self.data_dir / "exports" / plan_id / "audit.html").read_text()
        return audit.render_report(run)

    def get(self, plan_id):
        if not isinstance(plan_id, str) or not re.fullmatch(r"[a-f0-9]{32}", plan_id):
            raise Refusal("PLAN: expected a 32-character plan ID")
        with self.database() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (plan_id,)).fetchone()
        if not row:
            raise Refusal("PLAN: unknown plan ID")
        return self.decode(row)

    @staticmethod
    def decode(row):
        return {"id": row["id"], "created": row["created"], "source": row["source"], "source_sha256": row["source_sha"],
                "policy_sha256": row["policy_sha"], "contract": json.loads(row["contract"]), "summary": json.loads(row["summary"]),
                "drift": json.loads(row["drift"]), "state": row["state"], "receipt": json.loads(row["receipt"]) if row["receipt"] else None}

    def history(self, limit=30):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise Refusal("LIMIT: history limit must be 1–100")
        with self.database() as db:
            rows = db.execute("SELECT * FROM runs ORDER BY rowid DESC LIMIT ?", (limit,)).fetchall()
        return [self.decode(r) for r in rows]

    def check(self, plan_id):
        run = self.get(plan_id)
        if run["state"] == "EXPORTED":
            self.verify_receipt(run["receipt"], run)
            return run
        self._evaluate(run)
        return run

    def verify_receipt(self, receipt, run):
        if receipt.get("plan_id") != run["id"] or receipt.get("source_sha256") != run["source_sha256"] or receipt.get("policy_sha256") != run["policy_sha256"]:
            raise Refusal("RECEIPT: provenance mismatch")
        folder = self.data_dir / "exports" / run["id"]
        if any(p.is_symlink() for p in [folder, *folder.parents]):
            raise Refusal("SYMLINK: export folder refused")
        if not isinstance(receipt.get("artifacts"), dict) or set(receipt["artifacts"]) not in ({"clean.csv", "quarantine.json"}, {"clean.csv", "quarantine.json", "audit.html"}):
            raise Refusal("RECEIPT: unexpected artifact manifest")
        if "receipt_core_sha256" in receipt:
            base = {k: v for k, v in receipt.items() if k != "receipt_core_sha256"}
            base["artifacts"] = {k: v for k, v in base["artifacts"].items() if k != "audit.html"}
            if digest(canonical(base).encode()) != receipt["receipt_core_sha256"]:
                raise Refusal("RECEIPT: receipt core hash mismatch")
        for name in receipt["artifacts"]:
            path = folder / name
            if path.is_symlink() or digest(path.read_bytes()) != receipt["artifacts"][name]["sha256"]:
                raise Refusal("RECEIPT: exported artifact has changed; refusing silent overwrite")
        disk = folder / "receipt.json"
        if disk.is_symlink() or json.loads(disk.read_text()) != receipt:
            raise Refusal("RECEIPT: receipt has changed")
        return receipt

    def export(self, plan_id):
        """Called only after the host tool approval gate, or an explicit human CLI command.

        This library itself is not a sandbox and does not fabricate an approval token.
        """
        run = self.check(plan_id)
        if run["state"] == "EXPORTED":
            return run["receipt"]
        # Re-read and hash the exact byte snapshot subsequently transformed (no read-after-check race).
        _, data = self.read_source(run["source"])
        if digest(data) != run["source_sha256"]:
            self.check(plan_id)
            raise Refusal("STALE: source changed during export")
        header, _, _, clean, quarantine, summary = self._evaluate(run, data)
        if summary != run["summary"] or digest(canonical(run["contract"]).encode()) != run["policy_sha256"]:
            raise Refusal("PLAN: engine/policy output differs; replan")
        exports = private_dir(self.data_dir / "exports")
        final = exports / plan_id
        with self.database() as db:
            db.execute("BEGIN IMMEDIATE")
            state = db.execute("SELECT state, receipt FROM runs WHERE id=?", (plan_id,)).fetchone()
            if state["state"] == "STALE":
                raise Refusal("STALE: export refused")
            if state["state"] == "EXPORTED":
                return self.verify_receipt(json.loads(state["receipt"]), run)
            if final.is_symlink():
                raise Refusal("SYMLINK: export folder refused")
            if final.exists():
                # Recovery after atomic publication but before SQLite COMMIT. Never overwrite.
                receipt = self.verify_receipt(json.loads((final / "receipt.json").read_text()), run)
            else:
                staging = Path(tempfile.mkdtemp(prefix=".stage-", dir=exports))
                try:
                    stream = io.StringIO(newline="")
                    writer = csv.writer(stream, lineterminator="\n")
                    writer.writerow(header)
                    writer.writerows(clean)
                    payloads = {"clean.csv": stream.getvalue().encode("utf-8"),
                                "quarantine.json": (canonical({"warning": "Raw sensitive cells; JSON only; do not paste into spreadsheets", "records": quarantine}) + "\n").encode("utf-8")}
                    receipt = {"engine": "rowverdict", "engine_version": VERSION, "plan_id": plan_id, "exported_at": now(),
                               "source_sha256": run["source_sha256"], "policy_sha256": run["policy_sha256"],
                               "summary": summary, "contract": run["contract"], "output_dir": str(final),
                               "artifacts": {name: {"sha256": digest(body), "bytes": len(body)} for name, body in payloads.items()},
                               "row_numbering": "1-based logical table records; header=1; JSON/JSONL objects start at 2; Excel row coordinates are preserved; embedded CSV newlines stay within one record",
                               "approval_boundary": "Host approval is enforced by the Hermes export-tool hook, not by this library"}
                    receipt["receipt_core_sha256"] = digest(canonical(receipt).encode())
                    payloads["audit.html"] = audit.render_report(run, receipt).encode("utf-8")
                    receipt["artifacts"]["audit.html"] = {"sha256": digest(payloads["audit.html"]), "bytes": len(payloads["audit.html"])}
                    payloads["receipt.json"] = (canonical(receipt) + "\n").encode("utf-8")
                    for name, body in payloads.items():
                        fd = os.open(staging / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                        with os.fdopen(fd, "wb") as file:
                            file.write(body)
                            file.flush()
                            os.fsync(file.fileno())
                    os.rename(staging, final)
                    # Directory fsync makes atomic publication durable on local Linux filesystems.
                    fd = os.open(exports, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                finally:
                    if staging.exists():
                        shutil.rmtree(staging)
            db.execute("UPDATE runs SET state='EXPORTED', receipt=? WHERE id=?", (canonical(receipt), plan_id))
        return receipt
