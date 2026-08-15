# WP3.1 API and inference contract

**Status:** accepted and implemented for WP3.1. The project author manually approved the review
gate for this iteration; no independent Sol review ran and no independent-review `PASS` is claimed.

**Owner:** M3 analyst interface and serving. **Decision record:**
[ADR 0015](../adr/0015-wp3-1-serving-bundle-and-startup-semantics.md).

## 1. Scope and qualified source release

WP3.1 serves exactly the qualified WP2.8 release `exp-20260810-wp2_8-release`. It does not select,
fit, refit, retrain, recalibrate, or substitute a model. The source release remains
`release_status = "m2_qualified"` and `serving_status = "not_served"`; the latter is the historical
state recorded when M2 closed and is not rewritten. A successfully initialized M3 runtime reports
its separate runtime state.

The selected base is the WP2.4 `full_minus_presence` regularized logistic artifact fitted on the
2,872-shot, 115-match development population (WC2018 + Euro2020). The adopted Platt transform was
fitted on 1,430 WC2022 shots in 64 matches. Euro2024 is the one-time tournament holdout: 1,304 shots,
51 matches and 98 goals. WC2022 is calibration data, not an untouched final holdout.

Canonical source identities are:

| Material | SHA-256 |
|---|---|
| WP2.8 release-manifest file | `5c2e4016291c6ebe99ba69b37884f38791b4b6b1440c81107ed2a44db95645d4` |
| WP2.8 manifest content identity | `bad64e5972938335e62b98d694f24961117e5f46034518f38b61209e2c3ca87d` |
| WP2.4 model pickle | `9aeac9468c00bd1b93c771e454e48ca29e2eb759cf71836182a782d674bfadca` |
| WP2.4 artifact manifest | `62cade6c3db5d741039de8f1ad53010319f422dcb942c96f16f1db8a498e8e79` |
| WP2.7 calibration-decision file | `a88255ca56b478372ec76bc9dddb3295d9073a7f180d5dc8f0d9fa34bfd65d87` |
| WP2.7 calibration decision identity | `f5c9ccf665924069f755fbd669d4a9abada1e5791e957d3d436d42d500277e89` |
| WP2.7 holdout metrics | `3443b4a5e19fd87b1ee599502152a7dcfe1af3d8466c09ad7cbf2bb8cae2e674` |

WP3.1 ships four model-aware endpoints:

```text
GET  /model
GET  /model/metrics
GET  /model/shots
POST /model/predict
```

It does not expose arbitrary model paths, SQL, sorting, output-field selection, raw logits, base
probabilities, encoded features, coefficients, or debugging representations. It does not recompute
qualified evidence from PostgreSQL. Authentication, request IDs, drift monitoring, deployment
automation, UI work, and public enablement of unresolved row-level publication rights are outside
this work package.

## 2. Common provenance

Every successful model-aware response carries these top-level fields:

```text
model_version: string
release_id: string
serving_manifest_sha256: string
release_manifest_sha256: string
release_manifest_file_sha256: string
artifact_sha256: string
calibration_decision_sha256: string
```

`model_version` and `release_id` are both `exp-20260810-wp2_8-release`; no new scientific model
identity is invented. `serving_manifest_sha256` identifies the exact deployed M3 bundle separately
from the parent WP2.8 release. `release_manifest_sha256` is the WP2.8 manifest's content identity;
`release_manifest_file_sha256` identifies its exact serialized bytes. All values come from the
validated serving and source manifests, never from unrelated reconstruction at request time.

## 3. Endpoint schemas

### 3.1 `GET /model`

