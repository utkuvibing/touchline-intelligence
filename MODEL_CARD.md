# Touchline Intelligence Shot Quality Model Card

**Canonical M2 model card**  
**Release status:** `m2_qualified`  
**Serving status:** `not_served`  
**Released model:** development-fitted `full_minus_presence` regularized logistic regression with
the pre-holdout-adopted WC2022 Platt transform  
**Release packet:** `exp-20260810-wp2_8-release`

This is the current model card for the completed M2 shot-quality lifecycle. The shorter
[WP2.7 model card](reports/wp2.7-model-card.md) and
[WP2.7 closeout card](reports/wp2.7-model-card-closeout.md) remain unchanged as historical records
of the calibration and one-time-holdout stage.

## What is this model?

Touchline Intelligence's Shot Quality Model estimates the probability that an **eligible recorded
shot** is converted into a goal. Here, eligible means a non-penalty StatsBomb Shot event that meets
the fixed cohort contract. The output is a probability, not a yes/no football decision, a causal
estimate, or a statement of certainty about an individual shot.

This is **Touchline Intelligence's model, not StatsBomb's xG model**. Provider xG is removed before
data reaches the typed database and is never an input. The model uses location-derived geometry and
a small set of categorical descriptors available at the shot.

The final estimator is intentionally modest. Its strength is the lifecycle around it: a pinned
source snapshot, explicit leakage boundary, locked tournament splits, progressively more complex
challengers, a calibration decision made before final evaluation, one supervised holdout access,
and an environment-scoped byte-identical release reproduction.

### Status in plain English

| Question | Answer |
|---|---|
| What does it return? | An estimated probability that an eligible shot becomes a goal. |
| What is the base model? | L2-regularized logistic regression, candidate `full_minus_presence`, fitted on WC2018 + Euro2020. |
| Is it calibrated? | Yes. A Platt transform fitted on WC2022 was adopted under a rule frozen before Euro2024. |
| What was the final evaluation? | One predeclared evaluation on the Euro2024 tournament holdout. |
| Is it in the public API or UI? | No. M2 qualified the release; M3 owns serving. |
| Is it StatsBomb xG? | No. StatsBomb supplies the event data; provider xG is excluded. |

## Intended use and non-goals

Appropriate uses include:

- football analytics research and exploratory shot-quality analysis;
- analyst or product decision support, with the limitations below kept visible;
- comparing aggregate shot profiles where sample size and competition context are reported;
- demonstrating a reproducible applied-ML and model-release workflow.

The evidence does **not** establish the model for:

- causal evaluation of players, teams, or tactics;
- universal calibration across leagues, tournaments, seasons, or providers;
- replacing scouting, coaching, or domain judgement;
- treating an individual probability as certainty or as a prescribed decision threshold;
- claiming equivalence to StatsBomb's proprietary or any commercial xG model;
- production inference. The current release is qualified but not served.

## How to read the evidence

This card keeps four kinds of statement separate:

- **Measured fact** — a value in an immutable experiment artifact or measured report.
- **Registered decision** — a rule fixed before the relevant outcomes were used.
- **Engineering interpretation** — an explanation consistent with the evidence, but not itself a
  measured result.
- **Limitation or future work** — a boundary the current evidence does not cross.

Every material quantitative claim links to the evidence that owns it. JSON experiment artifacts,
not rounded prose in this card, remain the source of truth for exact machine values.

## Model at a glance

| Item | Specification |
|---|---|
| Target | `1` when an eligible Shot's recorded outcome is Goal; `0` otherwise |
| Base estimator | scikit-learn logistic regression, L2 regularization, `lbfgs`, `C = 0.1` |
| Base fit scope | 2,872 shots in 115 matches: WC2018 + Euro2020 only |
| Base features | 16 columns: two standardized geometry features and 14 categorical indicators |
| Calibration | `sigmoid(1.256307409023587 × base_logit + 0.7228009741380947)` |
| Calibration fit scope | 1,430 shots in 64 WC2022 matches only |
| Final holdout | 1,304 shots in 51 Euro2024 matches; 98 goals and 1,206 misses |
| Final adopted variant | `calibrated`, decided before Euro2024 was opened |
| Release state | `m2_qualified`; `not_served` |

