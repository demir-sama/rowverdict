"""Conservative proposals only. The engine separately enforces explicit draft review."""
import re
from datetime import datetime


def infer(header, rows, sample_rows=1000, delimiter=",", sheet=None):
    sample = [row for row in rows[:sample_rows] if len(row) == len(header)]
    columns, notes, ids = [], [], []
    for index, name in enumerate(header):
        values = [row[index] for row in sample]
        nonempty = [v for v in values if v.strip()]
        tokens = re.sub(r"([a-z])([A-Z])", r"\1_\2", name).lower().split("_")
        identifier = any(t in {"id", "identifier", "sku", "code", "zip", "postal", "phone", "account"} for t in tokens)
        col = {"name": name, "type": "string", "required": bool(values and len(nonempty) == len(values)), "trim": False}
        reason = "Conservative string; no reliable unambiguous type in sample."
        if identifier:
            reason = "Identifier candidate: preserve strings and leading zeroes."
            if nonempty and len(nonempty) == len(values) and len(set(nonempty)) == len(values):
                ids.append(name)
        elif nonempty and not any(v != v.strip() or v.lstrip().startswith(("=", "+", "@")) for v in nonempty):
            if all(re.fullmatch(r"-?[0-9]+", v) and not re.fullmatch(r"-?0[0-9]+", v) and len(v) <= 64 for v in nonempty):
                col["type"] = "integer"
                reason = "Every nonempty sampled value is an integer without leading zeroes."
            elif all(re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", v) and len(v) <= 64 for v in nonempty):
                if not any(re.fullmatch(r"-?0[0-9]+(?:\.[0-9]+)?", v) for v in nonempty):
                    col.update(type="decimal", decimal_separator=".")
                    reason = "Every nonempty sampled value is a plain dot-decimal number."
            else:
                candidates = []
                for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
                    try:
                        for value in nonempty:
                            datetime.strptime(value, fmt)
                        candidates.append(fmt)
                    except ValueError:
                        pass
                if len(candidates) == 1:
                    col.update(type="date", date_format=candidates[0])
                    reason = "One supported date format fits the sample."
                elif len(candidates) > 1:
                    reason = "AMBIGUOUS day/month order: string retained; choose a date format manually."
        categorical = any(t in {"status", "country", "currency", "category", "region", "segment", "channel", "priority"} for t in tokens)
        distinct = sorted(set(nonempty))
        if categorical and col["type"] == "string" and len(nonempty) >= 3 and 1 <= len(distinct) <= min(12, len(nonempty) // 2) and all(len(v) <= 64 and not any(ord(c) < 32 for c in v) and not v.lstrip().startswith(("=", "+", "-", "@")) for v in distinct):
            col["enum"] = distinct
            reason += " Small observed category enum proposed; unseen valid categories may exist."
        columns.append(col)
        notes.append({"column": name, "reason": reason})
    contract = {"columns": columns, "unique_key": ids[:1], "delimiter": delimiter}
    if sheet:
        contract["sheet"] = sheet
    return contract, notes, len(sample)