```text
{
  model_version: string,
  release_id: string,
  serving_manifest_sha256: string,
  release_manifest_sha256: string,
  release_manifest_file_sha256: string,
  artifact_sha256: string,
  calibration_decision_sha256: string,
  release_status: "m2_qualified",
  qualification_serving_status: "not_served",
  runtime_status: "ready",
  candidate: "full_minus_presence",
  estimator: "logistic_regression",
  calibration: "platt_sigmoid",
  adopted_variant: "calibrated",
  output: "goal_conversion_probability",
  scopes: {
    development: {
      competitions: ["FIFA World Cup 2018", "UEFA Euro 2020"],
      shots: 2872,
      matches: 115,
      role: "model_development"
    },
    calibration: {
      competition: "FIFA World Cup 2022",
      shots: 1430,
      matches: 64,
      role: "platt_calibration_and_adoption"
    },
    tournament_holdout: {
      competition: "UEFA Euro 2024",
      shots: 1304,
      matches: 51,
      role: "one_time_final_evaluation"
    }
  },
  input_contract: {
    coordinates: {
      system: "StatsBomb",
      location_x: {minimum: 0.0, maximum: 120.0},
      location_y: {minimum: 0.0, maximum: 80.0}
    },
    categorical_policy: "exact_frozen_vocabulary_with_unseen_as_reference",
    fields: {
      body_part: {
        reference: "Right Foot",
        retained: ["Head", "Left Foot"],
        rare_members: ["Other"]
      },
      technique: {
        reference: "Normal",
        retained: ["Half Volley", "Volley"],
        rare_members: ["Backheel", "Diving Header", "Lob", "Overhead Kick"]
      },
      play_pattern: {
        reference: "Regular Play",
        retained: ["From Corner", "From Counter", "From Free Kick",
                   "From Goal Kick", "From Keeper", "From Kick Off", "From Throw In"],
        rare_members: ["Other"]
      }
    }
  }
}
```

`qualification_serving_status` preserves the immutable M2 release statement. `runtime_status`
describes the M3 process after successful serving-bundle initialization.

### 3.2 `POST /model/predict`

The request is exactly:

```text
{
  location_x: number,
  location_y: number,
  body_part: string,
  technique: string,
  play_pattern: string
}
```

Extra fields are forbidden. The response is:

```text
{
  model_version: string,
  release_id: string,
  serving_manifest_sha256: string,
  release_manifest_sha256: string,
  release_manifest_file_sha256: string,
  artifact_sha256: string,
  calibration_decision_sha256: string,
  calibrated_probability: number
}
```

The probability must be finite and in `[0, 1]`. Raw/base probability, base logit, geometry,
encoded features, category mappings, coefficients, and debug state are not public fields.

### 3.3 `GET /model/metrics`

```text
{
  model_version: string,
  release_id: string,
  serving_manifest_sha256: string,
  release_manifest_sha256: string,
  release_manifest_file_sha256: string,
  artifact_sha256: string,
  calibration_decision_sha256: string,
  evidence_source: {
    holdout_metrics_sha256: string,
    evidence_status: "qualified_m2_evidence",
    recomputed_at_request_time: false
  },
  calibration_adoption: {
    split: "FIFA World Cup 2022",
    role: "calibration",
    shots: 1430,
    matches: 64,
    adopted_variant: "calibrated",
    supported_raw_anchor_bins: 1,
    raw: {
      log_loss: number,
      brier: number,
      max_supported_calibration_deviation: number
    },
    calibrated: {
      log_loss: number,
      brier: number,
      max_supported_calibration_deviation: number
    },
    raw_anchor_reliability: [{
      bin: integer,
      lower: number,
      upper: number,
      count: integer,
      positive_count: integer,
      raw_mean_prediction: number | null,
      calibrated_mean_prediction: number | null,
      observed_rate: number | null
    }]
  },
  tournament_holdout: {
    split: "UEFA Euro 2024",
    role: "one_time_tournament_holdout",
    shots: 1304,
    matches: 51,
    goals: 98,
    observed_prevalence: number,
    adopted_variant: "calibrated",
    proper_scoring: {log_loss: number, brier: number},
    discrimination: {roc_auc: number, pr_auc: number},
    uncertainty: {
      method: "match_clustered_paired_bootstrap",
      confidence_level: 0.95,
      repetitions: 2000,
      seed: 0,
      log_loss: {lower: number, upper: number},
      brier: {lower: number, upper: number}
    },
    reliability: [{
      bin: integer,
      lower: number,
      upper: number,
      count: integer,
      positive_count: integer,
      mean_prediction: number | null,
      observed_rate: number | null
    }],
    raw_comparator: {
      proper_scoring: {log_loss: number, brier: number},
      discrimination: {roc_auc: number, pr_auc: number},
      calibrated_minus_raw: {
        log_loss: number,
        brier: number,
        log_loss_interval: {lower: number, upper: number},
        brier_interval: {lower: number, upper: number}
      }
    }
  }
}
```