The fitted logistic coefficients describe associations conditional on this feature space. L2
regularization shrinks them toward zero, and neither their signs nor magnitudes are causal effects.

## Data and locked evaluation design

The source is StatsBomb Open Data pinned to commit
`b0bc9f22dd77c206ddedc1d742893b3bbe64baec`. The fixed four-tournament cohort contains 5,606
eligible non-penalty shots and 507 goals. Regulation and shootout penalties, own-goal events, and
rows with unknown required fields are outside the modeled population. Post-shot information is
excluded from the feature space. The exact reconciliation is in the
[WP2.1 report](reports/wp2.1-cohort-reconciliation.md).

### Three splits with different permissions

| Split | Tournament(s) | Matches | Shots | Permitted role | Prohibited role |
|---|---|---:|---:|---|---|
| Development | WC2018 + Euro2020 | 115 | 2,872 | Feature/model selection, regularization selection, grouped cross-validation, final base refit | Calibration or holdout claims |
| Calibration | WC2022 | 64 | 1,430 | Fit Platt parameters and apply the frozen adoption rule after the base model was frozen | Base refit, feature selection, candidate selection |
| Tournament holdout | Euro2024 | 51 | 1,304 | One predeclared final raw-versus-calibrated evaluation | Any retrospective model, feature, calibration, or threshold decision |

The development matches are divided into five deterministic, match-grouped folds of 23 matches.
They are assigned after sorting by `(match_date, match_id)` and using `index % 5`; they are **not**
temporal or forward-chaining folds. Grouping keeps every shot from a match on one side of a fold
boundary. The top-level tournament order is chronological, but the Euro2024 holdout also changes
competition composition. It is therefore a **tournament holdout**, not a pure temporal-drift test.

The lock is not described as historically blind. Before it was frozen, published cohort
reconciliation had exposed per-tournament goal counts and untracked exploration had viewed some
aggregate outcome rates. From WP2.3 onward, however, Euro2024 outcomes were prohibited from model,
feature, calibration, and selection decisions. This more precise claim is fixed in the
[split contract](docs/modeling/wp2_3-split-and-evaluation-contract.md) and verified by the
[split evidence](reports/wp2.3-split-evidence.md).

### Why the separation matters

**Registered decision.** Model choice was made from development evidence; calibration was then
fitted and adopted on a separate tournament; only after both were frozen was Euro2024 evaluated.

**Engineering interpretation.** If Euro2024 had been allowed to choose the raw model after its
scores were known, it would no longer be an honest final evaluation. Preserving the pre-holdout
calibration decision makes the reported transport result less flattering but scientifically more
useful.

## Feature engineering

### Geometry

The model sees two continuous features derived from the recorded shot location:

- `distance_to_goal`: Euclidean distance to goal centre `(120, 40)`, in **StatsBomb coordinate
  units**. The source contract does not establish metres or yards.
- `visible_goal_angle`: the angle subtended by the two goalposts at the shot location, in
  **radians**.

The angle uses a numerically stable two-post `atan2(cross, dot)` form. On the pinned cohort, the
common single-arctangent expression is wrong for 38 shots inside the four-coordinate-unit circle
around goal centre and divides by zero for one shot on its boundary. One measured source location
at `x = 120.1` receives a bounded geometry-only tolerance adjustment to `120.0`; the stored source
row is unchanged and values beyond the measured tolerance raise. See the
[geometry evidence](reports/wp2.2-geometry-evidence.md) and
[geometry contract](docs/modeling/wp2_2-geometry-contract.md).

Continuous columns are standardized. During cross-validation the scaler is fitted on each fold's
training rows only; the released base artifact carries a scaler refitted on all development rows.

### Categorical encoding

The categorical vocabulary is fitted once on development rows without labels. A development level
with fewer than 25 rows is merged into a derived `rare` bucket. One reference level per field is
dropped, so it is represented by all-zero indicators:

