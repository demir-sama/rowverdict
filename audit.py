"""Self-contained, escaped audit document. Deliberately excludes raw row values."""
import html
import json


def render_report(run, receipt=None):
    def esc(value):
        return html.escape(str(value), quote=True)

    def block(value):
        return "<pre>" + esc(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)) + "</pre>"

    summary = run["summary"]
    counts = "".join("<li><strong>" + esc(summary[key]) + "</strong> " + label + "</li>"
                     for key, label in [("input_rows", "input records"), ("clean_rows", "clean"), ("quarantined_rows", "quarantined")])
    events = "".join("<tr><td>" + esc(event["row"]) + "</td><td>" + esc(event["column"]) + "</td><td>" + esc(event["code"]) + "</td></tr>"
                     for event in summary.get("evidence", []))
    hashes = {"source_sha256": run["source_sha256"], "policy_sha256": run["policy_sha256"],
              "engine_sha256": summary.get("engine_sha256")}
    if receipt:
        hashes.update(receipt_core_sha256=receipt.get("receipt_core_sha256"), artifacts=receipt.get("artifacts", {}))
        # The report is hashed by the final receipt, never by itself.
        hashes["artifacts"] = {k: v for k, v in hashes["artifacts"].items() if k != "audit.html"}
    state = "EXPORTED — verified local artifacts" if receipt else "PREVIEW — NOT EXPORTED / NOT AN APPROVAL"
    return """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>RowVerdict audit</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#080808;color:#f5f5f5;font:16px/1.6 system-ui,sans-serif}main{max-width:1040px;margin:auto;padding:40px 24px}h1{font-size:40px;letter-spacing:-1.5px;margin:0}h2{margin-top:36px;font-size:21px}p{color:#c6c6c6}ul.counts{display:flex;gap:12px;padding:0;list-style:none;flex-wrap:wrap}.counts li{padding:18px;background:#151515;border:1px solid #383838;border-radius:10px}.counts strong{font-size:25px;color:#b5f5d0}pre{background:#121212;border:1px solid #383838;border-radius:8px;padding:18px;white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:10px;border-bottom:1px solid #383838}th{color:#b5f5d0}code{overflow-wrap:anywhere}.state{color:#f3d18b}footer{margin-top:40px;border-top:1px solid #383838;padding-top:20px;color:#bdbdbd}@media print{body{background:white;color:black}p,footer{color:#333}pre,.counts li{background:#f4f4f4}.counts strong,th,.state{color:#164b30}}
</style></head><body><main><header><p>HERMES / LOCAL DATA OPERATIONS</p><h1>RowVerdict audit</h1><p class="state">""" + esc(state) + """</p></header><p>Plan <code>""" + esc(run["id"]) + "</code> · " + esc(run["created"]) + "</p><p>Source: <code>" + esc(run["source"]) + "</code></p><ul class=counts>" + counts + "</ul><p>Row conservation: " + ("PASS" if summary["row_conservation"] else "FAIL") + """. No rows are silently dropped. All members of duplicate-key groups are quarantined.</p>
<h2>Policies / reviewed contract</h2>""" + block(run["contract"]) + "<h2>Quarantine reasons</h2>" + block(summary["issue_counts"]) + "<table><thead><tr><th>Record</th><th>Column</th><th>Reason</th></tr></thead><tbody>" + events + """</tbody></table><p>Evidence is bounded to the first 250 issue events. Counts scan every record. Raw sensitive cells are deliberately excluded; quarantine.json contains the complete quarantine.</p>
<h2>Drift from the previous plan</h2>""" + block(run["drift"]) + "<h2>Replay / draft provenance</h2>" + block({k: summary[k] for k in ("replay", "draft_review", "input_format", "worksheet") if k in summary}) + "<h2>Integrity hashes / receipt</h2>" + block(hashes) + """<p>The receipt-core hash covers the canonical receipt before the audit artifact and receipt_core_sha256 fields are added. The final receipt hashes audit.html; a receipt never hashes itself. No external signing authority is claimed.</p>
<footer>Self-contained HTML · no scripts, remote fonts, images, analytics or external assets. Review source paths, schema and category names before sharing; this document may reveal metadata. Host approval gates exported artifacts, not arbitrary shell tools.</footer></main></body></html>"""