The calibration section is curated from the validated immutable `calibration-decision.json`. The
holdout section is curated from the validated immutable `holdout-metrics.json`. The endpoint never
retrains, recalibrates, queries the database for evidence, or dumps the internal experiment schema.

The legacy top-level `raw_anchor_reliability` field in WP2.7 holdout metrics totals 1,430 rows and is
WC2022 calibration provenance. It must not be labelled as Euro2024 reliability. Euro2024 reliability
comes only from `variants.raw.reliability` and `variants.calibrated.reliability`, each over 1,304
rows.

### 3.4 `GET /model/shots`

```text
{
  model_version: string,
  release_id: string,
  serving_manifest_sha256: string,
  release_manifest_sha256: string,
  release_manifest_file_sha256: string,
  artifact_sha256: string,
  calibration_decision_sha256: string,
  cohort: "FIFA World Cup 2022 eligible non-penalty shots",
  split_role: "calibration_data_historical_predictions",
  historical_prediction_caveat: string,
  shots: [{
    shot_id: string,
    match_id: integer,
    match_date: string | null,
    competition_stage: string | null,
    team: string,
    opponent: string,
    player: string,
    period: integer,
    minute: integer | null,
    second: integer | null,
    location_x: number,
    location_y: number,
    outcome: string,
    shot_type: string,
    body_part: string,
    technique: string,
    play_pattern: string,
    calibrated_probability: number
  }],
  total: integer,
  limit: integer,
  offset: integer
}
```

The caveat states that WC2022 labels fitted and selected the Platt transform. These are historical
calibrated estimates over calibration data, not predictions from an untouched final holdout.
Recorded outcomes may be returned under the existing WC2022 public-data contract, but they are
response-only facts and never enter model inputs.

## 4. Prediction validation

### Coordinates

Coordinates must be JSON numbers (integer or floating point), not strings or booleans. They must be
finite and present. Public hypothetical input accepts inclusive StatsBomb bounds
`0 <= location_x <= 120` and `0 <= location_y <= 80`; it performs no clipping or normalization.

Exact goalpost locations `(120, 36)` and `(120, 44)` are rejected because visible angle is
undefined. Goal-line points strictly between the posts are accepted and produce angle `pi`; points
outside the posts are accepted and produce angle `0`; `(120, 40)` is accepted and has zero distance.
The frozen source-only adjustment for the one measured `location_x = 120.1` row is not a public
hypothetical-input allowance, so requests above `120` are rejected.

### Categoricals

Categoricals must be present, non-null, non-empty strings; whitespace-only strings are invalid. The
API performs no trimming, case folding, fuzzy matching, or aliases. Exact retained levels use their
frozen columns and exact frozen rare members use the frozen rare column.

Every other non-empty string is an unseen value and follows the qualified M2 policy: all-zero
reference encoding. This includes the literal string `"rare"`. Frozen M2 evidence does not establish
`"rare"` as a reserved invalid external value, so WP3.1 must not reject it specially. A value such
as `"head"` or `"Head "` is likewise unseen rather than an alias. This behavior is intentionally
strict and may make typographical errors look like future levels, but changing it would make serving
differ from the frozen preprocessing contract.

