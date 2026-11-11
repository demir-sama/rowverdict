"""Reproducible synthetic worldwide order exports; no real people or businesses."""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADER = ["order_id", "customer", "country", "currency", "amount", "ordered_on", "status", "reference"]
PLACES = [("US", "USD", "Avery Chen"), ("BR", "BRL", "Ana Silva"), ("GB", "GBP", "Jamie Morgan"),
          ("DE", "EUR", "Lena Fischer"), ("JP", "JPY", "Haruto Sato"), ("IN", "INR", "Aarav Mehta"),
          ("AU", "AUD", "Alex Nguyen"), ("ZA", "ZAR", "Lerato Dube"), ("NG", "NGN", "Ada Okafor"),
          ("KE", "KES", "Amani Otieno"), ("CA", "CAD", "Morgan Tremblay"), ("MX", "MXN", "Sofia Reyes"),
          ("AE", "AED", "Noor Haddad"), ("SG", "SGD", "Wei Tan"), ("FR", "EUR", "Camille Martin"),
          ("KR", "KRW", "Jiwoo Kim"), ("NZ", "NZD", "Taylor Rangi"), ("AR", "ARS", "Valentina Diaz"),
          ("SE", "SEK", "Robin Andersson"), ("ID", "IDR", "Dewi Putri")]


def generate(path, revision=False):
    rows = []
    for i in range(1, 10001):
        country, currency, customer = PLACES[(i - 1) % len(PLACES)]
        row = [f"{i:06}", customer, country, currency, f"{100 + i % 900}.{i % 100:02}",
               f"{1 + i % 28:02}/10/2026", "paid" if i % 3 else "pending", f"WEB-{i:06}"]
        if i % 113 == 0:
            row[1] = "  " + customer + "  "
        if i == 42:
            row[1] = "Ana, synthetic customer"
        if i == 77:
            row[7] = "Two-line\nsynthetic note"
        if i in {101, 102}:
            row[0] = "000100"  # ALL three conflicting IDs must quarantine, not keep first.
        if i in {201, 202, 203, 204, 205}:
            row[5] = "10/31/2026"  # explicitly DD/MM contract: refuse, never guess.
        if i in {301, 302, 303}:
            row[4] = "1,234.50"  # grouping refused, not auto-corrected.
        if i in {401, 402}:
            row[7] = '=HYPERLINK("https://example.invalid","synthetic")'
        if i in {501, 502, 503, 504}:
            row[1] = ""
        if i in {601, 602, 603}:
            row[6] = "settled"  # not in explicit enum.
        if i in {701, 702}:
            row[4] = "-10.00"
        if i == 801:
            row.append("unexpected field")
        if revision:
            row.append("online")
            if i in {901, 902}:
                row[6] = "unknown"
        rows.append(row)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(HEADER + (["channel"] if revision else []))
        writer.writerows(rows)


if __name__ == "__main__":
    target = ROOT / "demo"
    target.mkdir(exist_ok=True)
    generate(target / "orders-worldwide.csv")
    generate(target / "orders-worldwide-revision.csv", True)
    columns = [
        {"name": "order_id", "type": "string", "required": True},
        {"name": "customer", "type": "string", "required": True, "trim": True},
        {"name": "country", "type": "string", "enum": [x[0] for x in PLACES]},
        {"name": "currency", "type": "string", "enum": sorted({x[1] for x in PLACES})},
        {"name": "amount", "type": "decimal", "decimal_separator": ".", "min": "0", "max": "1000000"},
        {"name": "ordered_on", "type": "date", "date_format": "%d/%m/%Y"},
        {"name": "status", "type": "string", "enum": ["paid", "pending", "refunded"]},
        {"name": "reference", "type": "string", "required": False},
    ]
    contract = {"columns": columns, "unique_key": ["order_id"], "delimiter": ","}
    (target / "contract.json").write_text(json.dumps(contract, indent=2) + "\n")
    columns.append({"name": "channel", "type": "string", "enum": ["online", "retail"]})
    (target / "contract-revision.json").write_text(json.dumps(contract, indent=2) + "\n")
