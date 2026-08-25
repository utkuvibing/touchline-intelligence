# WP5.2 v2 nested protocol contract

## Status

Preregistered. This document, `data/model/v2_protocol.json`, the fold-semantics module
`backend/src/touchline/modeling/v2_folds.py`, and
[ADR 0016](../adr/0016-wp5-2-v2-nested-evaluation-protocol.md) were committed **before any v2
experiment ran**. No probability, metric, conversion count or row-level preview exists anywhere in
their provenance. Every number below is copied verbatim into the machine-readable config; unit
tests pin config, prose and literals together so silent divergence fails CI.

## Research question

The v1 question carries over unchanged: the probability that a recorded Shot becomes a goal,
using only information available at or before the shot, on the same pinned source revision
(`b0bc9f22dd77c206ddedc1d742893b3bbe64baec`) and the same 5,606 eligible non-penalty shots.
What changes is the evaluation protocol: v2 selects and reports under a nested
leave-one-tournament-out design whose selection folds never double as reporting folds, and whose
final quality claim rests on two sealed external tournaments that no development command can read.

## Relationship to the WP2.3 split

Carried over: the cohort definition and exclusions (`wp2_1`), the geometry features (`wp2_2`),
the identifier convention (`shot_id` is `events.event_id`), five equal-width reliability bins
fixed a priori per the ADR 0004 amendment, the prohibition on provider xG, outcome and post-shot
features, and the fold rule shape (matches sorted by `(match_date, match_id)`, `index % k`,
deterministic match-grouped assignment, no temporal claim within development).

Corrected: the single three-way split (development / WC2022 calibration / Euro2024 holdout) is
spent — its holdout was opened once for v1 and cannot be reopened for v2 claims. v2 replaces it
with four outer leave-one-tournament-out folds over all four development-pool tournaments, inner
match-grouped selection inside each outer training partition, fold-local preprocessing, and two
newly sealed external qualification sets (WP5.1). WC2022 loses its special calibration-split
status; it becomes ordinary v2 development data under the corrected protocol.

Euro 2024 status, kept apart so none can be mistaken for another:

1. For **v1** claims, Euro 2024 remains the historical one-time tournament holdout under ADR 0013;
   nothing in this protocol reopens or reslices it.
2. For **v2**, Euro 2024 is development data: its outcomes have long been exposed (WP2.1's
   published reconciliation reported per-tournament goal counts) and it is *not claimed as
   untouched*. Its untouchability cost is paid honestly: the time/tournament confound that v1
   isolated in a holdout now sits inside v2's training history.

## Evidence hierarchy

This is the protocol's central claim and every report, model card and UI surface must label
results accordingly:

- **Outer LOTO predictions and metrics are internal development/selection evidence.** They are
  produced by the same procedure that chose feature bundles, hyperparameters, the calibrator and
  the final refit, so they are optimistically biased. They are never presented as the unbiased
  post-selection estimate of v2 quality.
- **The one-time sealed AFCON 2023 + Copa América 2024 qualification is the external
  generalization evidence**, and the only basis for the v1-versus-v2 replacement decision.
- Conflating the two layers is a protocol violation, not a wording preference.

## Frozen fold semantics — one production primitive

The frozen fold semantics live in one production module,
`backend/src/touchline/modeling/v2_folds.py`, driven only by `data/model/v2_protocol.json`. M6 and
M7 must consume exactly that module's functions; reimplementing fold logic elsewhere is
prohibited. The unit contract imports and exercises the primitive directly — there is no second
reference implementation. Only *materialized* fold-manifest generation (the committed per-fold
assignment artifact) remains deferred to M7's evaluation harness.

**Outer — exactly four leave-one-tournament-out scopes, in this fixed iteration order:**

| Outer fold | Held out | Scope |
|---|---|---|
| `loto_wc2018` | WC2018 | `(43, 3)` |
| `loto_euro2020` | Euro2020 | `(55, 43)` |
| `loto_wc2022` | WC2022 | `(43, 106)` |
| `loto_euro2024` | Euro2024 | `(55, 282)` |

Each tournament is the outer evaluation fold exactly once. Outer training partitions are the
remaining three tournaments (166 or 179 matches).