Post-shot outcome, provider xG, shot end location, and every unneeded provider field are forbidden by
the request model's exact field set.

## 5. Minimal immutable serving bundle

The planned source and image layout is:

```text
backend/model-release/
└── exp-20260810-wp2_8-release/
    ├── serving-manifest.json
    ├── wp2_8-release-manifest.json
    ├── model.pkl
    ├── artifact-manifest.json
    ├── calibration-decision.json
    └── holdout-metrics.json
```

The trusted runtime path is fixed at:

```text
/app/backend/model-release/exp-20260810-wp2_8-release
```

No environment variable or request may select another model path. A future release requires an
explicit code and manifest change.

The WP2.8 release manifest references historical reproduction and audit evidence that is important
to qualification but unnecessary for inference. Copying all referenced experiment trees would
violate the minimal-image requirement. The separate immutable `serving-manifest.json` therefore
identifies the parent WP2.8 release and references only the serving files above:

```text
{
  serving_manifest_sha256: string,
  serving_bundle: {
    schema_version: 1,
    bundle_id: "exp-20260810-wp2_8-release",
    source_release_id: "exp-20260810-wp2_8-release",
    source_release_manifest_sha256: "bad64e...",
    source_release_manifest_file_sha256: "5c2e40...",
    files: {
      release_manifest: {path: string, sha256: string},
      model: {path: string, sha256: string},
      artifact_manifest: {path: string, sha256: string},
      calibration_decision: {path: string, sha256: string},
      holdout_metrics: {path: string, sha256: string}
    }
  }
}
```

`serving_manifest_sha256` hashes canonical `serving_bundle` content. The source WP2.8 release
manifest remains authoritative for scientific identity; the serving manifest records only package
membership and its exact source-release link.

Training configs, WP2.4 coefficient/metrics files, WP2.7 audit and experiment record, plots, reports,
WP2.8 reproduction material, challenger artifacts, source data, and the rest of `artifacts/` are
excluded from the image.

## 6. Startup and readiness semantics

Before FastAPI startup completes, the runtime:

1. locates the one fixed bundle;
2. requires the exact file allow-list and rejects path traversal, missing, or unexpected members;
3. verifies the serving-manifest content digest and supported schema;
4. hashes every referenced member;
5. verifies the WP2.8 release-manifest file and content hashes, release ID,
   `m2_qualified`/`not_served` states, and no-new-holdout-access record;
6. cross-checks member hashes against WP2.8 authoritative inputs;
7. validates the artifact manifest, then unpickles only the already hash-verified trusted model;
8. validates artifact class/schema, estimator feature count, scaler, vocabulary, rare/reference
   mappings, columns, selected indices, and feature order;
9. validates the calibration decision file/content identities, base identity, adopted variant,
   finite positive slope, finite intercept, and Platt-parameter digest;
10. validates holdout metrics identity/schema, candidate, decision identity, count anchors, and
    reliability totals;
11. constructs immutable metadata and metrics views and one runtime instance; and
12. attaches that instance before startup completes.

A missing file, hash mismatch, malformed or unsupported schema, incompatible artifact, invalid
preprocessing contract, invalid decision, or invalid evidence aborts application startup. The
application must not successfully start with deterministic corruption and must not turn such
corruption into a recoverable HTTP 503 path.

`/health` remains process liveness and does not touch PostgreSQL or reload the model. `/ready`
becomes:

```text
{
  status: "ready" | "degraded",
  database: "reachable" | "unreachable",
  database_schema: "current" | "behind" | "unknown",
  model_runtime: "ready" | "not_ready",
  model_version: string | null,
  detail: string | null
}
```