| Field | Reference | Retained non-reference columns | Members of `rare` |
|---|---|---|---|
| Body part | Right Foot | Head, Left Foot, `rare` | Other |
| Technique | Normal | Half Volley, Volley, `rare` | Backheel, Diving Header, Lob, Overhead Kick |
| Play pattern | Regular Play | From Corner, From Counter, From Free Kick, From Goal Kick, From Keeper, From Kick Off, From Throw In, `rare` | Other |

A genuinely unseen future level uses the all-zero reference encoding; it neither drops the row nor
silently expands the feature contract. This is a serving-time compatibility policy, not a claim
that the unseen level is semantically identical to the reference.

### Exact released base-model columns

The persisted order is part of the artifact contract:

```text
distance_to_goal
visible_goal_angle
body_part_name::Head
body_part_name::Left Foot
body_part_name::rare
technique_name::Half Volley
technique_name::Volley
technique_name::rare
play_pattern_name::From Corner
play_pattern_name::From Counter
play_pattern_name::From Free Kick
play_pattern_name::From Goal Kick
play_pattern_name::From Keeper
play_pattern_name::From Kick Off
play_pattern_name::From Throw In
play_pattern_name::rare
```

These are model features. `shot_type_name` is retained only for evaluation slices and is **not** a
released feature. `first_time` and `under_pressure` were evaluated as true-only presence
indicators, then excluded by the registered feature gate. `open_goal`, `one_on_one`, other uncertain
annotations, post-shot fields, outcomes, future events, and provider xG are also not features. The
[coverage audit](reports/wp2.2-slice-b-coverage-evidence.md) explains why absent optional annotations
cannot be called recorded `false` values.

## Model-development journey

Complexity was challenged progressively on identical development rows and grouped folds. The table
reports the unweighted mean of five fold log losses and pooled out-of-fold values for the other
metrics. Lower is better for log loss and Brier; higher is better for ROC AUC and PR AUC.

| Candidate | What it tested | Mean log loss | Pooled Brier | Pooled ROC AUC | Pooled PR AUC | Decision |
|---|---|---:|---:|---:|---:|---|
| `constant` | Training-fold goal rate only | 0.301886 | 0.081509 | 0.4755 | 0.0847 | Evaluation reference |
| `geometry_logistic` | Distance + angle, L2 logistic | 0.269951 | 0.074725 | 0.7354 | 0.2612 | Better probability quality than constant; not the final feature set |
| `full_logistic` | Geometry + categoricals + two presence indicators | 0.262047 | 0.072459 | 0.7543 | 0.3052 | Presence pair excluded by the D5 consistency gate |
| **`full_minus_presence`** | Geometry + categoricals | **0.263358** | **0.073044** | **0.7530** | **0.2942** | **Selected base estimator** |
| `hist_gbm` | Controlled nonlinear tree challenger | 0.268004 | 0.074544 | 0.7413 | 0.2592 | Did not replace logistic |
| `pytorch_mlp` | Bounded `16 → 8 → 1` neural challenger | 0.266694 | 0.073870 | 0.7492 | 0.2823 | Did not replace logistic |

The constant's pooled ROC AUC is below 0.5 because each validation fold receives its own
training-fold prevalence; within each fold its ROC AUC is 0.5. It is a baseline, not a useful
ranking model.

### How replacement decisions were made

**Registered decision.** A challenger could replace the incumbent only if all four conditions held
on development folds: mean log loss improved by more than the incumbent's cross-fold log-loss
standard deviation, mean Brier did not worsen, supported-bin calibration did not worsen, and
cross-fold log-loss stability did not worsen. Ties stayed with the simpler model. Euro2024 never
entered this rule.

The richer `full_logistic` candidate requires a separate explanation. Its two added fields are
provider true-only annotations (`first_time` and `under_pressure`), not ordinary booleans. The
pre-registered D5 gate required a positive log-loss contribution on at least four of five folds,
plus its other consistency conditions. It achieved three of five, so both indicators were excluded
even though its aggregate metrics were slightly better. That rule produced the released
`full_minus_presence` feature set; it was not decided after seeing Euro2024.

