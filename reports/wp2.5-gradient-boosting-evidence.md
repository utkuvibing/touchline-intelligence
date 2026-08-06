# WP2.5 — gradient boosting on the locked development split

One gradient-boosting candidate, tuned over a twelve-point declared grid, evaluated against the
WP2.4 logistic regression on identical rows and identical features.

**Result: the booster did not replace the logistic regression.** It is better calibrated and more
stable across folds, and worse on both proper scoring rules. The incumbent is kept and the
comparison is published as-is.

## Provenance

| | |
|---|---|
| Experiment | `exp-20260806-wp2_5-gradient-boosting` |
| Code / reproduction commit | `27d16f9862cf94f24a75f155907c1616ec3b7a04` |
| Data source commit | `b0bc9f22dd77c206ddedc1d742893b3bbe64baec` |
| Cohort SQL SHA-256 | `301d8a620b60d8da6011c7c4d12ef8108c658df4d923f612c3e3bf9e0427978e` |
| Split assignments SHA-256 | `e2d5517d96aa81d2229e1ef00a3c692f44f280630c3e75b7f6735e7cdc1787d8` |
| Input config SHA-256 | `ddb15e39789c0a916ad0de8c95974af7e77cf10a4ab7b03e22974ad70df37f02` |
| `uv.lock` SHA-256 | `f02faa7ea86d5808a8f210c0c8c2cda6781bdbb3a029bc8be0f87d032e95e71d` |
| Model pickle SHA-256 | `ef224dfdf7b65d461546abb987eb0ac492c5bb190180e60c220d8551b34dd0e8` |
| Runtime | CPython 3.12, `OMP_NUM_THREADS=1`, reported threadpool threads `[1]` |

Recreation:

```
git checkout 27d16f9862cf94f24a75f155907c1616ec3b7a04
uv sync --locked
# set TOUCHLINE_FULL_COHORT_DB_URL to the local ingested four-tournament database
uv run poe train-boosting --config experiments/run-configs/wp2_5-gradient-boosting.json
# (poe train-boosting runs `python -m touchline.boosting_bootstrap`, which pins OMP_NUM_THREADS=1)
```

## Population and protocol

2,872 eligible shots across 115 development matches — World Cup 2018 and Euro 2020 — in five
match-grouped folds of 570 / 552 / 602 / 576 / 572 shots. Goal rate 0.0895. The calibration split
(World Cup 2022) and the tournament holdout (Euro 2024) were never loaded: the loader filters to
development match ids server-side inside a read-only transaction and re-checks every returned row.

All five candidates were fitted **in this one process on these same folds**, so no figure in the
comparison depends on floats read from another run.

## Pre-registered decisions (D12–D21)

These were fixed, reviewed and accepted before the run. The internal contract that records them is
not published; every decision it fixes is restated here in full.

| # | Decision |
|---|---|
| D12 | Estimator: `sklearn.ensemble.HistGradientBoostingClassifier`, `random_state=0`, `early_stopping=False`. Already a project dependency, so no new package and no lock change. |
| D13 | Input matrix: the identical sixteen feature columns WP2.4 shipped, from the same encoder, with the per-fold scaler fitted on training rows only. The two candidates differ in exactly one thing — the estimator. |
| D14 | Declared grid, exactly twelve points: `learning_rate ∈ {0.03, 0.06, 0.1}` × `max_leaf_nodes ∈ {7, 15}` × `min_samples_leaf ∈ {20, 60}`. |
| D15 | Fixed, not searched, and every one passed explicitly rather than left to a library default: `max_iter=200`, `l2_regularization=1.0`, `max_bins=255`, `early_stopping=False`, `interaction_cst=None`. |
| D16 | Selection by unweighted mean of the five fold log losses; ties broken by `(mean_log_loss, mean_brier, learning_rate, max_leaf_nodes, min_samples_leaf)` ascending. The key is total, so the order the grid is enumerated in cannot decide a tie. |
| D17 | Exactly one pass over the grid: 12 × 5 = 60 fits. No second grid under any result. |
| D18 | The selection rule is applied twice. **Chain A** is the WP2.4 chain extended by one step (`constant → geometry_logistic → full_minus_presence → hist_gbm`), published for continuity. **Chain B** compares the booster directly against the shipped logistic and is the decision of record. |
| D19 | The calibration-support asymmetry is reported, never ruled on: alongside each candidate's own supported-bin deviation, the bins supported for **both** candidates are recorded. No decision reads it. |
| D20 | Every fit runs single-threaded, pinned at process start. Two runs under the same runtime must emit byte-identical records. |
| D21 | No calibration fitting on any split, no holdout access, no calibration-split access. |