It returns HTTP 200 only when database, schema, and model runtime are ready. It returns HTTP 503 for
a genuine runtime readiness failure, including database/schema unavailability or an unexpected
post-start absence of initialized runtime state. FastAPI does not normally accept traffic before
lifespan startup completes, so a valid production process should not expose an initialization race.
The current behavior—HTTP 200 with a degraded body—is intentionally superseded by WP3.1. ADR 0015
records this operational contract change.

## 7. Runtime interface and ownership

The runtime presents one interface:

```python
runtime.metadata()
runtime.metrics()
runtime.predict(input)
runtime.predict_historical(rows)
```

It is the single owner of bundle loading, manifests and hashes, frozen preprocessing, geometry,
categorical encoding, feature order, base-logit generation, adopted Platt transform, probability
bounds, curated evidence, and provenance. FastAPI owns HTTP schemas, request/filter validation,
routing, database query handling, the publication gate, and stable translation of known domain
errors. Endpoint code must not call the encoder, estimator, or calibration arithmetic directly.

## 8. Historical-query contract

The endpoint is the exact intersection of the WP2.1 eligible-shot cohort and the named WC2022 public
scope (`competition_id = 43`, `season_id = 106`): non-penalty, non-period-5 shots with required
player, location, outcome, body part, technique, and shot type. The expected unfiltered count is
1,430.

Supported filters are scalar and combine with `AND`:

```text
match_id: positive integer
team: exact non-empty string, maximum 200 characters
player: exact non-empty string, maximum 200 characters
outcome: exact non-empty string, maximum 100 characters
body_part: exact non-empty string, maximum 100 characters
technique: exact non-empty string, maximum 100 characters
play_pattern: exact non-empty string, maximum 100 characters
limit: integer, default 200, range 1..1000
offset: integer, default 0, minimum 0
```

Repeated scalar parameters, wildcards, aliases, partial matching, arbitrary sorting, SQL, or output
selection are rejected. Unknown exact filter values return an empty page.

The fixed order is:

```text
match_date ASC,
match_id ASC,
period ASC,
minute ASC,
second ASC,
event_index ASC,
shot_id ASC
```

`shot_id` is the unique final tie-breaker. This guarantees deterministic ordering for one database
state. Cross-request offset stability additionally depends on that underlying state remaining
unchanged. Repository evidence supports that assumption for the intended snapshot: the source is
pinned to StatsBomb commit `b0bc9f22dd77c206ddedc1d742893b3bbe64baec`, WP1.3 ingestion is
idempotent and reject-on-change, and the public scope names one fixed competition-season. The
endpoint does not claim stability across a database rebuild, source revision, manual mutation, or
future dataset release; such a change can shift offset pages even though ordering remains
deterministic.

Count and row queries run in one read-only transaction. One bounded page is materialized and passed
to one batch `predict_historical` call. Outcomes remain response facts and are excluded from runtime
input. Artifact reloads, N+1 database access, and per-row estimator initialization are prohibited.

## 9. Publication gate

The current source review says not to expand published row-level output until StatsBomb/Hudl gives
current written direction. Adding a model probability to a public WC2022 row may be such an
expansion even without expanding tournament coverage.

WP3.1 therefore plans a typed historical-model-shots enablement setting that defaults to false.
When closed, `/model/shots` returns HTTP 403 `publication_gate_closed`. Local controlled acceptance
may enable it; production must not do so until the existing release gate is cleared and recorded.
Aggregate qualified metrics and hypothetical prediction do not publish source rows, but attribution
remains mandatory.

## 10. Errors

HTTP-returnable errors use:

```text
{
  error: {
    code: string,
    message: string,
    details: [{field: string | null, code: string, message: string}]
  }
}
```

| HTTP | Code | Meaning |
|---:|---|---|
| 422 | `request_validation_error` | Missing, extra, wrong-type, non-finite, or invalid body field |
| 422 | `input_compatibility_error` | Geometry is undefined for an otherwise typed input |
| 422 | `invalid_filter` | Invalid/repeated query filter or pagination parameter |
| 403 | `publication_gate_closed` | Historical row-level model output is not publicly enabled |
| 503 | `runtime_not_ready` | A started process genuinely lacks ready runtime state |
| 503 | `data_unavailable` | PostgreSQL/schema cannot serve historical rows |