WP2.4 also exposed a protocol anomaly rather than tuning it away: the general four-part rule named
the constant as its formal `protocol_incumbent` because a training-fold-rate constant has a
constructed near-zero deviation in its single supported reliability bin. That label is distinct
from the shipped predictive candidate. The logistic model clearly improved the primary proper
scores, and `full_minus_presence` was the base carried into the direct WP2.5 and WP2.6 challenger
comparisons. The [WP2.4 evidence](reports/wp2.4-baselines-evidence.md) records both concepts.

### Controlled HistGradientBoosting challenger

The booster used the identical 16 encoded columns and fold-specific preprocessing. One declared
12-point grid varied learning rate `{0.03, 0.06, 0.1}`, maximum leaves `{7, 15}`, and minimum leaf
samples `{20, 60}`; fixed settings included 200 iterations, L2 regularization `1.0`, no early
stopping, and one execution thread. The selected point was learning rate `0.03`, 7 leaves, and 60
minimum samples per leaf.

It improved supported-bin maximum calibration deviation (`0.031439` versus `0.053595`) and
cross-fold log-loss standard deviation (`0.014544` versus `0.016167`), but worsened mean log loss
and Brier. Two of four replacement conditions passed, so the logistic remained selected. This is a
valid negative challenger result, not a broken model. See the
[WP2.5 evidence](reports/wp2.5-gradient-boosting-evidence.md).

### Bounded PyTorch MLP challenger

WP2.6 tested more than whether a neural network could fit the data. It preregistered one small
float32 network—`Linear(16, 8)`, ReLU, `Linear(8, 1)`—with 145 parameters, raw-logit output, AdamW,
200 fixed epochs, batch size 128, seed 0, and no architecture or hyperparameter search. The same 16
features, matches, folds, preprocessing boundary, and selection rule were retained.

Canonical selection ran on deterministic CPU fits. Two fresh CPU reproductions had to agree with
the canonical metrics, predictions, histories, parameters, and artifact identities. Separate RTX
4050 CUDA runs qualified deterministic device execution and same-weight CPU/CUDA inference parity;
the maximum probability difference was `1.78814e-07` under `atol=1e-6`, `rtol=1e-5`. CUDA evidence
was qualification-only and had no selection effect.

The MLP's mean log loss was `0.266694` and pooled Brier `0.073870`, so it did not replace the
logistic incumbent. Its engineering qualification remains useful evidence about deterministic
training, artifact integrity, dependency isolation, and cross-device inference. See
[ADR 0012](docs/adr/0012-wp2-6-bounded-pytorch-mlp-lifecycle.md), the
[WP2.6 contract](docs/modeling/wp2_6-pytorch-mlp-contract.md), and the immutable
[MLP metrics](experiments/shot_quality/exp-20260809-wp2_6-pytorch-mlp/metrics.json).

## Final base-model specification

The released base artifact is the `full_minus_presence` logistic model refitted on all 2,872
development shots after cross-validation decisions were frozen. It uses `lbfgs`, L2 regularization
with `C = 0.1`, selected from the preregistered `{0.01, 0.1, 1.0, 10.0}` grid by mean fold log
loss, then mean Brier, then the smaller `C`. It allows at most 100,000 iterations with convergence
checked, uses tolerance `1e-4` and seed 0, and applies no class weighting, resampling, or decision
threshold. The model bundle persists the estimator, all-development scaler, label-free development
vocabulary, column order, selected-column indices, and provenance. Inference fails loudly if the
feature-column contract changes.

The refit intercept is `-2.456661747175`; the interpretation report rounds it to `-2.457`. The two
standardized geometry coefficients are reported as `-0.596` for distance and `+0.478` for visible
angle. These measured coefficients are consistent with lower estimated conversion probability
farther from goal and higher estimated probability as more goal is visible, conditional on the
remaining model inputs. That sentence is an association-based engineering interpretation, not a
causal claim.

## What the metrics mean

