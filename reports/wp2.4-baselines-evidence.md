# WP2.4 baselines and regularized logistic regression — evidence

Measured 2026-08-05 against the local full-cohort PostgreSQL at
`postgresql://touchline:localdev@localhost:5433/touchline` over the pinned StatsBomb Open Data
revision `b0bc9f22dd77c206ddedc1d742893b3bbe64baec`. Every database read was `READ ONLY`.

The evidence packet is `experiments/shot_quality/exp-20260805-wp2_4-baselines/` (`metrics.json`,
`config.json`, `artifact-manifest.json`) and this report. No holdout or calibration label was read
by any WP2.4 code: the loader executes the WP2.1 cohort query inside `WHERE match_id =
ANY(%s)` filtered to the 115 development match ids, and the full-cohort tests prove zero
calibration/holdout match ids in the fitted input (§ Holdout lock).

## Population and protocol

- 2,872 development shots / 115 matches (WC 2018 `(43,3)` + Euro 2020 `(55,43)`), five
  deterministic match-grouped folds of 23 matches, fold shot sizes `{570, 552, 602, 576, 572}` —
  asserted byte-exact through the loader.
- Pinned artifacts verified against the split manifest: assignments CSV SHA-256
  `e2d5517d96aa81d2229e1ef00a3c692f44f280630c3e75b7f6735e7cdc1787d8`; cohort SQL SHA-256
  `301d8a620b60d8da6011c7c4d12ef8108c658df4d923f612c3e3bf9e0427978e` (canonical LF; a CRLF checkout
  fails loudly — the byte-pin fix, WP2.4 §6).
- Metrics per the WP2.3 protocol: log loss + Brier primary; ROC AUC and PR AUC
  (`sklearn.metrics.average_precision_score`, never trapezoidal) with prevalence secondary;
  five equal-width reliability bins with counts; unweighted mean of fold metrics reported
  separately from pooled out-of-fold metrics; cross-fold SD with `ddof=0`.

## Candidate results (mean of five fold-level metrics; pooled OOF in parens)

| Candidate | mean log loss | Brier (pooled) | ROC AUC | PR AUC | prevalence | cross-fold SD (log loss) |
|---|---:|---:|---:|---:|---:|---:|
| Constant (training-fold rate) | 0.301886 | 0.081509 | 0.4755 | 0.0847 | 0.0895 | 0.017234 |
| Geometry-only logistic (C=0.1) | 0.269951 | 0.074725 | 0.7354 | 0.2612 | 0.0895 | 0.016579 |
| **Full logistic (C=0.1)** | **0.262047** | **0.072459** | **0.7543** | **0.3052** | 0.0895 | 0.016550 |
| Full logistic minus presence (C=0.1) | 0.263358 | 0.073044 | 0.7530 | 0.2942 | 0.0895 | 0.016167 |

Pooled OOF: constant log loss 0.301541 / Brier 0.081509 / ROC 0.4755 / PR 0.0847; geometry
0.269548 / 0.074725 / 0.7354 / 0.2612; full 0.261651 / 0.072459 / 0.7543 / 0.3052; full-minus
0.262972 / 0.073044 / 0.7530 / 0.2942. Development goal prevalence **257 / 2,872 = 8.95%**.

Per-fold (log loss / Brier / ROC / PR):

| Fold | constant | geometry | full | full-minus |
|---|---:|---:|---:|---:|
| 0 | 0.31362 / 0.08581 | 0.27366 / 0.07774 | 0.27235 / 0.07707 | 0.27150 / 0.07736 |
| 1 | 0.31236 / 0.08536 | 0.28493 / 0.07863 | 0.27281 / 0.07519 | 0.27547 / 0.07592 |
| 2 | 0.27907 / 0.07353 | 0.24288 / 0.06498 | 0.23304 / 0.06245 | 0.23624 / 0.06328 |
| 3 | 0.28326 / 0.07504 | 0.26057 / 0.07083 | 0.25430 / 0.06866 | 0.25386 / 0.06920 |
| 4 | 0.32112 / 0.08843 | 0.28771 / 0.08213 | 0.27774 / 0.07959 | 0.27973 / 0.08013 |

ROC AUC per fold: geometry {0.7702, 0.7207, 0.7405, 0.7042, 0.7516}; full {0.7640, 0.7488,
0.7688, 0.7217, 0.7749}.

## Reliability (five equal-width bins, pooled out-of-fold; D11 support floor 100)

