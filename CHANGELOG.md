# Changelog

## 0.2.0 — 2026-11-11

- Add source-bound contract DRAFT proposals with conservative type/ID/date/enum inference and explicit immutable human review; extracting/editing a proposal cannot silently activate it.
- Add bounded flat JSON/JSONL/NDJSON and safe OOXML XLSX parsing; pin defusedxml==0.7.1 in pyproject.toml. Refuse unsafe XML/ZIP inputs; never evaluate formulas or fetch links.
- Add quarantined-row corrections and replay plans, full duplicate-key revalidation, immutable lineage, patch hashes and patch-file stale refusal.
- Add inspect/draft/plan/status/replay slash commands and plain-English summaries. Review/export commands fail safe with native-tool approval handoff because stable registry dispatch does not run pre-tool hooks.
- Atomically include self-contained escaped audit.html and receipt-core/data/report hashes in each new approved export; serve clearly marked unapproved previews separately.
- Replace the review-only tab with a true-dark, real-API workflow: opt-in local uploads, contract review, paginated/searchable quarantine, correction forms, replay previews, history and approval-safe report download. No export API.
- Preserve legacy history/receipts, bounds and source protection. Engine changes require unexported plans to be recreated.
- Expand automated core/native/API tests and refresh security, workflow, demo and admission documentation.

## 0.1.0 — 2026-11-11

Initial native Hermes CSV contract planning, quarantine, exact decimals, full-row validation, source/engine/policy binding, host-approved atomic exports, SQLite history and read-only dashboard review.
