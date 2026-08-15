# WP3.2 analyst interface evidence

**Status:** implementation present; the exhaustive local mutation gate is **PASS**, but WP3.2 local acceptance remains **NOT CLOSED** because responsive/manual inspection is outstanding. No overall or independent-review `PASS` is claimed.
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
| Local WP3.2 acceptance | **NOT CLOSED** | Focused checks and the exhaustive `uv run python` mutation run passed; responsive/manual inspection remains outstanding |
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
| WP3.2 full mutation verification (final homogeneous run) | PASS | Repository-pinned Python 3.12.11, four sequential shards, `288 CAUGHT, 0 MISSED, 0 SKIP`; every `BREAKS` index executed exactly once |
| Gate-closed local API/SSR check | PASS | `/model` 200, `/model/metrics` 200, `/model/shots` 403; rendered HTML contained the analyst heading, holdout heading, `publication_gate_closed`, and attribution |
| `git diff --check` | PASS | No whitespace errors in the final closeout diff |

## Full mutation verification and local environment

The local acceptance database was established without using Neon or any shared/remote database:

```text
Docker service: touchline-postgres
Image: postgres:17-alpine
Host mapping: localhost:5433 -> container 5432
Health: healthy
TOUCHLINE_DB_URL=postgresql://touchline:localdev@localhost:5433/touchline
TOUCHLINE_FULL_COHORT_DB_URL=postgresql://touchline:localdev@localhost:5433/touchline
```

The repository requires Python `>=3.12,<3.13`; every final shard wrapper was invoked through
`uv run python`, which reported Python `3.12.11`. The harness was loaded with `runpy` under a
non-`__main__` name, so `main()` was not invoked. It reported `len(BREAKS) = 288` before execution.

The initial monolithic `uv run python scripts/verify_tests_fail.py` run was incomplete because the
serial 288-entry process reached the 1,800-second execution limit before producing final totals. A
later provisional shard attempt used the system Python interpreter; its results, including the
index-86 compile failure, are discarded entirely and contribute nothing to this evidence. The
final run below is the only mutation result counted.

Each final shard called the existing `preflight()` and `check(BREAKS[index])` functions in order,
used no parallelism, verified every mutation target's bytes and the tracked Git tree after each
entry, and confirmed restoration after the shard.

| Shard | First contract | Last contract | Executed | CAUGHT | MISSED | SKIP | Result |
|---|---|---|---:|---:|---:|---:|---|
| `[0,72)` | WP2.1 model cohort must exclude Penalty shot types | quality reporting must preserve generic-event position missingness | 72 | 72 | 0 | 0 | PASS |
| `[72,144)` | quality reporting must preserve generic-event duration missingness | WP2.4 constant baseline must use the training-fold goal rate only | 72 | 72 | 0 | 0 | PASS |
| `[144,216)` | WP2.4 reliability bin count is locked at five (ADR 0004) | WP2.6 validates the learned-parameter digest after strict load | 72 | 72 | 0 | 0 | PASS |
| `[216,288)` | WP2.6 validates final preprocessing against committed identity | WP3.1 Docker image contains the exact minimal serving bundle | 72 | 72 | 0 | 0 | PASS |
| **Aggregate** | — | — | **288** | **288** | **0** | **0** | **PASS** |

Exhaustive coverage is proven by the four non-overlapping ranges partitioning `[0,288)`, with each
wrapper asserting `executed == list(range(start, end))`: executed indices are exactly `0..287`,
unique executed index count is `288`, duplicate count is `0`, and missing count is `0`. The
previous system-Python attempt is not included in any total.

Responsive/manual browser inspection remains outstanding. Historical gate-open full-cohort UI
inspection was not run; the public/default gate-closed state was inspected through local API and
server-rendered HTML only. Historical publication remains **NOT CLEARED**, and production
deployment/smoke remains **WP3.3–WP3.4**.

## Durable artifacts

- Contract: [`docs/interface/wp3_2-analyst-interface-contract.md`](../docs/interface/wp3_2-analyst-interface-contract.md)
- This evidence report: `reports/wp3.2-analyst-interface-evidence.md`
- Frontend model adapter: `frontend/lib/model-api.ts`
- Frontend view: `frontend/components/AnalystView.tsx`
- Frontend contract tests: `frontend/lib/model-api.test.ts`, `frontend/lib/model-view.test.ts`,
  `frontend/components/HomeView.test.tsx`

The historical publication gate remains unresolved, and no production deployment or smoke result is
implied by these local checks.