Startup failures have stable internal codes—`serving_bundle_missing`,
`serving_bundle_hash_mismatch`, `release_manifest_invalid`, `release_schema_unsupported`,
`artifact_incompatible`, `preprocessing_contract_invalid`, `calibration_decision_invalid`, and
`metrics_evidence_invalid`—but no HTTP representation because startup fails. Logs must not disclose
DSNs, credentials, or untrusted pickle details.

## 11. Golden M2-to-M3 parity

The golden oracle must be independent of the new WP3.1 runtime. Expected values are generated once
through the already-qualified WP2 preprocessing/inference path using the canonical WP2.8 artifact
and WP2.7 calibration decision. The generated fixture records those source hashes and is frozen
before WP3.1 runtime assertions are written. WP3.1 then consumes raw requests and is compared to the
frozen oracle; it must not generate its own expectations.

The primary request is:

```json
{
  "location_x": 112.0,
  "location_y": 40.0,
  "body_part": "Right Foot",
  "technique": "Normal",
  "play_pattern": "Regular Play"
}
```

The qualified WP2 path gives:

```text
distance_to_goal = 8.0
visible_goal_angle = 0.9272952180016122
base_logit = -0.9272702580316936
base_probability = 0.28347884798573286
calibrated_probability = 0.3912322351084872
```

The internal frozen fixture also records the exact selected 16-column feature order/vector; these
internals are test evidence, not response fields. Additional oracle cases cover retained levels,
rare-member mapping, unseen-reference mapping (including literal `"rare"`), mirrored geometry, and
valid goal-line geometry.

Hashes, identities, column names/order, and categorical indicators compare exactly. Derived floats,
logits, and probabilities use an absolute tolerance of `1e-12`, which must be confirmed in the Linux
Docker image rather than assumed from the Windows qualification machine. Negative cases cover
missing/corrupt members, unsupported schemas, column/index mismatch, decision mismatch, invalid
Platt state, non-finite/out-of-bounds coordinates, exact goalposts, and missing/null categoricals.

## 12. Docker, tests, evidence, and completion

The real Docker image must contain the exact minimal bundle and no unrelated experiment or model
artifacts. Acceptance builds and inspects the image, starts the runtime from packaged files, verifies
provenance and the golden prediction, and proves controlled missing/corrupt/unsupported bundles fail
startup rather than producing a degraded successful process. Source-tree tests alone do not satisfy
this gate.

Unit and integration tests cover every bundle-validation stage, lifespan single initialization,
response schemas, readiness codes, metric semantics, categorical and coordinate rules, historical
cohort/filter/order/read-only behavior, one batch inference per page, and the default-closed
publication gate. Mutation contracts must catch removal of release/artifact hashes, schema checks,
feature order, calibration, probability bounds, public/cohort predicates, penalty exclusion,
deterministic tie-breakers, read-only enforcement, one-time artifact loading, immutable metric
sources, publication default, and Docker bundle inclusion.

Planned durable outputs are:

```text
docs/serving/wp3_1-api-and-inference-contract.md
docs/adr/0015-wp3-1-serving-bundle-and-startup-semantics.md
reports/wp3.1-api-and-inference-evidence.md
backend/tests/fixtures/wp3_1_golden_cases.json
backend/model-release/exp-20260810-wp2_8-release/
```

The implemented order was: bundle assembly and validator; independent WP2 golden-fixture
generation; runtime; lifespan/readiness; structured errors; metadata; curated metrics; hypothetical
prediction; publication-gated historical query; Docker acceptance; mutation verification; and
evidence. The project author manually approved the review gate for this iteration after those checks;
that approval is not represented as an independent Sol review.