| Metric | What it asks | Interpretation boundary |
|---|---|---|
| Log Loss | How much probability the model assigned to what actually happened, with large penalties for confident errors | A proper probability score; lower is better. Sensitive to both discrimination and probability calibration. |
| Brier Score | Mean squared error between predicted probability and the binary outcome | A proper probability score; lower is better. Its scale depends on event prevalence. |
| ROC AUC | Probability that a randomly chosen goal is ranked above a randomly chosen miss, with tied scores receiving half credit | A ranking metric; higher is better. It does not show that probabilities are numerically calibrated. |
| PR AUC | Precision-recall ranking quality, reported here as average precision | Useful with rare positive outcomes and prevalence-sensitive; higher is better. It is not a calibration measure. |

Log loss and Brier were primary because the product needs probability estimates, not just an
ordering of shots. ROC AUC and PR AUC were secondary discrimination measures. A strictly increasing
Platt transform preserves ranking, so it can change log loss, Brier, and reliability while leaving
ROC AUC and PR AUC unchanged.

## WC2022 calibration

After the base estimator and preprocessing were frozen, WC2022 supplied 1,430 calibration shots and
152 goals. The runner obtained frozen base logits and fitted only the one-dimensional transform:

```text
p_calibrated = sigmoid(1.256307409023587 × base_logit + 0.7228009741380947)
```

No base estimator, vocabulary, scaler, or feature column was refitted. The Platt parameters and all
base identities were bound into an immutable calibration decision.

### Adoption rule and outcome

**Registered decision.** Five equal-width groups were anchored to the **raw** WC2022 probabilities:
`[0,.2)`, `[.2,.4)`, `[.4,.6)`, `[.6,.8)`, `[.8,1]`. Raw and calibrated values were compared on
identical rows. A group counted toward the maximum calibration-deviation comparison only with at
least 100 shots. Adoption required a finite positive slope, at least one supported group, an
improvement of at least `1e-12` in maximum supported deviation, and no deterioration greater than
`1e-12` in either log loss or Brier.

All conditions passed before Euro2024 was opened:

| WC2022 measure | Raw | Calibrated |
|---|---:|---:|
| Log loss | 0.287490481491 | 0.283935933001 |
| Brier | 0.083215749855 | 0.082042526407 |
| Maximum deviation over supported raw-anchor groups | 0.012247769394 | 0.004302015683 |

There was one supported raw-anchor group. The immutable decision adopted `calibrated`. The exact
rule and parameters are in
[calibration-decision.json](experiments/shot_quality/exp-20260809-wp2_7-calibration-holdout/calibration-decision.json).

## Final Euro2024 tournament holdout

The supervised final evaluation opened Euro2024 once and materialized 1,304 eligible shots from 51
matches: 98 goals and 1,206 misses. Observed prevalence was `0.075153374233`; it is descriptive
context, not a baseline prediction.

| Variant | Log loss | Brier | ROC AUC | PR AUC |
|---|---:|---:|---:|---:|
| Raw base model | 0.239307508271 | 0.064707399225 | 0.744677970691 | 0.223985679737 |
| Pre-holdout-adopted calibrated model | 0.243112806225 | 0.066029980705 | 0.744677970691 | 0.223985679737 |
| Calibrated minus raw | +0.003805297954 | +0.001322581480 | 0 | 0 |

**Measured fact.** On Euro2024, calibration slightly worsened both proper probability scores while
ranking metrics were unchanged. This shows that the WC2022-fitted transform did not improve
out-of-tournament probability quality on this holdout.

**Registered decision.** The result did not reselect `raw`. The adopted variant remains
`calibrated` because adoption happened on WC2022 under the frozen rule. Reversing that choice after
seeing Euro2024 would use the holdout for selection and make the final estimate optimistically
biased.

### Match-clustered paired uncertainty

The predeclared bootstrap sampled whole matches with replacement, scored raw and calibrated
predictions on the same resampled matches, and repeated this 2,000 times with seed 0. Whole-match
sampling respects the fact that shots within one match share context; pairing isolates the
raw-versus-calibrated difference from a change in sampled matches. The intervals are 95% percentile
intervals.

| Metric | Raw interval | Calibrated interval | Calibrated-minus-raw interval |
|---|---:|---:|---:|
| Log loss | [0.207095650265, 0.269139852355] | [0.210598611086, 0.273303673707] | [0.000095442006, 0.007815706219] |
| Brier | [0.053985347273, 0.074766555611] | [0.055641037736, 0.075907318637] | [-0.000013107008, 0.002806020149] |