| Bin | bounds | constant | geometry | full | full-minus |
|---|---|--:|--:|--:|--:|
| 0 | [0, 0.2) | n 2872 · pred 0.0895 · obs 0.0895 | n 2626 · pred 0.0701 · obs 0.0708 | n 2631 · pred 0.0678 · obs 0.0639 | n 2646 · pred 0.0691 · obs 0.0669 |
| 1 | [0.2, 0.4) | n 0 | n 215 · pred 0.2587 · obs 0.2558 | n 198 · pred 0.2681 · obs 0.3333 | n 183 · pred 0.2688 · obs 0.3224 |
| 2 | [0.4, 0.6) | n 0 | n 20 · pred 0.4785 · obs 0.3500 | n 23 · pred 0.4714 · obs 0.4783 | n 24 · pred 0.4656 · obs 0.4167 |
| 3 | [0.6, 0.8) | n 0 | n 9 · pred 0.6930 · obs 0.7778 | n 14 · pred 0.6974 · obs 0.5000 | n 14 · pred 0.7042 · obs 0.4286 |
| 4 | [0.8, 1.0] | n 0 | n 2 · pred 0.8158 · obs 1.0000 | n 6 · pred 0.8527 · obs 0.8333 | n 5 · pred 0.8728 · obs 1.0000 |

Empty bins are reported, not dropped. Under the D11 floor (≥ 100 pooled predictions) only bin 0 is
supported for every candidate; bins 1 (n ≈ 183–215) is supported for the logistic candidates.
Because predictions concentrate in `[0, 0.2)`, the §4.1 calibration comparison has thin support in
the upper bins — a documented limitation.

## D5 — presence-indicator STOP/EXCLUDE protocol (executed, pre-registered rule)

Pair: full logistic vs full-minus-presence, each with its own C (both 0.1). Δ = minus − full,
positive means full is better.

| Fold | Δ log loss | Δ Brier |
|---|---:|---:|
| 0 | −0.000851 | 0.000289 |
| 1 | +0.002664 | 0.000726 |
| 2 | +0.003193 | 0.000828 |
| 3 | −0.000441 | 0.000542 |
| 4 | +0.001991 | 0.000534 |

Mean Δ log loss **+0.001311** > 0; mean Δ Brier **+0.000584** > 0; positive log-loss folds **3 of 5**
(rule demands ≥ 4); positive Brier folds 5 of 5; **no sign flips**: raw fitted coefficient sign
`first_time_presence [+, +, +, +, +]` and `under_pressure_presence [−, −, −, −, −]` across the five
fold fits, and the final development refit agrees (`+1`, `−1`).

**Decision per the locked rule (condition 1 fails: 3/5): EXCLUDE both.** The shipped feature set is
the full-minus-presence set (geometry + categoricals). The addition narrows the per-fold log-loss
margin too inconsistently (positive on only 3 of 5 folds) to admit under the protocol; the
annotation-intensity caveat (WP2.2 Slice B) is therefore moot for this cohort but remains the
reason these are presence indicators, never booleans. This decision was executed by the
pre-registered rule; it was not tuned.

## PLAN §4.1 pairwise replacement — measured outcome and investigation

Candidates were compared pairwise (constant → geometry-only → full) under the four-condition PLAN
§4.1 rule. **The rule names `constant` as the WP2.4 incumbent** (both replacements fail).