**Inner — match-grouped CV inside each outer training partition:** grouped strictly by
`match_id`; `k = 5`; matches sorted by `(match_date, match_id)` then assigned
`inner_fold = index % 5` (~33–36 matches per inner fold); `shuffle = false`; there is **no seed**
because fold assignment is fully deterministic — the only preregistered random seed in v2 is the
bootstrap seed. The inner folds are deterministic match-grouped partitions: not temporal, not
forward-chaining.

**Tie behavior:** any unresolved selection tie resolves mechanically to the simpler candidate —
lower feature bundle level first, then logistic over boosting. Ties are never broken by measured
performance.

**Target-free by construction:** like WP2.3's assignment, fold inputs carry match identity, scope
and date only. No goal, label, provider xG or outcome-derived statistic enters fold construction.

## Fold-local preprocessing

Every learned step lives inside the relevant training partition — outer-fitting inside each outer
training partition, inner-fitting inside each inner training partition:

- categorical vocabulary construction and rare-level merging;
- missingness policy (including the WP2.3 inherited obligations: explicit unseen-level policy for
  `shot_type_name = 'Corner'`; recorded caution that `under_pressure` and `first_time` are partly
  annotation intensity);
- scaling;
- spline knot placement (F1 bases);
- encodings.

One versioned transformer powers training, batch prediction and API prediction; duplicated
feature logic is prohibited. Features requiring unavailable inputs stay explicitly missing; no
inferred players or fabricated positions (relevant if F3 passes its M6 gate).

## Candidate families — exactly four

| Family | Definition | Search space (frozen) |
|---|---|---|
| `constant_prevalence` | training-fold non-penalty goal prevalence | none |
| `v1_form_l2_logistic` | v1 representation under the corrected pipeline, L2 logistic | `C ∈ {0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0}` |
| `context_rich_spline_logistic` | inner-selected M6 bundle + fold-fitted splines, L2 logistic | same `C` grid |
| `hist_gradient_boosting_challenger` | one `HistGradientBoostingClassifier` on the same inner-selected raw information | `learning_rate ∈ {0.03, 0.1}`, `max_leaf_nodes ∈ {8, 31}`, `min_samples_leaf ∈ {20, 50}`, `l2_regularization ∈ {0.0, 1.0}`, `max_iter = 300` |

Adding families or widening search spaces after any v2 run has executed requires a new ADR and
invalidates preregistration claims. All non-searched hyperparameters are fixed before the first
run and recorded in the M7 experiment record.

## Frozen M6 bundle evaluator

M6 freezes this evaluator and never applies it against held-out tournament outcomes; in M7 it
runs inside each outer training partition, on that partition's match-grouped inner validation
predictions only. A feature bundle is preferred over its predecessor only when all of the
following hold: mean log-loss improvement whose 95% match-bootstrap confidence interval lies
wholly below zero; Brier degradation at most `0.0005`; log loss non-worse in all but at most one
tournament represented in the outer training partition; no represented tournament worse by more
than `0.005` log loss; and complete offline/serving parity with declared feature coverage.

## Fixed metrics and uncertainty mechanics

- Primary: log loss and Brier score, pooled and per tournament.
- Calibration intercept/slope: logistic regression of the observed outcome on the logit of the
  predicted probability, fitted jointly by maximum likelihood; ideals are intercept `0`, slope `1`.
- Reliability tables: five equal-width bins over `[0, 1]` (edges `0, 0.2, 0.4, 0.6, 0.8, 1.0`),
  fixed a priori; alternative binning appears only as labelled sensitivity analysis.
- Secondary: ROC AUC and PR AUC; prespecified slice families carried over from WP2.7:
  `body_part_name`, `technique_name`, `play_pattern_name`, `shot_type_name`,
  `distance_statsbomb_coordinate_units`, `visible_goal_angle_radians`. Reliability diagrams are
  descriptive evidence, never an optimization target.
- Uncertainty: paired differences, match-clustered bootstrap, 2,000 replicates, seed 0, 95%
  percentile intervals. Pooled multi-tournament comparisons resample **tournament-stratified**:
  each replicate resamples matches within every tournament stratum, preserving per-stratum match
  counts, so a pooled interval cannot be dominated by the largest tournament. Per-tournament
  comparisons use identical mechanics with a single stratum.

## Calibration policy

Compare only raw probabilities, intercept-only recalibration and Platt scaling. Isotonic
regression is excluded on this corpus. The fitting procedure is preregistered and leakage-free by
construction:

- **Per outer fold:** the calibrator candidates (`intercept_only`, `platt`) are fitted **only**
  from out-of-fold raw predictions generated inside the outer training partition by the frozen
  inner CV — never from predictions of rows those inner models saw in training. A fitted
  calibrator is then applied to that outer fold's **untouched outer-holdout** raw predictions
  only. The adoption gates below evaluate these per-fold calibrated predictions; this is what
  "cross-fitted outer predictions" means.
- **Final refit, in this exact order:** (1) generate development OOF raw predictions by running
  the frozen inner procedure once on all four development tournaments; (2) fit the selected
  calibrator on those development OOF raw predictions; (3) refit the base model on all development
  rows; (4) freeze the model-calibrator pair before opening either sealed set.

Adopt a calibrator over raw only if cross-fitted outer
predictions show pooled log-loss improvement of at least `0.001` with the 95% paired interval
wholly below zero; no pooled Brier degradation (`≤ 0.000`); calibration intercept and slope
closer to their ideals in at least three of four tournaments; and no tournament worse by more
than `0.002` log loss. Otherwise ship raw probabilities.

## Internal replacement rule

The best non-constant candidate may replace the corrected v1-form candidate internally only when
pooled outer log loss improves by at least `0.003`; the 95% paired match-bootstrap confidence
interval for the difference is wholly below zero; pooled Brier degradation is at most `0.0005`;
it is non-worse in at least three of four tournaments; no tournament worsens by more than
`0.005` log loss; and feature coverage plus offline/serving parity pass. A near miss is a failed
gate, not permission for another search round.

## Final refit procedure

After outer evaluation: run the frozen inner procedure once on all four development tournaments
to choose the final bundle and hyperparameters; break unresolved ties toward the simpler
bundle/model; refit on all development rows; apply the cross-fitted calibration decision; freeze
the complete candidate **before opening either sealed set**. Outer predictions remain the
internal performance report and are not recomputed after this refit.

## One-time external qualification

Run the frozen candidate once on AFCON 2023 (`1267, 107`) and Copa América 2024 (`223, 282`),
each opened exactly once, reported separately and combined. Score four references: constant
prevalence, v1 raw, v1 calibrated, frozen v2. The external `constant_prevalence` reference is the
**full-development non-penalty goal prevalence over the four development-pool tournaments,
frozen before any sealed set is opened** — it is a training-pool statistic, not an external-set
statistic, so scoring it on the sealed sets leaks nothing. Promote v2 only against the stronger
of v1 raw /
v1 calibrated on the combined set when: combined log loss improves by at least `0.003`; the 95%
paired match-bootstrap interval is wholly below zero; the upper bound of the paired Brier
difference is at most `+0.0005`; neither external tournament worsens by more than `0.005` log
loss; and coverage, artifact integrity and offline/serving parity pass. On any failure: retain
v1, publish v2 as a negative result, stop model selection until a newly pinned genuinely
untouched complete tournament exists (per the WP5.1 future reservation, none does at the pinned
revision). Recycling AFCON 2023 or Copa América 2024 after opening is prohibited.

## Leakage-history statements kept apart

1. WP2.1's published full-cohort reconciliation exposed descriptive per-tournament goal counts,
   including Euro 2024's.
2. WP2.2 recorded aggregate outcome rates viewed during untracked exploratory work before the v1
   split was frozen.
3. This protocol's artifacts are target-free: no experiment has executed under them, and the
   committed config contains no outcome-bearing field in any fold rule.

These are properties of the artifacts, not claims that no historical query ever read a target.

## Boundaries and artifacts

- Machine-readable gates: `data/model/v2_protocol.json` (allowed-key schema, validated field by
  field; extra keys reject).
- Registry consistency: development pool and sealed sets mirror `data/model/v2_evaluation_registry.json`
  exactly; the two files must change together.
- Fold semantics are the production module `backend/src/touchline/modeling/v2_folds.py`; the unit
  contract imports it and pins its behavior on synthetic fixtures. M6/M7 import the same module;
  only materialized fold-manifest generation lands with M7's harness.
- This contract changes no schema, migration, dependency, public endpoint, deployed release, or
  v1 artifact. Zero experiments have executed under it.

Data provided by StatsBomb.