These intervals quantify match-sampling uncertainty for this paired tournament comparison. They do
not quantify every model uncertainty, remove dataset shift, or turn the result into a causal claim.
The authoritative aggregates and bootstrap payload are in
[holdout-metrics.json](experiments/shot_quality/exp-20260809-wp2_7-calibration-holdout/holdout-metrics.json).

## Reliability and slice analysis

Reliability tables use five fixed equal-width probability bins. On Euro2024 the raw variant placed
1,211 of 1,304 shots in `[0,.2)`; the calibrated variant placed 1,151 there. Upper bins were much
thinner, so their observed conversion rates are noisy and should not be read as precise calibration
estimates.

One provenance detail is easy to misread: the legacy top-level `raw_anchor_reliability` field in
`holdout-metrics.json` is copied **WC2022 calibration provenance**. Its counts total 1,430. It is
not a Euro2024 reliability table. Actual Euro2024 reliability lives under `variants.raw.reliability`
and `variants.calibrated.reliability`, each totaling 1,304 rows. The
[schema clarification](reports/wp2.7-holdout-schema-clarification.md) preserves this mapping without
rewriting the immutable artifact.

Slice interpretation required, simultaneously, at least 50 shots, 5 goals, 5 misses, and 10
matches. Supported Euro2024 levels were:

- body part: Head, Left Foot, Right Foot;
- distance: `[0,10)`, `[10,20)`, `[20,30)` StatsBomb coordinate units;
- play pattern: From Corner, From Counter, From Free Kick, From Throw In, Regular Play;
- shot type: Open Play;
- technique: Half Volley, Normal, Volley;
- visible angle: `[0.2,0.4)`, `[0.4,0.6)`, `[0.6,+inf)` radians.

Other registered levels remained listed as `sparse` and were not interpreted. In particular,
`shot_type_name` is an evaluation dimension here, not a model input. The support rule limits
overinterpretation; it does not prove that every supported subgroup is precisely estimated or
transportable to another competition.

## Reproducibility and release status

WP2.8 assembled a content-hashed release packet from the frozen WP2.4 base artifact and frozen
WP2.7 calibration/holdout chain. It did not train another candidate, fit another calibrator, reopen
WC2022 or Euro2024, create a second calibrated pickle, or add a result-ledger row.

### What was reproduced

Historical reproduction was deliberately **development-only**. A temporary checkout at the
registered WP2.4 reproduction commit loaded the same 2,872 development shots and 115 matches;
WC2022 and Euro2024 rows were forbidden and were not loaded, preprocessed, or scored. This proves
the historical base-training artifact can be recreated without reopening calibration or holdout
labels.

The execution exactly matched the registered fingerprint—Windows AMD64, CPython 3.12.11, uv
0.11.25, the registered historical lockfile bytes, reproduction commit, and config digest. Inside
that scope, exact comparison passed: the model artifact was byte-identical, canonical metrics JSON
was equal, and the feature contract matched. The byte-identical claim does **not** extend to
arbitrary operating systems, architectures, Python environments, or dependency resolutions.

**Release qualification is not deployment.** `release_status = m2_qualified` says the content and
provenance packet passed the M2 release gate. `serving_status = not_served` says no evidence yet
shows this model powers the API or UI. Serving and production monitoring belong to M3.

### Version and provenance

| Identity | Canonical value |
|---|---|
| StatsBomb Open Data revision | `b0bc9f22dd77c206ddedc1d742893b3bbe64baec` |
| Split-assignment SHA-256 | `e2d5517d96aa81d2229e1ef00a3c692f44f280630c3e75b7f6735e7cdc1787d8` |
| WP2.4 reproduction commit | `81d4a56395985cb427fbcd13f38a0eb8c42e8be6` |
| Base model SHA-256 | `9aeac9468c00bd1b93c771e454e48ca29e2eb759cf71836182a782d674bfadca` |
| Base metrics SHA-256 | `00b8785b25c03758a93416b0edf461adf1584fc06b20be1f75ba702019a67e5c` |
| Calibration decision digest | `f5c9ccf665924069f755fbd669d4a9abada1e5791e957d3d436d42d500277e89` |
| Holdout membership digest | `6a4b02d6bfb9d3c4619239772c089a65455a5cb0299956912d2d520ca639b729` |
| Release ID | `exp-20260810-wp2_8-release` |
| Release-manifest content digest | `bad64e5972938335e62b98d694f24961117e5f46034518f38b61209e2c3ca87d` |

