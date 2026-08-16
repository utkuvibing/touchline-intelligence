# WP3.2 analyst interface evidence

**Status:** WP3.2 implementation and local acceptance are **REPAIRED / REVALIDATED**. The independent review returned **FAIL**; its remediation is locally revalidated, and independent re-review remains pending. No independent-review `PASS` is claimed.
**Branch:** `codex/wp3-2-analyst-interface`
**Scope:** local frontend implementation over the frozen WP3.1 contract.
**Historical publication:** **NOT CLEARED**.
**Production deployment/smoke:** not part of WP3.2; remains **WP3.3–WP3.4**.

This report records only checks that actually ran. It does not claim external publication permission,
deployed model serving, browser smoke evidence, or an independent-review `PASS` that did not occur.

## Status separation

| Status | Result | Evidence boundary |
|---|---|---|
| Local WP3.2 implementation | **REPAIRED / REVALIDATED** | Frontend source, typed WP3.1 adapter, model-aware view, filters, map, detail panel, reliability view, limitations and attribution |
| Local WP3.2 acceptance | **REVALIDATED** | Focused checks, fresh exhaustive mutation verification, controlled local API checks, and prior responsive/manual browser inspection passed |
| Historical publication permission | **NOT CLEARED** | `/model/shots` remains closed by default; no StatsBomb/Hudl written direction was obtained or inferred |
| Production deployment/smoke | **NOT PART OF WP3.2** | No deployment, production variable change, or deployed smoke claim was made; WP3.3–WP3.4 own it |
| Independent review | **FAIL — re-review pending** | Review found stale final-head mutation evidence, two pagination invariant gaps, and status drift; all remediation is locally revalidated, but no independent `PASS` is claimed |

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
  the UI source of truth. Duplicate IDs, over-limit pages, changed totals/offsets/page sizes,
  changed historical prediction caveats, short/stalled pages and inconsistent provenance are
  rejected. The pinned snapshot's 1,430-row / two-page result is tested as an acceptance invariant,
  not used as a presentation constant.
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
| `npm --prefix frontend test lib/model-api.test.ts` | PASS | 1 file, 8 tests passed; includes over-limit, changed-caveat, and 1,000 + 430 pagination cases |
| `npm --prefix frontend test` | PASS | 4 files, 30 tests passed |
| `npm --prefix frontend run lint` | PASS | ESLint completed with no findings |
| `npm --prefix frontend run typecheck` | PASS | TypeScript completed with no errors |
| `npm --prefix frontend run build` | PASS | Next production build completed; `/` remained dynamic |
| `uv run poe check` | PASS | Ruff format/lint and mypy passed; pytest `932 passed, 303 skipped` |
| WP3.2 focused mutation verification | PASS | `9 CAUGHT, 0 MISSED` for attribution, gate state, caveat, sample sizes, area mapping, provenance, duplicate paging, over-limit paging, and changed-caveat paging |
| WP3.2 full mutation verification (fresh final-head run) | PASS | Repository-pinned Python 3.12.11, four sequential shards, `290 CAUGHT, 0 MISSED, 0 SKIP`; every `BREAKS` index executed exactly once and mutation targets restored byte-exactly |
| Controlled local gate-closed API check | PASS | `/model` 200, `/model/metrics` 200, `/model/shots` 403 `publication_gate_closed`; no `/model/predict` request occurred |
| Controlled local gate-open pagination check | PASS | Local Docker DSN only; returned total `1,430`, pages `1,000 + 430`, 1,430 unique shots, stable seven-field provenance and stable caveat; no `/model/predict` request occurred |
| `git diff --check` | PASS | No whitespace errors in the final remediation diff |
| Responsive/manual browser inspection | PASS | Prior local Chrome inspection at 1440px, 1024px, and 390px covered the unchanged layout/map/reliability behavior; remediation changes were adapter invariants and status text only |

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
`uv run python`, which reported Python `3.12.11`, with `PYTHONHASHSEED=0`. The harness was loaded
with `runpy` under a non-`__main__` name, so `main()` was not invoked. After adding the two
legitimate WP3.2 pagination contracts, the authoritative population was `len(BREAKS) = 290`.

The earlier 288-entry run recorded in the prior closeout evidence predates the final remediation
implementation and is superseded historical evidence only. It is not included in the final totals.
The final run below was executed after all pagination, tests, status, contract, and evidence changes,
using the required local Docker PostgreSQL DSN and four deterministic sequential shards. No
parallel mutations were used.

Each shard called the existing `preflight()` and `check(BREAKS[index])` functions in order. The
wrapper asserted exact shard coverage and compared SHA-256 digests for every distinct mutation
target before and after the shard; all mutation targets restored byte-exactly. Final repository
status and `git diff --check` were also verified after the run.

| Shard | First contract | Last contract | Executed | CAUGHT | MISSED | SKIP | Result |
|---|---|---|---:|---:|---:|---:|---|
| `[0,72)` | WP2.1 model cohort must exclude Penalty shot types | quality reporting must preserve generic-event position missingness | 72 | 72 | 0 | 0 | PASS |
| `[72,144)` | quality reporting must preserve generic-event duration missingness | the refusal must name the target without printing the DSN | 72 | 72 | 0 | 0 | PASS |
| `[144,216)` | ingestion must consult the write-target guard before any work | WP2.6 CUDA qualification cannot publish a CUDA-derived selection | 72 | 72 | 0 | 0 | PASS |
| `[216,290)` | WP2.6 keeps artifact candidate distinct from the selection incumbent | WP3.1 Docker image contains the exact minimal serving bundle | 74 | 74 | 0 | 0 | PASS |
| **Aggregate** | — | — | **290** | **290** | **0** | **0** | **PASS** |

