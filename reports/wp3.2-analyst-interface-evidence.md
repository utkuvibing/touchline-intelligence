# WP3.2 analyst interface evidence

**Status:** implementation present; WP3.2 acceptance is **NOT CLOSED** and no `PASS` is claimed.
**Branch:** `codex/wp3-2-analyst-interface`
**Scope:** local frontend implementation over the frozen WP3.1 contract.
**Historical publication:** **NOT CLEARED**.
**Production deployment/smoke:** not part of WP3.2; remains **WP3.3–WP3.4**.

This report records only checks that actually ran. It does not claim external publication permission,
deployed model serving, browser smoke evidence, or an independent review that did not occur.

## Status separation

| Status | Result | Evidence boundary |
|---|---|---|
| Local WP3.2 implementation | Implemented in the working tree and rebased onto current `origin/main` | Frontend source, typed WP3.1 adapter, model-aware view, filters, map, detail panel, reliability view, limitations and attribution |
| Local WP3.2 acceptance | **NOT CLOSED** | Focused checks passed, but the required full mutation harness and responsive/manual inspection were not executable in this environment |
| Historical publication permission | **NOT CLEARED** | `/model/shots` remains closed by default; no StatsBomb/Hudl written direction was obtained or inferred |
| Production deployment/smoke | **NOT PART OF WP3.2** | No deployment, production variable change, or deployed smoke claim was made; WP3.3–WP3.4 own it |
| Independent review | **NOT RUN** | No independent Sol review or `PASS` was manufactured |

## Implemented contracts

- `/model`, `/model/metrics`, and `/model/shots` are fetched independently through the frozen
  WP3.1 interface; no backend endpoint was added or changed.
- Success payloads are parsed at runtime. Finite/bounded probabilities, reliability values, integer
  counts, required split literals, caveats, and structured errors are checked.
- All seven provenance identity fields must agree across model metadata, metrics, and every
  historical page:

  ```text
  model_version
  release_id
  serving_manifest_sha256
  release_manifest_sha256
  release_manifest_file_sha256
  artifact_sha256
  calibration_decision_sha256
  ```

- Historical paging uses a maximum page size of 1,000 and the first response's returned `total` as
  the UI source of truth. Duplicate IDs, changed totals/offsets/page sizes, short/stalled pages and
  inconsistent provenance are rejected. The pinned snapshot's 1,430-row / two-page result is tested
  as an acceptance invariant, not used as a presentation constant.
- Offset stability is limited to the WP3.1 condition that the pinned database snapshot remains
  unchanged between requests.
- A closed `publication_gate_closed` response is rendered as a publication notice. The frontend
  does not substitute raw `/shots` rows or issue one `/model/predict` request per historical row.
- Probability uses the exact affine-area mapping
  `r(p) = sqrt(0.45² + p × (2.40² − 0.45²))`.
- Goals are filled, non-goals hollow, and selection uses a separate outer ring. A single keyboard
  selector avoids putting every map marker in the tab order.
- Euro2024 reliability bins retain counts and positive counts, including sparse `n=4` and `n=1`
  bins. WC2022 calibration/adoption evidence remains visually separate from holdout evidence.
- Limitations, the independent-not-StatsBomb-xG statement, the historical calibration-data caveat,
  and visible StatsBomb attribution remain on the page.

## Executed verification

| Check | Result | Actual observation |
|---|---|---|
| `npm --prefix frontend test` | PASS | 4 files, 27 tests passed |
| `npm --prefix frontend run lint` | PASS | ESLint completed with no findings |
| `npm --prefix frontend run typecheck` | PASS | TypeScript completed with no errors |
| `npm --prefix frontend run build` | PASS | Next production build completed; `/` remained dynamic |
| `uv run poe check` | PASS | Ruff format/lint and mypy passed; pytest `932 passed, 303 skipped` |
| WP3.2 focused mutation verification | PASS | `7 CAUGHT, 0 MISSED` for attribution, gate state, caveat, sample sizes, area mapping, provenance and duplicate paging |
| Gate-closed local API/SSR check | PASS | `/model` 200, `/model/metrics` 200, `/model/shots` 403; rendered HTML contained the analyst heading, holdout heading, `publication_gate_closed`, and attribution |
| `git diff --check` | PASS | No whitespace errors in the final closeout diff |

## Required verification not executable here

The full repository mutation command was attempted:

```text
uv run python scripts/verify_tests_fail.py
```

It refused to run with exit code 2 because both required variables were unset:

```text
TOUCHLINE_DB_URL is not set
TOUCHLINE_FULL_COHORT_DB_URL is not set
```

This was not replaced with a remote Neon DSN. Docker Desktop was unavailable and no local
PostgreSQL listener was present on ports 5432 or 5433, so running the harness against an unsuitable
or remote target would have produced a misleading acceptance claim. The full mutation result is
therefore **BLOCKED / NOT RUN**, not passed.

Responsive/manual browser inspection was also not run in this environment. Historical gate-open
full-cohort UI inspection was not run; the public/default gate-closed state was inspected through
local API and server-rendered HTML only.

## Durable artifacts

- Contract: [`docs/interface/wp3_2-analyst-interface-contract.md`](../docs/interface/wp3_2-analyst-interface-contract.md)
- This evidence report: `reports/wp3.2-analyst-interface-evidence.md`
- Frontend model adapter: `frontend/lib/model-api.ts`
- Frontend view: `frontend/components/AnalystView.tsx`
- Frontend contract tests: `frontend/lib/model-api.test.ts`, `frontend/lib/model-view.test.ts`,
  `frontend/components/HomeView.test.tsx`

The historical publication gate remains unresolved, and no production deployment or smoke result is
implied by these local checks.
