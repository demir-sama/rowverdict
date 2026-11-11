# RowVerdict 0.2.0 verification

Verification date: **2026-11-11 (Africa/Lagos / WAT, UTC+1)**. Local changes only; no new commit or catalog update has been published by this upgrade.

## Automated results

| Check | Result | Evidence |
|---|---|---|
| Full Python suite, Hermes-managed Python 3.14.9 | **122 passed, no skips**, including 13 FastAPI route tests | `evidence/tests-v020-python314.txt` |
| System Python 3.13.5 | **109 passed, 13 explicitly skipped** (host FastAPI/httpx absent) | `evidence/tests-v020-python313.txt` |
| JavaScript syntax | `node --check dashboard/dist/index.js` passes | repeatable command |
| Stable Hermes v0.23.1 Doctor `--ci` | PASS: 7 tools, 1 hook, slash registration | `evidence/doctor-v020-stable.txt` |
| Stable local admission with `--install-deps` | PASS, safe security scan, no core override, host-ready isolation | `evidence/validate-v020-stable.json` |
| Real stable-host API/auth/native integration | PASS: real mounts/assets, unauthenticated GET/POST 401, no export endpoint, native formats and fail-closed approval | `evidence/host-v020-tests.txt` |
| Real React 19.3.0 component against actual host API | **24 assertions passed** through source → draft → explicit review → plan → filter/search → correction → replay preview → child → safe handoff → STALE | same host log; `evidence/v020-ui/ui-result.json` |
| Contrast arithmetic | 11 foreground/control/focus pairs meet sampled WCAG AA thresholds | `evidence/v020-ui/contrast-checks.json` |
| Original worldwide baseline | 9,977 clean + 23 quarantined = 10,000 | `evidence/demo-v020.txt` |
| Actual UI correction/replay fixture | 9,978 clean + 22 quarantined = 10,000; parent unchanged | host/UI test log |

The suite retains the previous 61-test safety coverage; its former non-CSV-refusal case now refuses an unsupported PDF, because JSON is intentionally supported. Added tests cover draft extraction/review/immutability/staleness, conservative date/identifier/category inference, JSON precision/grammar/bounds, XML/ZIP attacks, Excel formulas/errors/dates/sheets, patch restrictions/duplicate rechecks/lineage/source+file staleness, HTML escaping/receipt integrity, approval hooks/slash handoffs, version consistency, independent profile/source module caches and real API operations.

Hermes stable source: `v0.23.1`, commit `3b421578588243f920886e6fe79a6faa87ea026e`. Runtime dependency: `defusedxml==0.7.1` declared in pyproject and prepared by Hermes PM. API tests used FastAPI 0.133.1 and httpx 0.28.1 from the host runtime. The test renderer and host TestClient emit their upstream deprecation notices; these are not failing assertions.

## Approval: what was actually verified

The real host returns `approve` directives for native draft acceptance/export, then **blocks unattended execution** when no person/gateway approval bridge exists. Stale source plans return `block`. Denied actions are never retried through a library/CLI. Positive EXPORTED history/report fixtures come from separately labeled explicit offline library QA, not a simulated affirmative human native approval.

The stable public dispatcher reaches `registry.dispatch` without pre_tool_call hooks. Therefore slash review/export deliberately return a native-tool handoff instead of calling that ungated dispatcher. Other slash commands invoke only inspect/draft/history/review-plan handlers. The dashboard has **no export route**. Its replay operation creates a new review plan only; native host export of that child still needs separate approval.

Not verified: a new live-model conversation, an actual affirmative human-host approval round-trip, or public catalog CI against the unpublished SHA. No claim of those is made. Exact-SHA public fetch/CI can only run after Lee approves publication.

## Visual evidence: honest document renders, not browser screenshots

The actual production IIFE was loaded with host-version React and exercised using a **non-DOM React test renderer**. Its fetches called the real authenticated Hermes host API through an own-app loopback TestClient bridge, not mock production responses. Resolved React trees with real persisted synthetic-fixture state were server-rendered as HTML. WeasyPrint 70.0 and pdftoppm produced PNGs without running a browser, browser JavaScript, CDP, Playwright or Puppeteer.

- `docs/dashboard-dark-source-render.png`
- `docs/dashboard-dark-contract-render.png`
- `docs/dashboard-dark-review-render.png`
- `docs/dashboard-dark-replay-render.png`
- `docs/dashboard-dark-export-render.png`
- `docs/dashboard-dark-stale-render.png`
- `docs/dashboard-dark-source-mobile-render.png`

Each image is labeled **not a browser capture**. They show the actual component/state/styles, but static document engines do not faithfully render every native input, scrolling or browser layout detail. Responsive CSS rules were resolved at the target document width (desktop 1440px, narrow 390px). These are useful visual snapshots, **not** certification of browser behavior, screen-reader navigation, all WCAG criteria or touch interactions. Form labels/current-step/status semantics and selected contrast pairs are tested separately. Native focus states are implemented but need final human browser/screen-reader QA.

No Shell-driven browser automation was used. The live local QA dashboard remains available for a legitimate browser-side review at `http://172.30.0.2:9124/rowverdict`, protected by the existing QA authentication. Credentials are not in this repository.

## Reproduce on this box

- Run all Python tests using the PM-prepared interpreter that contains the declared dependency plus the host's FastAPI/httpx.
- `hermes plugins validate /absolute/path/to/rowverdict --install-deps --json`
- `hermes plugins doctor /absolute/path/to/rowverdict --ci`
- Box-local integration runner: `/workspace/hackathons/hermes-plugin/verify-host-v020.py`; it intentionally uses this disposable QA profile, creates synthetic fixtures and never approves a native export.
- Box-local non-DOM component driver: `/workspace/hackathons/hermes-plugin/ui-qa/verify.cjs`.
- Box-local document renderer: `/workspace/hackathons/hermes-plugin/render-dark-documents.py`.

The final local catalog entry/patch lives outside the plugin repository under `catalog-prepared`; structural validation is recorded there. Publishing the plugin commit and updating PR #153092 are separate approval-required steps. The demo script was refreshed; no new video, post or form submission is claimed.