Why `early_stopping=False`: early stopping needs an inner validation split, which would subdivide a
fold structure that was locked and proved before any model was fitted.

## Candidate results — identical locked rows

| Candidate | mean log loss | cross-fold SD | Brier (pooled) | ROC AUC | PR AUC | supported bins | max abs deviation |
|---|---:|---:|---:|---:|---:|---:|---:|
| Constant (training-fold rate) | 0.301886 | 0.017234 | 0.081509 | 0.4755 | 0.0847 | 1 | 0.000048 |
| Geometry-only logistic (C=0.1) | 0.269951 | 0.016579 | 0.074725 | 0.7354 | 0.2612 | 2 | 0.002906 |
| Full logistic (C=0.1) | 0.262047 | 0.016550 | 0.072459 | 0.7543 | 0.3052 | 2 | 0.065201 |
| **Full logistic minus presence (C=0.1) — incumbent** | **0.263358** | 0.016167 | 0.073044 | 0.7530 | 0.2942 | 2 | 0.053595 |
| **Histogram gradient boosting — candidate** | **0.268004** | **0.014544** | 0.074544 | 0.7413 | 0.2592 | 2 | **0.031439** |

The four WP2.4 rows are not transcribed: they were re-fitted in this run and **match the committed
WP2.4 record to twelve decimals**, across per-fold values, pooled out-of-fold values, reliability
tables, selected `C` and the support summary.

### Per-fold log loss

| fold | boosting | logistic incumbent |
|---|---:|---:|
| 0 | 0.274093 | 0.271496 |
| 1 | 0.281721 | 0.275470 |
| 2 | 0.249996 | 0.236236 |
| 3 | 0.251193 | 0.253857 |
| 4 | 0.283020 | 0.279733 |

The booster wins one fold of five, and is the more consistent of the two — its cross-fold spread is
the smallest of any candidate.

### Selected grid point

`learning_rate=0.03, max_leaf_nodes=7, min_samples_leaf=60`. The four best of the twelve:

| learning rate | max leaf nodes | min samples leaf | mean log loss | mean Brier |
|---:|---:|---:|---:|---:|
| 0.03 | 7 | 60 | 0.268004 | 0.074658 |
| 0.03 | 7 | 20 | 0.268210 | 0.074890 |
| 0.06 | 7 | 20 | 0.274227 | 0.076174 |
| 0.06 | 7 | 60 | 0.275297 | 0.076110 |

The ordering is unambiguous: the slowest learning rate and the shallower trees win, and every
seven-leaf configuration beats every fifteen-leaf one. On 2,872 rows with ~9% positives that is the
expected direction, and it is the reason the declared grid was kept small.

## Reliability — boosting candidate, five equal-width bins fixed a priori

| bin | range | n | positives | mean prediction | observed rate |
|---|---|---:|---:|---:|---:|
| 0 | [0.0, 0.2) | 2570 | 169 | 0.061391 | 0.065759 |
| 1 | [0.2, 0.4) | 233 | 61 | 0.293241 | 0.261803 |
| 2 | [0.4, 0.6) | 69 | 27 | 0.452970 | 0.391304 |
| 3 | [0.6, 0.8) | 0 | 0 | — | — |
| 4 | [0.8, 1.0] | 0 | 0 | — | — |

Empty bins are reported, never dropped. Under the pre-registered 100-prediction support floor, bins
0 and 1 count; bin 2 does not.

## The selection rule, applied twice

**Chain B — the decision of record.** `full_minus_presence` versus `hist_gbm`:

- **Condition 1 (lower mean log loss by more than the incumbent's own cross-fold SD): FAILS.** The
  booster needed 0.263358 − 0.016167 = 0.247191 or better; it scored 0.268004, which is worse than
  the incumbent outright.
- **Condition 2 (lower or equal mean Brier): FAILS.**
- **Condition 3 (no worse calibration): passes.** 0.031439 against 0.053595.
- **Condition 4 (not less stable): passes.** 0.014544 against 0.016167.

Two of four hold, so the incumbent is kept. **`selection_incumbent = full_minus_presence`.**

**Chain A — continuity with the WP2.4 record.** `geometry_beats_constant` false,
`shipped_beats_incumbent` false, `gbm_beats_protocol_incumbent` false, leaving
`protocol_incumbent = constant`. This outcome was written down before the run: a constant baseline
predicts the base rate for every row, so its predictions land in one supported bin where observed
equals predicted by construction (deviation 0.000048), and no real model can undercut that. Chain A
is a rule artifact, published for continuity, and is not the selection. Chain B exists because of
it.

**D19 diagnostic.** Both candidates cleared the support floor in the same two bins, `[0, 1]`, so on
this run the comparison rested on a shared basis: paired deviations 0.053595 for the incumbent and
0.031439 for the booster. This is reported, not ruled on — the rule kept reading each candidate's
own supported-bin deviation.

## What was measured

Stated as differences, without a causal account attached to them:

- **Ranking.** The booster ranks worse: ROC AUC 0.7413 against 0.7530, PR AUC 0.2592 against
  0.2942.
- **Calibration.** The booster is closer to observed rates on the supported bins: maximum absolute
  deviation 0.031 against 0.054.
- **Fold-to-fold stability.** The booster varies less across the five folds: cross-fold standard
  deviation of log loss 0.0145 against 0.0162 — the smallest of any candidate.
- **Proper scoring rules.** The booster is worse on both: mean log loss 0.268004 against 0.263358,
  pooled Brier 0.074544 against 0.073044.

Relative to knowing only the base rate, the booster recovers 0.033882 nats per shot and the
logistic model 0.038528 — the booster captures about 88% of the incumbent's information gain.

**Possible explanations, none of them tested here.** Sample size is one: 2,872 rows with roughly
257 goals is a small budget for a model class that can express interactions, and the positives are
what constrain a probability estimate. Shrinkage is another: the selected configuration uses the
slowest learning rate in the declared grid at a fixed 200 iterations, which compresses predictions
toward the base rate, and a compressed predictor would be expected to rank less sharply while
sitting closer to observed rates in the bins holding most of the mass. Feature representation is a
third: the booster consumed the logistic model's one-hot encoding rather than a tree-native
categorical form. This report does not distinguish between these, and nothing in WP2.5 was designed
to. They are candidate explanations for a measured pattern, not findings.

Under a pre-registered rule weighted toward proper scoring rules, the incumbent is kept.

## Determinism

The record reproduces. Re-running the protocol in a fresh process reproduced `metrics.json`
byte-for-byte across all 827 lines and reproduced the model pickle byte-for-byte (177,737 bytes,
SHA-256 matching the manifest).

That took a remediation. An earlier full-cohort run was **invalidated** because its artifact hash
was not reproducible, while every metric and every prediction was. The cause was measured, not
guessed: the OpenMP thread count changes the serialized bytes of a fitted histogram booster while
leaving its predictions bit-identical. Two hypotheses were tested and rejected first — database row
order (three independent loads returned the same 2,872 unique ids in the same ascending order) and
`PYTHONHASHSEED` (no effect). The fix pins one OpenMP thread at process start, before scikit-learn
is imported; a process started under a different thread count now fails loudly rather than
producing an artifact nobody can reproduce. The statistical protocol was not touched, and the
measured result was identical before and after: mean log loss 0.268004334632 either way.

## Limitations

- The booster's advantage on calibration and stability is measured but was not decisive under the
  pre-registered rule, and this report does not argue that it should have been. The rule was fixed
  before the measurement.
- The explanations offered above for the ranking/calibration pattern are untested hypotheses. WP2.5
  ran one configuration of one model family on one population; it cannot separate sample size from
  shrinkage from representation.
- Reliability mass sits overwhelmingly in `[0, 0.2)`. Only two bins clear the support floor, so the
  calibration comparison rests on a narrow basis for every candidate.
- The declared grid is twelve points. A larger search might find a better booster; that is a
  different, separately pre-registered question, and widening the grid after seeing this result
  would not have been a search, it would have been a rationalisation.
- The direction within the grid (slowest learning rate, shallower trees) is a description of twelve
  measured points, not evidence about the shape of the loss surface beyond them.
- The booster consumed the logistic model's one-hot encoding rather than a tree-native categorical
  representation. That keeps the comparison clean — one variable changed — at the cost of not
  showing what a booster could do with its natural input format.
- `model_pickle_sha256` is sensitive to process history: reproducing it requires a fresh process
  that unpickles nothing before running.
- Full-cohort evidence is local. Continuous integration never ingests the source data.
- The holdout was not opened. Model selection is not complete until the WP2.6 comparison runs.

Data provided by StatsBomb.