Investigation, recorded as the contract requires ("if it does not, investigated and reported, not
tuned away"):

- Conditions 1 and 2 pass for both logistic candidates over the constant (e.g. full mean log loss
  0.262047 < 0.301886 − 0.017234; full mean Brier 0.072459 < 0.081509).
- **Condition 3 fails structurally.** The constant predicts the base rate (0.0895) for every row,
  so its predictions land in a single supported bin where observed = predicted by construction:
  `max_abs_deviation = 0.000048`. No real model can undercut a constructed near-zero calibration
  deviation, so condition 3 is unsatisfiable against a constant incumbent. This is a degeneracy of
  applying the §4.1 calibration condition to a constant baseline, not a claim that the constant is
  the better predictor: on the primary probability-quality metrics the full logistic dominates
  (log loss 0.262 vs 0.302, Brier 0.072 vs 0.082, ROC 0.754 vs 0.476).
- The pre-registered expectation that the full logistic would be named incumbent under full §4.1
  therefore did **not** hold; the rule was applied exactly and the mismatch reported here.

For M3 shaping, the **predictive model to use is the full-minus-presence logistic** (the D5-admitted
feature set); the §4.1 "constant" label is a rule artifact recorded for honesty, not a production
recommendation.

## Final development-refit model (interpretation)

Full logistic refit on all 2,872 development rows, C = 0.1, intercept −2.405. Standardized
coefficients (odds ratio = e^coefficient; per one standard deviation of the continuous features,
per presence of the categorical level):

| Feature | coefficient | odds ratio |
|---|---:|---:|
| distance_to_goal | −0.588 | 0.556 |
| visible_goal_angle | +0.482 | 1.619 |
| body_part_name::Head (vs Right Foot) | −0.452 | 0.637 |
| body_part_name::Left Foot (vs Right Foot) | +0.170 | 1.185 |
| body_part_name::rare (=Other) | −0.204 | 0.816 |
| technique_name::Half Volley (vs Normal) | −0.139 | 0.870 |
| technique_name::Volley (vs Normal) | −0.304 | 0.738 |
| technique_name::rare | +0.123 | 1.131 |
| play_pattern_name::From Corner (vs Regular Play) | −0.521 | 0.594 |
| play_pattern_name::From Counter (vs Regular Play) | +0.276 | 1.317 |
| play_pattern_name::From Free Kick | −0.047 | 0.954 |
| play_pattern_name::From Goal Kick | −0.357 | 0.700 |
| play_pattern_name::From Keeper | +0.336 | 1.399 |
| play_pattern_name::From Kick Off | −0.026 | 0.975 |
| play_pattern_name::From Throw In | −0.003 | 0.998 |
| play_pattern_name::rare | +0.046 | 1.047 |

Regularized-coefficient caveat: L2 (C = 0.1) shrinks coefficients toward zero, so magnitudes are
conservative, not causal; the reference levels (Right Foot / Normal / Regular Play) are dropped
columns and are the comparison baseline. `first_time_presence` (+0.070, odds 1.073) and
`under_pressure_presence` (−0.474, odds 0.622) are reported for interpretation only — they are
**not part of the shipped feature set** (D5 excluded them) — and they are **presence indicators,
never booleans**: absence of an annotation is encoded 0 but is not "annotated as not the case"
(WP2.2 Slice B).

Serially cached full-cohort run evidence: `metrics.json` (rounded to 12 dp, canonical bytes),
`config.json` (self-contained and rerunnable), `artifact-manifest.json` (pickle SHA-256
`bd53ccc5011e261e…`, recreation command recorded).

## D4 — planning-stage semantics review (resolved, no gate)

`open_goal` and `one_on_one` are **excluded**. The review, completed at planning stage, records
the unestablished property precisely: **outcome-independent provider annotation semantics cannot be
established, because the repository contains insufficient evidence** — WP2.1 flags both fields as
"provider annotation semantics and optional encoding require review" and no such review exists
(`docs/modeling/wp2_1-cohort-and-leakage-contract.md`). That is a documented-fact rationale, not an
inference about provider behaviour. Supporting facts: dev support 32 (1.1%) / 98 (3.4%); both are
true-only presence annotations. Their situation content overlaps the admitted geometry only
partially (distance and visible goal angle do not describe goalkeeper or defender state); the
exclusion rests on the unestablished annotation semantics and low support, not on a redundancy
claim.

## Prevalence and annotation report (development, label-free)

| Indicator | dev count | overall rate | WC 2018 | Euro 2020 | folds 0–4 |
|---|---:|---:|---:|---:|---|
| `first_time` | 751 | 26.15% | 21.79% | 31.93% | 24.6 / 29.7 / 24.4 / 26.0 / 26.2 |
| `under_pressure` | 634 | 22.08% | 20.09% | 24.72% | 22.8 / 21.6 / 21.6 / 22.9 / 21.5 |

These reproduce WP2.2 Slice B's development figures exactly (21.8/31.9 and 20.1/24.7), confirming
the loader and presence pipeline against the published coverage audit.

## Holdout lock

`test_wp2_4_training_full_cohort.py` proves: 2,872 rows / 115 matches / exact fold sizes through
the loader; exact shot-id set equality between the loader and the WP2.1 cohort query restricted to
development match ids; and **zero calibration or holdout match ids in the fitted input** (all rows
are from scopes `(43,3)` / `(55,43)`). The database holds 230 matches including WC 2022 and
Euro 2024; the loader surfaces only development. No holdout number appears anywhere in WP2.4 output.

## Commands

- Structure: `TOUCHLINE_FULL_COHORT_DB_URL='postgresql://touchline:localdev@localhost:5433/touchline'
  uv run pytest backend/tests/test_wp2_4_training_full_cohort.py -m full_cohort` → 5/5.
- Protocol run: `TOUCHLINE_FULL_COHORT_DB_URL='postgresql://touchline:localdev@localhost:5433/touchline'
  uv run poe train --config experiments/shot_quality/exp-20260805-wp2_4-baselines/config.json`.

## Limitations

- Measured on one pinned source revision and one four-tournament cohort; no generalisation claimed.
- The holdout is a tournament holdout: holding out Euro 2024 changes time and competition
  composition together (ADR 0004) — stated, not removed.
- The §4.1 rule names the constant as incumbent due to the constructed near-zero calibration
  deviation of a constant baseline (condition-3 degeneracy, investigated above); the predictive
  model remains the full-minus-presence logistic on the primary metrics.
- Annotation intensity (WP2.2) makes `first_time` / `under_pressure` presence indicators; D5
  excluded them here (3/5 positive folds).
- Reliability upper bins are sparse (mass in `[0, 0.2)`); D11's 100-prediction floor leaves few
  supported bins for the calibration comparison.
- C grid is the pre-registered `{0.01, 0.1, 1.0, 10.0}`; only 0.1 was selected — stiffer
  regularization was never preferred on this population.
- Full-cohort evidence is local-only (CI never ingests StatsBomb).

Data provided by StatsBomb.
