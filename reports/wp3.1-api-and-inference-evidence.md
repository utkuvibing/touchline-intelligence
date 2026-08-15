# WP3.1 API and inference evidence

**Implementation status:** complete for this iteration

**Serving-bundle status:** validated locally and in the production Docker image

**Public historical-prediction gate:** closed by default

**Review:** manually approved by the project author for this iteration; no independent Sol review
ran and no independent-review `PASS` is claimed

This report records the stabilized WP3.1 implementation against
[`docs/serving/wp3_1-api-and-inference-contract.md`](../docs/serving/wp3_1-api-and-inference-contract.md)
and [ADR 0015](../docs/adr/0015-wp3-1-serving-bundle-and-startup-semantics.md). It does not claim a
public deployment. No qualified WP2.x artifact or evidence file was modified.

## Qualified source and minimal bundle

The runtime serves only `exp-20260810-wp2_8-release`. The minimal bundle is committed under
`backend/model-release/exp-20260810-wp2_8-release/` and contains exactly:

| File | Role |
|---|---|
| `serving-manifest.json` | M3 package membership and parent-release link |
| `wp2_8-release-manifest.json` | qualified WP2.8 scientific release identity |
| `model.pkl` | selected WP2.4 logistic artifact |
| `artifact-manifest.json` | frozen artifact/feature contract |
| `calibration-decision.json` | adopted WC2022 Platt decision |
| `holdout-metrics.json` | immutable qualified WC2022/Euro2024 evidence source |

The copied source members remain byte-identical to their qualified originals:

| Material | SHA-256 |
|---|---|
| Serving-manifest content | `68cee3ab4f06c280421f848de36d59b3db39d8c3ea7ece7765a4ba29e3a7ae5c` |
| WP2.8 release-manifest file | `5c2e4016291c6ebe99ba69b37884f38791b4b6b1440c81107ed2a44db95645d4` |
| WP2.8 release-manifest content | `bad64e5972938335e62b98d694f24961117e5f46034518f38b61209e2c3ca87d` |
| Model pickle | `9aeac9468c00bd1b93c771e454e48ca29e2eb759cf71836182a782d674bfadca` |
| Artifact manifest | `62cade6c3db5d741039de8f1ad53010319f422dcb942c96f16f1db8a498e8e79` |
| Calibration-decision file | `a88255ca56b478372ec76bc9dddb3295d9073a7f180d5dc8f0d9fa34bfd65d87` |
| Calibration decision content | `f5c9ccf665924069f755fbd669d4a9abada1e5791e957d3d436d42d500277e89` |
| Holdout metrics | `3443b4a5e19fd87b1ee599502152a7dcfe1af3d8466c09ad7cbf2bb8cae2e674` |

The image does not contain `/app/artifacts` or `/app/experiments`. Runtime loading uses the fixed
path `/app/backend/model-release/exp-20260810-wp2_8-release`; there is no configurable or
request-controlled model path.

## Fail-fast initialization

`ModelRuntime.load` verifies, before returning a runtime:

- exact file allow-list, including rejection of extra directories;
- serving-manifest content identity and schema;
- every member's file hash and canonical relative path;
- fixed WP2.8 release file/content identities and release state;
- cross-agreement between serving members and WP2.8 authoritative inputs;
- trusted pickle type/schema after hash verification;
- artifact manifest, scaler, vocabulary, rare/reference mappings, selected columns/indices,
  estimator feature count, column order, and finite estimator state;
- calibration decision identity, selected base identity, adopted variant, finite positive slope,
  finite intercept, and Platt-parameter digest; and
- holdout evidence identity, count anchors, decision identity, and reliability membership totals.

FastAPI lifespan constructs this runtime before startup completes. Missing, corrupt, unexpected, or
unsupported material raises a typed startup error and does not produce a degraded running model.
Controlled source-tree tests cover missing and corrupt model members, self-inconsistent serving
manifests, unsupported serving schema, unexpected files/directories, incompatible selected-column
ordering, and a self-consistent serving member that disagrees with the qualified WP2.8 release. The
actual Linux production image separately proves missing, corrupt, and unsupported-schema bundles all
fail runtime initialization.

## Runtime and HTTP surface

The runtime is the only owner of feature geometry, frozen encoding/order, estimator inference, base
logit generation, adopted Platt transformation, probability bounds, curated evidence, and model
provenance. FastAPI routes do not call the encoder, estimator, or calibration arithmetic.

Implemented endpoints are:

```text
GET  /model
GET  /model/metrics
POST /model/predict
GET  /model/shots
```

Every successful model-aware response includes `model_version`, `release_id`,
`serving_manifest_sha256`, both source release-manifest identities, `artifact_sha256`, and
`calibration_decision_sha256`. Public prediction output contains only the calibrated probability
and provenance; raw probability, logit, feature vectors, coefficients, and debug state are absent.

Structured errors distinguish model body validation, input compatibility, query filters, the
publication gate, runtime readiness, and database availability. Request validation is scoped to
`/model` routes; legacy `/shots` retains FastAPI's pre-WP3.1 `{"detail": ...}` validation shape.
Deterministic bundle corruption remains a startup exception rather than an HTTP error. Model-aware
requests reuse the lifespan singleton, and a regression test makes any per-request artifact reload
fail visibly.