The [release closeout](reports/wp2.8-reproducible-release-closeout.md) records the full hash chain;
the [release manifest](experiments/shot_quality/exp-20260810-wp2_8-release/release-manifest.json)
is the compact machine-readable integrity authority.

## Limitations

1. **Coverage is narrow.** Development uses two international tournaments, calibration one World
   Cup, and final evaluation one European Championship, all from one pinned Open Data revision.
   The evidence does not establish performance in domestic leagues, women's football, youth
   football, other eras, or another provider's event definitions.
2. **The holdout changes more than time.** Euro2024 differs in date and competition composition, so
   the result cannot isolate temporal drift from tournament distribution shift.
3. **Calibration transport is not established.** The WC2022 Platt transform met its adoption rule
   but worsened log loss and Brier on Euro2024. One source and one destination tournament cannot
   characterize general calibration transport.
4. **Sparse groups remain uncertain.** The support policy prevents interpretation of the thinnest
   slices, and even supported slice estimates carry sampling and multiple-comparison uncertainty.
5. **The feature view is deliberately incomplete.** The model has shot location, body part,
   technique, and play pattern, but no continuous tracking, StatsBomb 360, goalkeeper/defender
   geometry, pass-sequence representation, player ability, or game-state history. Embedded source
   freeze frames are not treated as tracking data.
6. **Provider annotations have semantics and intensity limits.** True-only context annotations
   cannot distinguish “not present” from “not annotated.” The two tested presence indicators were
   excluded; other uncertain annotations were not silently promoted to features.
7. **Geometry uses provider coordinates.** Distance is in StatsBomb coordinate units, not a claimed
   physical unit. One bounded source-coordinate exception is handled in derived geometry only.
8. **Probabilities are not causal effects.** The model describes associations in recorded event
   data. It cannot say how conversion probability would change under an intervention.
9. **Uncertainty is partial.** The match bootstrap addresses sampling variation for aggregate
   Euro2024 score comparisons. It does not include source-label error, model-form uncertainty,
   hyperparameter-search uncertainty, or all forms of distribution shift.
10. **No commercial-model equivalence is claimed.** Provider xG is absent, and the project has not
    established parity with proprietary data, features, or models.
11. **No live-serving evidence exists.** M2 release qualification does not demonstrate latency,
    online feature parity, operational calibration, drift monitoring, rollback, or user-interface
    behavior.

## Responsible interpretation

An individual value should be read as: “given the information this model sees, shots like this were
assigned this estimated conversion probability.” It should not be read as a complete account of
chance difficulty, player skill, decision quality, or tactical value.

Aggregate comparisons should report population, tournament, sample size, and whether a slice met
the support rule. A lower score on one tournament is not proof of universal superiority. The
Euro2024 raw-versus-calibrated result is especially important: it is a measured transport outcome,
not permission for post-hoc reselection.

## Verifying the release

Routine verification should inspect the committed packet and run hermetic tests; it should not
reopen historical calibration or holdout rows:

```bash
uv sync --locked
uv run pytest backend/tests/test_wp2_8_release.py
uv run poe check
```

The historical full acceptance command was `uv run poe wp2-8-release`. It is intentionally outside
the normal test suite, requires the registered read-only full-cohort database and exact historical
inputs, and refuses to overwrite an existing packet. It is recorded for auditability, not as a
routine command to rerun in this checkout.

To audit values without execution, inspect:

