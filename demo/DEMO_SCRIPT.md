# RowVerdict — 80-second demo

Target **80 seconds**, 75–85 allowed. About 190 spoken words; rehearse at 145–150
words/minute with short pauses. Use only the synthetic fixtures. Do not claim a
live model or a human approval happened unless it actually did on the recording.

## Recording prerequisites

1. Install/enable in Hermes >=0.23.1; configure a narrow input root outside `.hermes`.
2. Copy both sample CSVs to a disposable inbox. Use the same `orders.csv` path for
   revision/drift, and the matching explicitly reviewed contract for each schema.
3. Open the real dashboard RowVerdict tab; enlarge readable text. Pre-stage commands,
   not fabricated outputs. Hide unrelated accounts/keys. Do not show provider settings.
4. Have normal provider sign-in completed for a live chat. The offline core works
   without it, but label an offline recording “deterministic core demo” instead.
5. The baseline is **9,977 clean / 23 quarantine / 10,000 input**. Revision adds
   `channel` and two enum issues; do not replace measured counts with marketing numbers.

## Shot list + voiceover

| Time | On screen | Say |
|---|---|---|
| 0–10 | Synthetic CSV, zero-padded identifier; switch to Hermes | “A CSV can look fine in chat and still break your import. RowVerdict gives Hermes a reviewable transaction, not a best-effort cleanup prompt.” |
| 10–25 | Invoke native inspect + plan using the explicit demo contract; open queue/evidence | “This is ten thousand synthetic orders across twenty countries. Every record is checked. Nothing is sampled. Nine thousand nine hundred seventy-seven are clean; twenty-three are quarantined. Duplicate identifiers, wrong date formats, and formula-like cells stay out.” |
| 25–40 | Contract tab; show ID policy, trim and DD/MM date policy; highlight record evidence | “I choose the policy: keep identifiers as strings, trim customer names, and normalize explicitly declared dates. No guessed money formats. No keeping the first duplicate and quietly dropping the others. The contract, not inference, decides.” |
| 40–55 | Native export request, actual host approval prompt, user approves; receipt and artifact directory | “I review the plan and approve this exact export in Hermes. The original stays unchanged. Clean rows, raw quarantined records, and a hash-bound receipt are written together. Both data files have independently recorded verification hashes.” |
| 55–70 | Replace disposable source with revision; new contract/plan; drift shows channel and +2 enum; then mutate source and request export | “The next export adds a column; drift makes it visible. Now I change the source after review. RowVerdict refuses the stale plan instead of exporting something I never approved. A new review is required.” |
| 70–80 | Refresh dashboard/history; EXPORTED and STALE states remain | “Reload the review desk: the evidence and receipt persist. No rows disappear. No uploads. No silent repairs. Local, deterministic, and auditable. RowVerdict for Hermes.” |

## Honesty / contingency

- Do not auto-answer or simulate a host approval, even in a demo. Get the actual
  human click. The present build verified fail-closed unattended approval, not the
  live affirmative human round-trip.
- If provider sign-in remains unavailable, show `python3 scripts/demo_run.py` as a
  clearly labeled **offline deterministic-core demo**. Replace the 40–55 voiceover:
  “This offline QA command exports the reviewed fixture. In Hermes, the native
  export tool additionally requests the host's human approval.” Do not overlay a
  fake chat or approval prompt.
- The dashboard is read-only, so there is no “Approve” button in this plugin panel.
- Keep raw formula text confined to the synthetic input/JSON view; never activate a
  link or paste it into a spreadsheet. Only source code/text should be recorded.
- No video, X post, catalog PR or submission form is sent by these instructions.
