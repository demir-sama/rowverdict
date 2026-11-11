# Practical workflows

## 1. Draft without silently applying inference

1. Configure a narrow input root, or explicitly enable private dashboard uploads.
2. Inspect the file. Multi-sheet XLSX requires an exact worksheet name.
3. Create a draft. It remains `DRAFT` and creates no run/export.
4. Check identifiers/zeroes, inferred required fields, enum completeness and date ambiguity. Edit the JSON as needed.
5. Accept through the dashboard's explicit authenticated review action, or request `rowverdict_review` and review its native host approval card.
6. Create a plan using the source and reviewed draft ID. Every row is scanned. A changed source or policy cannot borrow a different review.

Manual contracts remain supported. Once this source snapshot has draft proposals, its exact policy must have a recorded draft review; extracting or modifying suggested_contract does not skip that step.

## 2. Correct a rejected record

Select a plan → Review → search/filter quarantine → Correct → edit fields → Stage correction → Preview replay → Create new replay plan. Alternatively pass an inline JSON patch or absolute .json patch_file to `rowverdict_replay`. Only quarantined record numbers may change; wrong-width rows require complete cells replacement.

Replay is a **new review plan only**. It merges the correction logically into the original ordered dataset, rechecks every record against the same contract and all duplicate-key groups, and never edits input files or appends clean rows twice. A corrected value may still be rejected. Approve `rowverdict_export` of the **new child ID**, not the parent, to produce new artifacts/receipt/report. Keep source and any file patches unchanged until export.

## 3. Export safely / share an audit

Review plan counts, exact policy, quarantine reasons and drift. Use Check freshness. In Hermes ask for `rowverdict_export({"plan_id":"..."})` and review the native approval card. Refresh the dashboard after approval. The dashboard has no export route and cannot approve on your behalf.

`/rowverdict export ID` provides the exact safe native-tool handoff; it never calls an ungated registry write. If a host call was denied, do not retry via the QA CLI or direct Python.

Download the receipt-verified HTML audit from the Export/report step. It contains no raw rows or external assets, but paths/schema/category metadata may be sensitive. Before approval the download is an explicitly marked **unapproved preview**, not a clean export.

## API boundary

Hermes provides authentication and active-profile routing. GET /runs, /runs/{id}, /quarantine and /report read state/data. POST /inspect, /drafts, /drafts/{id}/review, /plans, /runs/{id}/replays, /runs/{id}/check and opt-in /inputs perform bounded review workflows. No route publishes clean/quarantine/export artifacts. Native review/export tools use the host hook. Pydantic request bodies reject unknown fields; review requires exact source hash and explicit operator acknowledgement. Authenticated operator review is not advertised as cryptographic proof of human presence.

## Keyboard / accessibility

All interactions use native buttons, labeled inputs/selects/textareas and checkboxes, semantic tables with captions/headers, visible :focus-visible outlines, polite status announcements and alert errors. Workflow buttons use aria-current, history uses aria-pressed; raw row text is React-escaped. No drag-only interaction, motion dependency, color-only state indicator or global keyboard shortcut is required. High-contrast color pairs are checked separately; browser/screen-reader certification is not claimed.