- [WP2.4 base metrics](experiments/shot_quality/exp-20260805-wp2_4-baselines/metrics.json);
- [WP2.7 calibration decision](experiments/shot_quality/exp-20260809-wp2_7-calibration-holdout/calibration-decision.json);
- [WP2.7 holdout metrics](experiments/shot_quality/exp-20260809-wp2_7-calibration-holdout/holdout-metrics.json);
- [WP2.7 one-open audit](experiments/shot_quality/exp-20260809-wp2_7-calibration-holdout/holdout-access-audit.json);
- [WP2.8 reproduction record](experiments/shot_quality/exp-20260810-wp2_8-release/reproduction.json);
- [WP2.8 release manifest](experiments/shot_quality/exp-20260810-wp2_8-release/release-manifest.json).

## Evidence index

| Lifecycle stage | What it establishes | Canonical evidence |
|---|---|---|
| Cohort and leakage boundary | Eligible population, target, exclusions, provider-xG prohibition | [WP2.1 reconciliation](reports/wp2.1-cohort-reconciliation.md), [cohort contract](docs/modeling/wp2_1-cohort-and-leakage-contract.md) |
| Geometry | Goal constants, feature formulas, units, numerical and boundary behavior | [WP2.2 geometry evidence](reports/wp2.2-geometry-evidence.md), [geometry contract](docs/modeling/wp2_2-geometry-contract.md) |
| Context coverage | Category support and true-only annotation encoding | [WP2.2 Slice B evidence](reports/wp2.2-slice-b-coverage-evidence.md) |
| Split and evaluation | Locked tournament roles, grouped folds, holdout restrictions | [public split contract](reports/wp2.3-split-contract.md), [split evidence](reports/wp2.3-split-evidence.md), [split manifest](data/model/wp2_3_split_manifest.json) |
| Logistic selection | Candidate metrics, feature gate, final coefficients and artifact | [WP2.4 evidence](reports/wp2.4-baselines-evidence.md), [run config](experiments/run-configs/wp2_4-baselines.json), [immutable metrics](experiments/shot_quality/exp-20260805-wp2_4-baselines/metrics.json) |
| Boosting challenge | Registered grid, controlled comparison and non-replacement | [WP2.5 evidence](reports/wp2.5-gradient-boosting-evidence.md), [run config](experiments/run-configs/wp2_5-gradient-boosting.json), [immutable metrics](experiments/shot_quality/exp-20260806-wp2_5-gradient-boosting/metrics.json) |
| PyTorch challenge | Bounded architecture, deterministic CPU/CUDA qualification and non-replacement | [ADR 0012](docs/adr/0012-wp2-6-bounded-pytorch-mlp-lifecycle.md), [run config](experiments/run-configs/wp2_6-pytorch-mlp.json), [artifact manifest](experiments/shot_quality/exp-20260809-wp2_6-pytorch-mlp/artifact-manifest.json) |
| Calibration and holdout | Frozen-base Platt decision, one-time Euro2024 scores, bootstrap, slices and audit | [WP2.7 closeout](reports/wp2.7-calibration-holdout-closeout.md), [calibration decision](experiments/shot_quality/exp-20260809-wp2_7-calibration-holdout/calibration-decision.json), [holdout metrics](experiments/shot_quality/exp-20260809-wp2_7-calibration-holdout/holdout-metrics.json) |
| Reproducible release | Development-only historical reproduction, environment scope, integrity chain and lifecycle status | [ADR 0014](docs/adr/0014-wp2-8-reproducible-calibrated-release.md), [release closeout](reports/wp2.8-reproducible-release-closeout.md), [release manifest](experiments/shot_quality/exp-20260810-wp2_8-release/release-manifest.json) |
| Experiment ledger | Registered completed development experiments | [results ledger](experiments/results.csv) |

## Data attribution and rights

Data provided by **StatsBomb** through the
[StatsBomb Open Data repository](https://github.com/statsbomb/open-data). StatsBomb/Hudl owns the
match data, which is governed by its own Public Data User Agreement; this repository's software
notice grants no rights to that data. See [DATA_SOURCE.md](DATA_SOURCE.md) for the pinned snapshot,
attribution review, and two unresolved publication gates concerning an approved logo asset and the
public row-level API boundary. See [LICENSE](LICENSE) for the separate source-available software
terms.

This model card does not reproduce or claim ownership of StatsBomb's data or proprietary xG model.