ADR 0015's intentional readiness change is implemented: `/ready` returns HTTP 200 only when the
model runtime, database, and required schema are ready; a genuine degraded runtime dependency
returns HTTP 503. `/health` remains process-only liveness.

## Split and evidence semantics

The API keeps the three roles explicit:

| Scope | Role |
|---|---|
| WC2018 + Euro2020 | model development |
| WC2022 | Platt calibration and adoption |
| Euro2024 | one-time tournament holdout |

`GET /model/metrics` curates existing immutable files and performs no database evidence query or
metric recomputation; a focused test makes any PostgreSQL connection from that endpoint fail. Its
WC2022 adoption section comes from `calibration-decision.json`. Its
Euro2024 scores and reliability come from `holdout-metrics.json`. The legacy top-level
`raw_anchor_reliability` is correctly treated as 1,430-row WC2022 calibration provenance; actual
Euro2024 reliability comes from the 1,304-row `variants.calibrated.reliability` table.

`GET /model/shots` labels WC2022 rows as calibration-data historical predictions and states that
they are not an untouched final holdout. Recorded outcomes are response facts and are absent from
runtime inference inputs.

## Independent WP2 oracle parity

`scripts/write_wp3_1_golden_cases.py` imports no WP3.1 serving module. It verifies the canonical
WP2 model and calibration identities, then generates expected geometry, selected vectors, logits,
base probabilities, and calibrated probabilities through the qualified WP2 preprocessing and
inference path. Its frozen fixture is
`backend/tests/fixtures/wp3_1_golden_cases.json`, SHA-256
`fc030dcdaad6cb3ad5279605fd1cef23deb3469f799506351298c482335c2e66`.

The primary qualified oracle result is:

```text
request: (112, 40), Right Foot, Normal, Regular Play
base logit: -0.9272702580316936
base probability: 0.28347884798573286
calibrated probability: 0.3912322351084872
```

WP3.1 matches the frozen calibrated probabilities at absolute tolerance `1e-12`. Cases cover
reference, retained, development-rare, unseen, literal `"rare"` as external unseen/reference, and
goal-line geometry. The same parity passed inside the Linux production image. Exact goalposts,
out-of-range and non-finite coordinates, and blank categoricals are rejected.

## Historical query and publication gate

Historical rows are the intersection of the WP2.1 eligible-shot contract and the fixed WC2022
public scope. Filters are parameterized, scalar, exact, bounded, and combined with `AND`. Count and
page queries execute in one read-only transaction under the total order:

```text
match_date, match_id, period, minute, second, event_index, shot_id
```

The fixture integration proof catches removal of WC2022 scope, penalty exclusion, deterministic
ordering including the final shot-ID tie-breaker, and read-only enforcement. It also proves filtered
totals and one batch-inference call for the page, with no outcome field in inference inputs. Unknown
query keys—including `sort`, `fields`, and arbitrary names—fail against the exact allow-list with
structured HTTP 422 `invalid_filter` responses.

`TOUCHLINE_HISTORICAL_MODEL_SHOTS_ENABLED` defaults to `false`. A closed gate returns structured
HTTP 403 without querying PostgreSQL. This implementation does not clear the existing StatsBomb/Hudl
publication question and does not silently enable row-level model probabilities in production.

## Verification results

Commands were run after stabilization:

| Check | Result |
|---|---|
| Focused WP3.1 unit/API/ops tests | PASS |
| WP3.1 PostgreSQL fixture integration | 6 passed |
| `uv run poe check` | 932 passed, 303 skipped; format, lint and strict mypy passed |
| Full mutation verification | 284 CAUGHT, 0 MISSED, 0 SKIP; all files restored |
| WP3.1 mutation additions | 20 CAUGHT |
| `uv run python scripts/verify_wp3_1_docker.py` | PASS |
| Linux-image canonical golden prediction | matched `0.3912322351084872` at absolute tolerance `1e-12` |
| Docker missing/corrupt/unsupported-schema probes | expected initialization failures observed |
| `git diff --check` | PASS |

The 302 ordinary-suite skips are declared environment-specific full-source/full-cohort and CUDA
contracts. The full mutation run was executed separately with both database variables pointing at
the local 230-match cohort, so none of its protected contracts skipped.

## Limitations and open gates

- No deployed URL was changed or smoke-tested in WP3.1 evidence; README distinguishes the
  implemented repository API from the still-descriptive live API and UI.
- Historical row-level probabilities remain publication-disabled by default.
- Offset order is deterministic for one database state. Cross-request page stability assumes the
  pinned, idempotently loaded snapshot remains unchanged; it is not claimed across source revisions,
  rebuilds, or manual mutation.
- Unknown exact categorical strings use the frozen all-zero reference encoding. There is no case
  folding, trimming, aliasing, or typo correction; literal `"rare"` follows the same external-unseen
  behavior.
- The serving bundle duplicates only required immutable release bytes; the qualified originals
  remain authoritative and unchanged.
- The project author manually approved the review gate for this iteration after the stabilized diff
  and evidence were prepared. This is a manual approval, not an independent Sol review, and is not
  recorded as an independent-review `PASS`.

Data provided by StatsBomb.