Exhaustive coverage is proven by the four non-overlapping ranges partitioning `[0,290)`, with each
wrapper asserting `executed == list(range(start, end))`: executed indices are exactly `0..289`,
unique executed index count is `290`, duplicate count is `0`, and missing count is `0`. The prior
system-Python attempt and the superseded 288-entry result are not included in any final total.

## Independent review remediation

The independent WP3.2 review of the previous immutable branch returned **FAIL**. It identified:

1. the claimed 288-entry exhaustive mutation run was recorded before the final implementation HEAD;
2. historical pagination did not reject a page whose row count exceeded its returned `limit`;
3. historical pagination did not require an identical `historical_prediction_caveat` on later pages; and
4. the local acceptance status was inconsistent across the analyst view, contract, evidence report,
   and `AGENTS.md`.

The remediation is now locally revalidated: the adapter rejects both malformed page cases, regression
coverage and two focused mutation contracts protect them, the final authoritative mutation population
passes at 290/290, and the status records distinguish local revalidation from the still-pending
independent review. This does **not** manufacture an independent-review `PASS`; the branch is ready
for independent re-review only.

## Responsive/manual browser inspection

**Result: PASS.** The current branch was inspected in local Chrome through the normal Next.js dev
server at representative viewport widths of **1440px**, **1024px**, and **390px**. The backend
used only the local Docker PostgreSQL target. No remote publication gate or production variable was
changed.

### Gate-closed production-like state

With `TOUCHLINE_HISTORICAL_MODEL_SHOTS_ENABLED=false`, `/model` and `/model/metrics` returned 200
and `/model/shots` returned the structured 403 `publication_gate_closed`. At all three widths, the
metadata identity, aggregate metrics, Euro2024 holdout reliability view, limitations, and visible
StatsBomb attribution remained usable. The page clearly showed `publication_gate_closed`, `NOT
CLEARED`, and the historical publication explanation; it did not show a zero-shot state. API logs
showed only `/model`, `/model/metrics`, and the gated `/model/shots` request—no legacy `/shots`
fallback and no `/model/predict` reconstruction.

### Controlled local gate-open state

A second local API process used the same Docker DSN with
`TOUCHLINE_HISTORICAL_MODEL_SHOTS_ENABLED=true`; this was never applied remotely. The two returned
pages were:

```text
limit=1000 offset=0:    total=1430, rows=1000
limit=1000 offset=1000: total=1430, rows=430
unique shot IDs: 1430
provenance identity: stable across metadata, metrics, and both pages
historical prediction caveat: stable across both pages
```

The controlled API check also confirmed no `/model/predict` reconstruction request. At each width the
interface rendered `showing 1430 of 1430`, 1,430 markers, and the selected shot workspace. Exact AND filtering was exercised with `team=Ecuador` and
`player=Romario Andrés Ibarra Mina`, producing the expected 2 rows. A deliberately empty exact
combination (`team=Ecuador` and `player=Abdelkarim Hassan Al Haj Fadlalla`) showed the explicit
“No shots match the current exact filters” state, disabled the selector, removed the markers, and
showed the empty detail state. Reset restored all 1,430 rows. Selecting a shot and then filtering
out its team repaired selection to the first remaining shot; the keyboard selector's `ArrowDown`
path moved selection, the map ring followed it, and the detail panel matched the selected shot's
player, outcome, probability, and caveat.

### Map, reliability, claims, and responsive result

The rendered map contained 152 filled goal markers and 1,278 hollow non-goal markers. Every marker's
`cx`/`cy` matched the API coordinates without jitter; the attacking-half viewBox was `60 0 60 80`
(the 60:80 StatsBomb coordinate-space ratio), and every rendered radius matched
`r(p) = sqrt(0.45² + p × (2.40² − 0.45²))`. The observed low/high radii increased from
`0.452875...` to `2.345938...`; one independent outer selection ring was present. The dense
central overlap area remained interpretable through the hollow/filled outcome encoding, opacity,
individual titles, and selection ring. The probability/outcome legend was readable.

The reliability view showed all five bins and both count columns, explicitly identified `n=4` and
`n=1`, rendered five unconnected points with zero connecting paths, reported the signed
`calibrated − raw` comparison, and kept the WC2022 calibration/adoption section separate from the
Euro2024 one-time tournament holdout. The historical calibration-data caveat remained beside the
workspace and selected-shot probability. “Data provided by StatsBomb”, “not StatsBomb's
proprietary xG model”, “Event data is not tracking”, and “No causal recommendation” were visible.

After the first inspection found two bounded defects, they were fixed and rechecked: reliability
content now permits a mobile-width internal table scroll without page-level horizontal overflow,
and SVG reliability tooltip text is a single node so hydration remains stable. The regression
assertion is in `frontend/components/HomeView.test.tsx`. Final browser runs reported no hydration
or page errors and no horizontal overflow at any requested width; controls, map, detail panel,
reliability table/chart, limitations, and attribution remained readable/usable.

Historical publication remains **NOT CLEARED**, and production deployment/smoke remains
**WP3.3–WP3.4**.

## Durable artifacts

- Contract: [`docs/interface/wp3_2-analyst-interface-contract.md`](../docs/interface/wp3_2-analyst-interface-contract.md)
- This evidence report: `reports/wp3.2-analyst-interface-evidence.md`
- Frontend model adapter: `frontend/lib/model-api.ts`
- Frontend view: `frontend/components/AnalystView.tsx`
- Frontend contract tests: `frontend/lib/model-api.test.ts`, `frontend/lib/model-view.test.ts`,
  `frontend/components/HomeView.test.tsx`

The historical publication gate remains unresolved, and no production deployment or smoke result is
implied by these local checks.
