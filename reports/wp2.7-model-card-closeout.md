# Shot-quality model card - WP2.7 closeout

This closeout model card summarizes only immutable WP2.7 aggregate artifacts. It does not rerun,
reopen, or reinterpret Euro2024 rows.

## Purpose and intended use

The model estimates shot-conversion probability for research and analyst decision support. It is
not StatsBomb's xG model, does not provide causal claims, and should not be treated as a calibrated
truth for sparse subgroups. The output is a probability, not a thresholded decision.

## Datasets and locked splits

The locked three-way design is:

- development: WC2018 + Euro2020;
- calibration: WC2022, used only to fit Platt parameters after the base model was frozen;
- final tournament holdout: Euro2024, used only for the predeclared final comparison.

The base estimator and preprocessing were fitted only on the all-development scope. Neither
WC2022 nor Euro2024 refit or altered the base estimator, preprocessing, feature columns, or feature
order.

## Candidate and feature decisions

The registered development candidates and decisions were:

| Candidate | Decision |
|---|---|
| `constant` | Protocol reference only; excluded from the Euro2024 scoring packet. |
| `geometry_logistic` | Evaluated as the geometry-only logistic candidate; not selected. |
| `full_logistic` | Presence-indicator alternative; rejected by the registered D5 rule. |
| `full_minus_presence` | Selected and shipped as the regularized-logistic base estimator. |
| `hist_gbm` | Controlled WP2.5 comparison; did not replace the selected logistic model. |
| `pytorch_mlp` | Bounded WP2.6 qualification; `candidate_replaces_incumbent=false`, so it did not replace the selected logistic model. |

The shipped artifact manifest identifies the exact feature columns as `distance_to_goal`,
`visible_goal_angle`, `body_part_name::{Head, Left Foot, rare}`,
`technique_name::{Half Volley, Volley, rare}`, and
`play_pattern_name::{From Corner, From Counter, From Free Kick, From Goal Kick, From Keeper,
From Kick Off, From Throw In, rare}`. Omitted one-hot reference levels are represented by the
encoding contract rather than additional columns. Shot type appears below only as a slice
dimension; `shot_type_name` is not a shipped feature column. Provider xG is not a feature.

Shipped geometry is distance in StatsBomb coordinate units and visible goal angle in radians;
physical units such as yards or metres are not claimed.

## Calibration protocol and decision

WC2022 fitted only a one-dimensional Platt sigmoid from frozen base logits. Adoption used raw
WC2022 probabilities to define five equal-width bins, with minimum support 100 and identical row
membership for raw and calibrated predictions. The slope was `1.256307409023587`, and every
registered adoption condition passed. The adopted calibrated variant is therefore the decision of
record before Euro2024.

Euro2024 did not choose between variants. Its raw-versus-calibrated result is reported as a paired
effect, including uncertainty, without changing the adopted variant.

## Final holdout result

The supervised audit records 1,304 rows, 51 matches, 98 goals, 1,206 misses, and exactly one
logical holdout open. Observed prevalence (`0.075153374233`) is descriptive context.

| Variant | Log loss | Brier | ROC AUC | PR AUC |
|---|---:|---:|---:|---:|
| raw | 0.239307508271 | 0.064707399225 | 0.744677970691 | 0.223985679737 |
| calibrated | 0.243112806225 | 0.066029980705 | 0.744677970691 | 0.223985679737 |

On Euro2024, the calibrated variant produced slightly worse log loss and Brier score than the raw
model, while ROC AUC and PR AUC were unchanged. This indicates that the WC2022-fitted Platt
transform did not improve out-of-tournament probability quality on this holdout, but the
pre-holdout calibration decision remains unchanged by design.

Match-clustered paired bootstrap: 2,000 replicates, seed `0`, 95% percentile intervals.

| Metric | Raw | Calibrated | Calibrated minus raw |
|---|---:|---:|---:|
| Log loss | [0.207095650265, 0.269139852355] | [0.210598611086, 0.273303673707] | [0.000095442006, 0.007815706219] |
| Brier | [0.053985347273, 0.074766555611] | [0.055641037736, 0.075907318637] | [-0.000013107008, 0.002806020149] |

The holdout scores are descriptive final evaluation. They do not reselect raw and do not invalidate
the pre-holdout calibrated decision.

## Reliability and slice uncertainty

The top-level legacy `raw_anchor_reliability` field in the immutable holdout metrics is the
WC2022 calibration raw-anchor adoption table copied for provenance. Its 1,430-count total is not a
Euro2024 count. Euro2024 reliability is nested under each scored variant and totals 1,304 rows.

The slice support rule is at least 50 shots, 5 goals, 5 misses, and 10 matches. Supported levels
are body part (Head, Left Foot, Right Foot), distance (`[0,10)`, `[10,20)`, `[20,30)` coordinate
units), play pattern (From Corner, From Counter, From Free Kick, From Throw In, Regular Play), shot
type (Open Play), technique (Half Volley, Normal, Volley), and visible angle (`[0.2,0.4)`,
`[0.4,0.6)`, `[0.6,+inf)` radians).

Sparse levels were body part (Other), distance (`[30,+inf)` coordinate units), play pattern (From
Goal Kick, From Keeper, From Kick Off, Other), shot type (Corner, Free Kick), technique (Backheel,
Diving Header, Lob, Overhead Kick), and visible angle (`[0,0.2)` radians). They remain listed but
are not interpreted.

## Limitations

Euro2024 is a tournament holdout rather than a pure temporal drift test: time and competition
composition change together. Match-clustered bootstrap intervals quantify sampling uncertainty for
the paired score comparison but do not address dataset shift, causal validity, or every source of
model uncertainty. The WC2022-fitted Platt transform did not improve probability quality on this
out-of-tournament Euro2024 holdout, so calibration transport across tournaments is not established.
The sparse slice levels are not supported for interpretation.

## Reproducibility and version identity

- Experiment: `exp-20260809-wp2_7-calibration-holdout`
- Decision SHA-256: `f5c9ccf665924069f755fbd669d4a9abada1e5791e957d3d436d42d500277e89`
- Base candidate: `full_minus_presence`
- Model artifact SHA-256: `9aeac9468c00bd1b93c771e454e48ca29e2eb759cf71836182a782d674bfadca`
- Artifact manifest SHA-256: `62cade6c3db5d741039de8f1ad53010319f422dcb942c96f16f1db8a498e8e79`
- Execution/reproduction commit: `e8e863947b74bbe8496a9734878941e8b10e30ce`
- Holdout config SHA-256: `d77187ad0bf7e5053d73c2debe0a61b8e1464885b16601d025f43d811267589b`
- Data source commit: `b0bc9f22dd77c206ddedc1d742893b3bbe64baec`
- Source bundle SHA-256: `710ec99da792c946ff53d5730f0235bb03df41fcfc7dd74d1acfd6a574a2c4fa`
- Holdout membership digest: `6a4b02d6bfb9d3c4619239772c089a65455a5cb0299956912d2d520ca639b729`

The completed audit's evidence-file hashes remain the integrity authority for the measured run.
This closeout model card is a separate presentation artifact derived from those hashes and
aggregates.

Data provided by StatsBomb.
