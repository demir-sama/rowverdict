/* RowVerdict 0.1.0. Handwritten, unminified IIFE. React comes ONLY from Hermes SDK. */
(function () {
  "use strict";
  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK || !window.__HERMES_PLUGINS__) return;
  const React = SDK.React;
  const h = React.createElement;
  const {useState, useEffect, useMemo} = SDK.hooks;
  const labels = {DATE_FORMAT: "Date format", DUPLICATE_KEY: "Conflicting identifier", TYPE: "Numeric format", FORMULA: "Formula-like cell", RANGE: "Outside allowed range", REQUIRED: "Missing required value", ROW_WIDTH: "Wrong field count", ENUM: "Unlisted value"};
  const count = x => Number(x || 0).toLocaleString();
  const short = x => (x || "").slice(0, 12);
  const el = (tag, cls, children, props) => h(tag, Object.assign({className: cls || ""}, props || {}), ...(Array.isArray(children) ? children : [children]));
  const code = value => el("code", "rv-code", value);
  const chip = (text, tone) => el("span", "rv-chip " + (tone || ""), text);
  const stat = (number, label, tone) => el("div", "rv-stat " + tone, [el("strong", "", number, {key: "n"}), el("span", "", label, {key: "l"})]);

  function App() {
    const [runs, setRuns] = useState([]);
    const [selected, setSelected] = useState("");
    const [view, setView] = useState("evidence");
    const [filter, setFilter] = useState("ALL");
    const [ascending, setAscending] = useState(true);
    const [busy, setBusy] = useState(true);
    const [error, setError] = useState("");
    async function refresh() {
      setBusy(true); setError("");
      try {
        const data = await SDK.fetchJSON("/api/plugins/rowverdict/runs");
        setRuns(data.runs || []);
        setSelected(old => (data.runs || []).some(r => r.id === old) ? old : ((data.runs || [])[0] || {}).id || "");
      } catch (e) { setError("Could not load the review queue. Check that RowVerdict is enabled and refresh."); }
      finally { setBusy(false); }
    }
    useEffect(() => {refresh();}, []);
    const run = runs.find(r => r.id === selected);
    const evidence = useMemo(() => {
      const rows = run ? (run.summary.evidence || []) : [];
      return rows.filter(r => filter === "ALL" || r.code === filter).slice().sort((a,b) => (a.row-b.row) * (ascending ? 1 : -1));
    }, [run, filter, ascending]);
    const summary = run ? run.summary : {};
    const issues = Object.entries(summary.issue_counts || {}).sort((a,b) => b[1]-a[1]);
    const maximum = Math.max(1, ...issues.map(x => x[1]));
    const sourceName = run ? run.source.split("/").pop() : "No plan selected";
    const tabs = ["evidence", "contract", "drift", "receipt"];
    return el("div", "rv", [
      el("header", "rv-heading", [
        el("div", "", [el("p", "rv-eyebrow", "HERMES / LOCAL DATA OPERATIONS"), el("h1", "", ["Row", el("span", "rv-accent", "Verdict")]), el("p", "rv-subtitle", "Trust the import. Keep the evidence.")]),
        el("div", "rv-top-actions", [chip("LOCAL ONLY", "green"), el("button", "rv-button", busy ? "Loading…" : "↻ Refresh", {onClick: refresh, disabled: busy})])
      ]),
      error ? el("div", "rv-error", error, {role:"alert"}) : null,
      el("div", "rv-boundary", [el("span", "rv-dot", ""), "Read-only review desk · Exports require the Hermes approval gate · Originals are never edited"]),
      !run ? el("section", "rv-empty", [el("div", "rv-empty-mark", "✓"), el("h2", "", busy ? "Loading local history" : "Every clean import starts with a review"), el("p", "", "Configure allowed_roots, then ask Hermes to inspect a CSV and create an explicit RowVerdict plan. No sample data is fabricated here."), code('rowverdict_inspect({"source":"/absolute/path/orders.csv"})')]) :
      el("div", "rv-layout", [
        el("aside", "rv-queue", [el("div", "rv-section-heading", [el("h2", "", "Review queue"), chip(String(runs.length))]), el("p", "rv-muted", "Persisted across restarts · newest first"),
          ...runs.map(r => el("button", "rv-run " + (r.id === selected ? "active" : ""), [
            el("span", "rv-run-top", [el("strong", "", r.source.split("/").pop()), chip(r.state, r.state === "EXPORTED" ? "green" : r.state === "STALE" ? "red" : "amber")]),
            el("span", "rv-muted", count(r.summary.input_rows) + " records · " + count(r.summary.quarantined_rows) + " quarantined"),
            code(short(r.id))
          ], {key:r.id, onClick:()=>{setSelected(r.id); setFilter("ALL");}, "aria-pressed":r.id === selected}))]),
        el("main", "rv-main", [
          el("section", "rv-card rv-file", [el("div", "", [el("p", "rv-eyebrow", "SOURCE-BOUND PLAN"), el("h2", "", sourceName), el("p", "rv-filepath", run.source)]), chip(run.state, run.state === "EXPORTED" ? "green" : run.state === "STALE" ? "red" : "amber")]),
          el("div", "rv-stats", [stat(count(summary.input_rows), "records fully scanned", "neutral"), stat(count(summary.clean_rows), "ready for clean CSV", "green"), stat(count(summary.quarantined_rows), "quarantined, not discarded", "amber")]),
          el("div", "rv-conservation", [el("strong", "", summary.row_conservation ? "✓ No rows disappear" : "⚠ Conservation failed"), el("span", "", `${count(summary.clean_rows)} clean + ${count(summary.quarantined_rows)} quarantine = ${count(summary.input_rows)} input`)]),
          el("section", "rv-card", [
            el("nav", "rv-tabs", tabs.map(t => el("button", view === t ? "active" : "", t[0].toUpperCase()+t.slice(1), {key:t,onClick:()=>setView(t),"aria-pressed":view===t})), {"aria-label":"Plan details"}),
            view === "evidence" ? el("div", "rv-tab-content", [
              el("div", "rv-section-heading", [el("h3", "", "What needs a decision"), chip("NO ROW VALUES SENT TO THE MODEL")]),
              el("div", "rv-issues", issues.length ? issues.map(([name,n]) => el("button", "rv-issue " + (filter === name ? "chosen" : ""), [el("span", "", labels[name] || name), el("span", "rv-bar", el("i", "", "", {style:{width:(n/maximum*100)+"%"}})), el("strong", "", count(n))], {key:name,onClick:()=>setFilter(filter===name ? "ALL" : name)})) : el("p", "rv-muted", "No issues found under this exact contract.")),
              el("div", "rv-section-heading", [el("h3", "", "Row evidence"), el("button", "rv-link", filter === "ALL" ? "All issue types" : "Clear filter", {onClick:()=>setFilter("ALL")})]),
              summary.evidence_truncated ? el("p", "rv-muted", "Showing the first 250 issue events only. Counts above include every record; quarantine.json holds all rejected records.") : null,
              el("div", "rv-table-wrap", el("table", "rv-table", [el("thead", "", el("tr", "", [el("th", "", el("button", "rv-link", "Record " + (ascending ? "↑" : "↓"), {onClick:()=>setAscending(!ascending)})), el("th", "", "Column"), el("th", "", "Verdict")])),
                el("tbody", "", evidence.map((r,i) => el("tr", "", [el("td", "", code(String(r.row))), el("td", "", r.column), el("td", "", chip(labels[r.code] || r.code, "amber"))], {key:i})))])),
              el("p", "rv-muted", "Record 1 is the header. Embedded newlines do not create new records. All members of a duplicate-key group are quarantined.")]) : null,
            view === "contract" ? el("div", "rv-tab-content", [el("h3", "", "Only declared transformations"), el("p", "rv-muted", "Exact ordered schema. No type inference, guessed dates, currency conversion, arbitrary code or silent deduplication."),
              el("div", "rv-table-wrap", el("table", "rv-table", [el("thead", "", el("tr", "", ["Column", "Type", "Explicit policy"].map(t=>el("th", "", t, {key:t})))), el("tbody", "", run.contract.columns.map(c => el("tr", "", [el("td", "", c.name), el("td", "", code(c.type)), el("td", "", [c.required?"required":"optional",c.trim?"trim":"no trim",c.date_format,c.decimal_separator?"decimal: "+c.decimal_separator:null,c.min!==undefined?"min: "+c.min:null,c.max!==undefined?"max: "+c.max:null,c.enum?"enum: "+c.enum.join(" / "):null].filter(Boolean).join(" · "))], {key:c.name})))])),
              el("p", "rv-muted", "Unique key: " + (run.contract.unique_key.join(" + ") || "not declared")), code("Policy SHA256: " + run.policy_sha256)]) : null,
            view === "drift" ? el("div", "rv-tab-content", [el("h3", "", "Compare with the previous plan"), !run.drift.previous_plan_id ? el("p", "rv-muted", "This is the first plan for this exact source path.") : el("div", "rv-drift", [
              el("p", "", ["Previous plan: ", code(run.drift.previous_plan_id)]), el("p", "", "Input record delta: " + run.drift.input_rows_delta), el("p", "", "Added columns: " + (run.drift.added_columns.join(", ") || "none")), el("p", "", "Removed columns: " + (run.drift.removed_columns.join(", ") || "none")), el("p", "", "Column order changed: " + (run.drift.order_changed?"yes":"no")), el("p", "", "Contract changed: " + (run.drift.contract_changed?"yes; comparisons may reflect policy changes":"no")),
              el("pre", "rv-json", JSON.stringify(run.drift.issue_delta,null,2))]), el("p", "rv-muted", "Schema mismatches are refused until you explicitly declare a new matching contract. Drift never silently approves new columns.")]) : null,
            view === "receipt" ? el("div", "rv-tab-content", [el("h3", "", run.receipt ? "Immutable export receipt" : "Review first. Export second."),
              el("p", "rv-muted", "Exports contain clean.csv, raw-cell quarantine.json and receipt.json, written atomically to a private per-plan directory. Nothing is uploaded or imported."),
              el("dl", "rv-hashes", [el("dt", "", "Source SHA256"),el("dd", "", code(run.source_sha256)),el("dt", "", "Policy SHA256"),el("dd", "", code(run.policy_sha256))]),
              run.receipt ? el("div", "", [el("p", "rv-muted", "Private artifact directory"), code(run.receipt.output_dir), el("pre", "rv-json", JSON.stringify(run.receipt.artifacts,null,2))]) : el("div", "rv-export-note", [el("strong", "", run.state === "STALE" ? "Source changed. Create a new plan." : "Continue in your Hermes conversation"), el("p", "", "Review this contract and evidence. Then approve this exact plan through Hermes:"), code('rowverdict_export({"plan_id":"'+run.id+'"})'), el("p", "rv-muted", "This panel has no export endpoint and cannot approve on your behalf.")])]) : null
          ]),
          el("footer", "rv-footer", [el("span", "", "ROWVERDICT 0.1.0 / DETERMINISTIC BY DESIGN"), el("span", "", "No network · No per-row inference · No silent repairs")])
        ])
      ])
    ]);
  }
  window.__HERMES_PLUGINS__.register("rowverdict", App);
})();
