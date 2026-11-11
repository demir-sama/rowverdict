# Verification record

Executed on the shared Linux box on **11 November 2026, Africa/Lagos (WAT)**.
This record describes actual tests, not public CI or a certification.

## Verified

| Layer | Result | Evidence |
|---|---|---|
| Deterministic unit/regression suite | **61 passed**, Python 3.13.5 | `evidence/core-tests.txt` |
| Same suite under Hermes-managed Python 3.14.9 | **61 passed** | `evidence/core-tests-python314.txt` |
| Stable Hermes catalog admission with `--install-deps` | **PASS**, security scan **safe**, no core overrides/collisions, declarations match | `evidence/validate-stable.txt` |
| Stable Hermes Doctor `--ci` | **PASS**, real runtime discovery/import/registration; four tools, one hook | `evidence/doctor-stable.txt` |
| Researched current-main snapshot admission + Doctor | **PASS** | `evidence/validate-main.txt`, `evidence/doctor-main.txt` |
| Actual installed native tools | Four discovered; inspect and plan process 10,000 records; history reads durable plan | `evidence/hermes-runtime-smoke.txt` |
| Actual host unattended approval | Export directive is `approve`; real stable host refuses without a human/bridge; **no artifacts** for denied plan | same |
| Actual stable dashboard host | Unauthenticated API 401; fresh QA-token authenticated scoped plugin API 200; detail/404 and no export route; manifest/JS/CSS served 200 | `evidence/dashboard-host-tests.txt` |
| Dashboard structure | Real host React renders evidence/contract/drift/receipt views, filter/sort and refresh path; no browser claimed | `evidence/dashboard-render-tests.txt` |
| Offline end-to-end core demonstration | 9,977 + 23 = 10,000; real artifacts, unchanged source, retained ID zeros, column drift, stale refusal and reload | `evidence/demo-core.txt` |

Stable target is **v0.23.1**, upstream commit
`3b421578588243f920886e6fe79a6faa87ea026e`. This is a separate local worktree of the
release tag, not an assertion that an arbitrary main checkout is stable.

The tests cover UTF-8/BOM, quoted commas/newlines, malformed rows, empty input,
header/schema mismatches, full-row/byte/column/field/total-cell/contract-size bounds, exact Decimal arithmetic
beyond default precision, explicit dates/separators, enum/ranges, optional/required
cells, all-conflict duplicate quarantine, no raw row data in tool plans/SQLite,
conservation, source and engine-source drift, private POSIX permissions,
traversal/symlink/FIFO refusal, concurrent/idempotent exports, atomic staging cleanup,
publish-before-commit recovery, artifact/receipt tampering, and persisted restart state.

## Not verified / not completed

- **Affirmative human host approval round-trip.** The actual fail-closed path is
  verified; deterministic export is verified separately. No approval was forged,
  auto-answered or retried through another route for the denied native plan.
- **Live model-generated tool call.** Official free-endpoint attempts reached Nous
  (HTTP 402) and OpenRouter (HTTP 401) without a credential available through the
  supported accessor. Neither succeeded. See `evidence/free-inference-smoke.json`.
- **Interactive browser visual/keyboard QA or a real dashboard screenshot.** The
  executor has no browser/screenshot tool. The CLI illustration is explicitly a
  rendered transcript. Parent can capture the actual live dashboard next.
- **Public GitHub publication / public commit reachability / fresh remote install
  at the pin / GitHub Actions / catalog CI or maintainer admission.** The inline
  connector cannot create/push repository contents; `gh` needs normal restored
  sign-in. A local pass is not a maintainer approval.
- **Video recording, X post, catalog PR or hackathon form submission.** None sent.
- Windows/macOS, network filesystems, hostile same-user processes, older Hermes,
  financial/business correctness and universal spreadsheet formula prevention.

## Reproduction notes

`python3 -m unittest discover -s tests -v` needs no external package. The optional
render test uses an already-installed Hermes web workspace:

```bash
HERMES_CHECKOUT=/path/to/hermes-agent node scripts/test_dashboard.cjs
```

It uses `evidence/dashboard-api.json`, a captured plan for the synthetic fixture,
not real customer data. It is a structural render test, not browser automation.
The GitHub workflow is prepared but has not run remotely.

The first isolated `--install-deps` attempt used a fresh HERMES_HOME with no managed
Python and hit a download TLS error. Re-running the same sanctioned validator
with the already-provisioned isolated runtime home completed cleanly. The real
stable dashboard build initially found system Node/pnpm too old; the official
Hermes toolchain helper installed its exact Node 26.12.1 / pnpm 12.15.0 pins,
after which the stable web build passed. No platform guards were disabled.
