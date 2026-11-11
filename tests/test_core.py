import csv
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import Engine, Refusal, analyze, canonical, digest, parse_csv, validate_contract

ROOT = Path(__file__).resolve().parents[1]


def policy(*columns, key=None):
    return {"columns": [{"name": n, "type": t, **extra} for n, t, extra in columns], "unique_key": key or []}


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()
        self.file = self.inputs / "data.csv"
        self.app = Engine(self.root / "state", [str(self.inputs)])
        self.c = policy(("id", "string", {}), ("amount", "decimal", {"min": "0"}), key=["id"])
        self.file.write_text("id,amount\n00042,1.01\n00043,2.02\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self, content=None, contract=None):
        if content is not None:
            self.file.write_text(content, encoding="utf-8")
        return self.app.plan(str(self.file), contract or self.c)

    def test_exact_decimal_and_leading_zeros(self):
        run = self.plan()
        self.assertEqual(run["summary"]["clean_decimal_totals"], {"amount": "3.03"})
        receipt = self.app.export(run["id"])
        self.assertEqual((Path(receipt["output_dir"]) / "clean.csv").read_text(), self.file.read_text())

    def test_source_never_modified(self):
        before = self.file.read_bytes()
        self.app.export(self.plan()["id"])
        self.assertEqual(self.file.read_bytes(), before)

    def test_every_duplicate_quarantined(self):
        s = self.plan("id,amount\n00042,1\n00042,2\n00042,3\n")["summary"]
        self.assertEqual(s["quarantined_rows"], 3)
        self.assertEqual(s["issue_counts"], {"DUPLICATE_KEY": 3})

    def test_duplicate_after_declared_trim(self):
        c = policy(("id", "string", {"trim": True}), ("amount", "decimal", {}), key=["id"])
        self.assertEqual(self.plan("id,amount\n A,1\nA ,2\n", c)["summary"]["quarantined_rows"], 2)

    def test_composite_unique_key(self):
        c = dict(self.c, unique_key=["id", "amount"])
        self.assertEqual(self.plan("id,amount\nA,1\nA,2\n", c)["summary"]["clean_rows"], 2)

    def test_duplicates_include_invalid_rows(self):
        s = self.plan("id,amount\nA,bad\nA,2\n")["summary"]
        self.assertEqual(s["issue_counts"], {"DUPLICATE_KEY": 2, "TYPE": 1})

    def test_stale_persisted_and_no_outputs(self):
        run = self.plan()
        self.file.write_text(self.file.read_text() + "00044,4\n")
        with self.assertRaisesRegex(Refusal, "STALE"):
            self.app.export(run["id"])
        self.assertEqual(self.app.get(run["id"])["state"], "STALE")
        self.assertFalse((self.app.data_dir / "exports").exists())

    def test_stale_remains_stale_when_source_restored(self):
        original = self.file.read_bytes()
        run = self.plan()
        self.file.write_text("id,amount\nA,1\n")
        with self.assertRaises(Refusal):
            self.app.check(run["id"])
        self.file.write_bytes(original)
        with self.assertRaises(Refusal):
            self.app.export(run["id"])

    def test_same_hash_different_mtime_is_not_stale(self):
        run = self.plan()
        os.utime(self.file, (1, 1))
        self.assertEqual(self.app.export(run["id"])["plan_id"], run["id"])

    def test_idempotent_export(self):
        run = self.plan()
        first = self.app.export(run["id"])
        self.assertEqual(first, self.app.export(run["id"]))
        self.assertEqual(len(list((self.app.data_dir / "exports").iterdir())), 1)

    def test_corrupt_export_never_silently_overwrites(self):
        run = self.plan()
        first = self.app.export(run["id"])
        (Path(first["output_dir"]) / "clean.csv").write_text("corrupted")
        with self.assertRaisesRegex(Refusal, "RECEIPT"):
            self.app.export(run["id"])

    def test_corrupt_receipt_detected(self):
        run = self.plan()
        first = self.app.export(run["id"])
        (Path(first["output_dir"]) / "receipt.json").write_text("{}")
        with self.assertRaisesRegex(Refusal, "RECEIPT"):
            self.app.export(run["id"])

    def test_recovery_after_publication_before_commit(self):
        run = self.plan()
        first = self.app.export(run["id"])
        with self.app.database() as db:
            db.execute("UPDATE runs SET state='PLANNED', receipt=NULL WHERE id=?", (run["id"],))
        self.assertEqual(first, self.app.export(run["id"]))
        self.assertEqual(self.app.get(run["id"])["state"], "EXPORTED")

    def test_concurrent_export_single_artifact(self):
        run = self.plan()
        with ThreadPoolExecutor(max_workers=4) as ex:
            receipts = list(ex.map(lambda _: self.app.export(run["id"]), range(4)))
        self.assertTrue(all(r == receipts[0] for r in receipts))
        self.assertEqual(len(list((self.app.data_dir / "exports").iterdir())), 1)

    def test_restart_recovers_history(self):
        run = self.plan()
        app = Engine(self.app.data_dir, [str(self.inputs)])
        self.assertEqual(app.get(run["id"])["summary"], run["summary"])
        self.assertEqual(app.history()[0]["id"], run["id"])

    def test_no_raw_cell_contents_in_plans_or_db(self):
        run = self.plan("id,amount\nPRIVATE_SENTINEL,not_numeric_secret\n")
        self.assertNotIn("PRIVATE_SENTINEL", canonical(run))
        self.assertNotIn("not_numeric_secret", canonical(run))
        self.assertNotIn(b"PRIVATE_SENTINEL", (self.app.data_dir / "runs.sqlite3").read_bytes())

    def test_private_permissions(self):
        receipt = self.app.export(self.plan()["id"])
        self.assertEqual(self.app.data_dir.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.app.data_dir / "runs.sqlite3").stat().st_mode & 0o777, 0o600)
        for p in Path(receipt["output_dir"]).iterdir():
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)

    def test_default_deny_inputs(self):
        with self.assertRaisesRegex(Refusal, "ROOTS"):
            Engine(self.root / "other").inspect(str(self.file))

    def test_outside_root(self):
        other = self.root / "outside.csv"
        other.write_text("id\n1\n")
        with self.assertRaisesRegex(Refusal, "outside"):
            self.app.inspect(str(other))

    def test_relative_and_traversal_paths(self):
        for path in ("data.csv", str(self.inputs / ".." / "inputs" / "data.csv")):
            with self.subTest(path=path), self.assertRaisesRegex(Refusal, "PATH"):
                self.app.inspect(path)

    def test_symlink_and_parent_symlink(self):
        link = self.inputs / "link.csv"
        link.symlink_to(self.file)
        alias = self.root / "alias"
        alias.symlink_to(self.inputs, target_is_directory=True)
        for p in (link, alias / "data.csv"):
            with self.subTest(p=p), self.assertRaisesRegex(Refusal, "SYMLINK"):
                self.app.inspect(str(p))

    def test_credential_stores_denied(self):
        for name in (".ssh", ".env-directory", ".config", "credentials", ".hermes"):
            folder = self.inputs / name
            folder.mkdir()
            target = folder / "secret.csv"
            target.write_text("id\n1\n")
            with self.subTest(name=name), self.assertRaisesRegex(Refusal, "credential"):
                self.app.inspect(str(target))

    def test_fifo_refused_without_blocking(self):
        target = self.inputs / "fifo.csv"
        os.mkfifo(target)
        with self.assertRaisesRegex(Refusal, "regular"):
            self.app.inspect(str(target))

    def test_non_csv_refused(self):
        target = self.inputs / "data.json"
        target.write_text("{}")
        with self.assertRaisesRegex(Refusal, "only .csv"):
            self.app.inspect(str(target))

    def test_state_symlink_refused(self):
        self.app.data_dir.symlink_to(self.inputs, target_is_directory=True)
        with self.assertRaisesRegex(Refusal, "SYMLINK"):
            self.plan()

    def test_database_symlink_refused(self):
        self.app.data_dir.mkdir()
        (self.app.data_dir / "runs.sqlite3").symlink_to(self.file)
        with self.assertRaisesRegex(Refusal, "SYMLINK"):
            self.plan()

    def test_header_only_valid_zero_conservation(self):
        s = self.plan("id,amount\n")["summary"]
        self.assertEqual(s["input_rows"], 0)
        self.assertTrue(s["row_conservation"])

    def test_bad_headers(self):
        for content in ("id,id\nA,B\n", ",amount\nA,2\n", "=unsafe,amount\nA,2\n", "\n"):
            with self.subTest(content=content), self.assertRaises(Refusal):
                self.plan(content)

    def test_missing_extra_or_reordered_header_refused(self):
        for content in ("amount,id\n1,A\n", "id\nA\n", "id,amount,other\nA,1,X\n"):
            with self.subTest(content=content), self.assertRaisesRegex(Refusal, "SCHEMA"):
                self.plan(content)

    def test_blank_records_and_malformed_widths_quarantine(self):
        s = self.plan("id,amount\nA,1\n\nB\nC,3,extra\n")["summary"]
        self.assertEqual((s["input_rows"], s["clean_rows"], s["quarantined_rows"]), (4, 1, 3))
        self.assertEqual(s["issue_counts"], {"ROW_WIDTH": 3})

    def test_embedded_newlines_and_quoted_commas(self):
        s = self.plan('id,amount\n"A,comma",1\n"B\nnewline",2\n')["summary"]
        self.assertEqual(s["clean_rows"], 2)

    def test_utf8_bom_and_unicode(self):
        self.file.write_bytes('\ufeffid,amount\n東京,2.01\nSão Paulo,1.02\n'.encode())
        s = self.plan()["summary"]
        self.assertEqual(s["clean_decimal_totals"]["amount"], "3.03")

    def test_invalid_encoding_nul_and_unterminated_quote(self):
        for data in (b"id,amount\n\xff,1\n", b"id,amount\n\0,1\n", b'id,amount\n"unterminated,1\n'):
            self.file.write_bytes(data)
            with self.subTest(data=data), self.assertRaises(Refusal):
                self.plan()

    def test_non_utf8_fails_before_persistence(self):
        self.file.write_bytes(b"id,amount\n\xff,1\n")
        with self.assertRaises(Refusal):
            self.plan()
        self.assertFalse(self.app.data_dir.exists())

    def test_delimiters(self):
        for delim in (";", "\t", "|"):
            with self.subTest(delim=delim):
                s = self.plan(f"id{delim}amount\nA{delim}1.01\n", dict(self.c, delimiter=delim))["summary"]
                self.assertEqual(s["clean_rows"], 1)

    def test_formula_cells_quarantined_and_only_json_raw(self):
        content = "id,amount\n=HYPERLINK(),1\n @SUM(A1),2\n+1,3\n-1,4\n"
        run = self.plan(content)
        receipt = self.app.export(run["id"])
        self.assertEqual(run["summary"]["quarantined_rows"], 4)
        self.assertEqual((Path(receipt["output_dir"]) / "clean.csv").read_text(), "id,amount\n")
        raw = json.loads((Path(receipt["output_dir"]) / "quarantine.json").read_text())
        self.assertEqual(len(raw["records"]), 4)
        self.assertEqual(raw["records"][0]["cells"][0], "=HYPERLINK()")

    def test_negative_numeric_not_formula_but_range_rejected(self):
        s = self.plan("id,amount\nA,-10\n")["summary"]
        self.assertEqual(s["issue_counts"], {"RANGE": 1})

    def test_typed_negative_without_range_allowed(self):
        c = policy(("id", "string", {}), ("amount", "decimal", {}))
        self.assertEqual(self.plan("id,amount\nA,-10\n", c)["summary"]["clean_rows"], 1)

    def test_decimal_grouping_nan_infinity_exponent_refused(self):
        for val in ('"1,234.50"', "NaN", "Infinity", "1e3", "1.2.3", "1 000", "USD12"):
            with self.subTest(val=val):
                s = self.plan("id,amount\nA," + val + "\n")["summary"]
                self.assertEqual(s["issue_counts"], {"TYPE": 1})

    def test_comma_decimal_explicit_normalization(self):
        c = policy(("id", "string", {}), ("amount", "decimal", {"decimal_separator": ","}))
        run = self.plan('id,amount\nA,"12,34"\n', c)
        self.assertEqual(run["summary"]["changed_clean_cells"], {"amount": 1})
        self.assertEqual(run["summary"]["clean_decimal_totals"], {"amount": "12.34"})

    def test_precision_above_default_decimal_context(self):
        c = policy(("id", "string", {}), ("amount", "decimal", {}))
        s = self.plan("id,amount\nA,123456789012345678901234567890.01\nB,0.02\n", c)["summary"]
        self.assertEqual(s["clean_decimal_totals"]["amount"], "123456789012345678901234567890.03")

    def test_explicit_date_formats(self):
        for fmt, value, expected in (("%d/%m/%Y", "02/03/2026", "2026-03-02"), ("%m/%d/%Y", "02/03/2026", "2026-02-03"), ("%Y-%m-%d", "2026-03-02", "2026-03-02")):
            c = policy(("id", "string", {}), ("date", "date", {"date_format": fmt}))
            run = self.plan(f"id,date\nA,{value}\n", c)
            path = Path(self.app.export(run["id"])["output_dir"]) / "clean.csv"
            self.assertIn(expected, path.read_text())

    def test_bad_date_never_guessed(self):
        c = policy(("id", "string", {}), ("date", "date", {"date_format": "%d/%m/%Y"}))
        for value in ("10/31/2026", "29/02/2026", "2026-11-10"):
            with self.subTest(value=value):
                self.assertEqual(self.plan(f"id,date\nA,{value}\n", c)["summary"]["issue_counts"], {"DATE_FORMAT": 1})

    def test_optional_empty_required_and_enum(self):
        c = policy(("id", "string", {}), ("state", "string", {"required": False, "enum": ["paid"]}))
        s = self.plan("id,state\nA,\nB,other\n,paid\n", c)["summary"]
        self.assertEqual(s["issue_counts"], {"ENUM": 1, "REQUIRED": 1})
        self.assertEqual(s["clean_rows"], 1)

    def test_integer_rejects_fraction(self):
        c = policy(("id", "string", {}), ("qty", "integer", {"min": "0", "max": "100"}))
        s = self.plan("id,qty\nA,12.5\nB,101\nC,012\n", c)["summary"]
        self.assertEqual(s["issue_counts"], {"RANGE": 1, "TYPE": 1})
        self.assertEqual(s["clean_rows"], 1)

    def test_drift_and_explicit_new_contract(self):
        first = self.plan()
        c = policy(("id", "string", {}), ("amount", "decimal", {"min": "0"}), ("channel", "string", {}), key=["id"])
        run = self.plan("id,amount,channel\nA,bad,online\n", c)
        self.assertEqual(run["drift"]["previous_plan_id"], first["id"])
        self.assertEqual(run["drift"]["added_columns"], ["channel"])
        self.assertTrue(run["drift"]["contract_changed"])
        self.assertEqual(run["drift"]["issue_delta"], {"TYPE": 1})
        self.assertEqual(run["drift"]["input_rows_delta"], -1)

    def test_schema_mismatch_inspect_still_shows_new_columns(self):
        self.file.write_text("id,amount,new\nA,1,yes\n")
        self.assertEqual(self.app.inspect(str(self.file))["columns"], ["id", "amount", "new"])
        with self.assertRaises(Refusal):
            self.plan()

    def test_bounded_evidence_full_scan(self):
        run = self.plan("id,amount\n" + "A,bad\n" * 1000)
        s = run["summary"]
        self.assertEqual(s["input_rows"], 1000)
        self.assertEqual(s["issue_counts"], {"DUPLICATE_KEY": 1000, "TYPE": 1000})
        self.assertEqual(len(s["evidence"]), 250)
        self.assertTrue(s["evidence_truncated"])

    def test_row_limit_refuses_not_sample_pass(self):
        self.file.write_text("id,amount\n" + "A,1\n" * 100001)
        with self.assertRaisesRegex(Refusal, "LIMIT"):
            self.plan()
        self.assertFalse(self.app.data_dir.exists())

    def test_byte_limit_refuses_before_read(self):
        with self.file.open("wb") as f:
            f.truncate(20 * 1024 * 1024 + 1)
        with self.assertRaisesRegex(Refusal, "LIMIT"):
            self.plan()

    def test_field_column_limits(self):
        for text in ("id,amount\n" + "A" * 65537 + ",1\n", ",".join("col" + str(i) for i in range(129)) + "\n"):
            self.file.write_text(text)
            with self.assertRaisesRegex(Refusal, "LIMIT"):
                self.app.inspect(str(self.file))

    def test_unknown_and_malformed_plan_ids(self):
        for value in ("a" * 32, "../file", None, 123, "a" * 1000):
            with self.subTest(value=value), self.assertRaises(Refusal):
                self.app.get(value)

    def test_history_limit(self):
        for value in (0, 101, "10", True):
            with self.subTest(value=value), self.assertRaises(Refusal):
                self.app.history(value)

    def test_contract_validation(self):
        bad = [{}, {"columns": []}, {"columns": [{"name": "id", "type": "sql"}]},
               {"columns": [{"name": "id", "trim": "true"}]}, {"columns": [{"name": "id", "type": "date"}]},
               {"columns": [{"name": "id", "max": "1"}]}, {"columns": [{"name": "id", "type": "decimal", "min": "NaN"}]},
               {"columns": [{"name": "id", "type": "decimal", "min": "2", "max": "1"}]},
               {"columns": [{"name": "id", "enum": "all"}]}, {"columns": [{"name": "id"}], "unique_key": ["missing"]},
               {"columns": [{"name": "id"}, {"name": "id"}]}, {"columns": [{"name": "id", "date_format": "%d/%m/%Y"}]},
               {"columns": [{"name": "id", "unknown": True}]}, {"columns": [{"name": "id"}], "delimiter": "xx"},
               {"columns": [{"name": "id"}], "code": "arbitrary"}]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(Refusal):
                validate_contract(value)

    def test_total_cell_budget_refuses_before_issue_explosion(self):
        text = ",".join("c" + str(i) for i in range(11)) + "\n" + ("," * 10 + "\n") * 100000
        self.file.write_text(text)
        with self.assertRaisesRegex(Refusal, "1,000,000 cells"):
            self.app.inspect(str(self.file))

    def test_contract_total_size_bound(self):
        c = policy(("id", "string", {"enum": ["x" * 1000 + str(i) for i in range(100)]}))
        # Keep each enum within its own 1000-char cap; total normalized size is independently capped.
        c["columns"][0]["enum"] = [str(i).zfill(4) + "x" * 996 for i in range(100)]
        with self.assertRaisesRegex(Refusal, "64 KiB"):
            validate_contract(c)

    def test_engine_source_change_requires_replan(self):
        from unittest.mock import patch
        run = self.plan()
        with patch("core.ENGINE_SHA256", "0" * 64):
            with self.assertRaisesRegex(Refusal, "ENGINE_CHANGED"):
                self.app.export(run["id"])
        self.assertFalse((self.app.data_dir / "exports").exists())

    def test_atomic_publication_failure_cleans_staging(self):
        from unittest.mock import patch
        run = self.plan()
        with patch("core.os.rename", side_effect=OSError("synthetic publication failure")):
            with self.assertRaises(OSError):
                self.app.export(run["id"])
        self.assertEqual(list((self.app.data_dir / "exports").iterdir()), [])
        self.assertEqual(self.app.get(run["id"])["state"], "PLANNED")
        self.assertEqual(self.app.export(run["id"])["plan_id"], run["id"])

    def test_symlinked_published_export_refused(self):
        run = self.plan()
        receipt = self.app.export(run["id"])
        folder = Path(receipt["output_dir"])
        moved = folder.with_name("other")
        folder.rename(moved)
        folder.symlink_to(moved, target_is_directory=True)
        with self.assertRaisesRegex(Refusal, "SYMLINK"):
            self.app.export(run["id"])

    def test_required_whitespace_is_missing_without_implicit_trim(self):
        s = self.plan("id,amount\n   ,1\n")["summary"]
        self.assertEqual(s["issue_counts"], {"REQUIRED": 1})

    def test_large_worldwide_demo_exact_measured_counts(self):
        contract = json.loads((ROOT / "demo/contract.json").read_text())
        self.file.write_bytes((ROOT / "demo/orders-worldwide.csv").read_bytes())
        run = self.plan(contract=contract)
        s = run["summary"]
        self.assertEqual((s["input_rows"], s["clean_rows"], s["quarantined_rows"]), (10000, 9977, 23))
        self.assertEqual(s["issue_counts"], {"DATE_FORMAT": 5, "DUPLICATE_KEY": 3, "ENUM": 3, "FORMULA": 2, "RANGE": 2, "REQUIRED": 4, "ROW_WIDTH": 1, "TYPE": 3})
        receipt = self.app.export(run["id"])
        clean = (Path(receipt["output_dir"]) / "clean.csv").read_text()
        self.assertIn("000042", clean)
        self.assertNotIn("HYPERLINK", clean)
        quarantine = json.loads((Path(receipt["output_dir"]) / "quarantine.json").read_text())
        self.assertEqual(len(quarantine["records"]), 23)


if __name__ == "__main__":
    unittest.main(verbosity=2)
