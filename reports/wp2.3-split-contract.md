# WP2.3 split contract (public)

## Research question

WP2.1's cohort contract asks for the probability that a recorded Shot becomes a goal, using only
information available at or before the shot. WP2.3 locks the population into a named three-way
split and fixes the evaluation protocol that every WP2.4+ candidate must follow. It creates no
split model, fits nothing, and evaluates nothing.

## The locked split

| Split | Population | Matches | Eligible shots |
|---|---|---|---|
| development | World Cup 2018 `(43,3)` + Euro 2020 `(55,43)` | 115 | 2,872 |
| calibration | World Cup 2022 `(43,106)` | 64 | 1,430 |
| tournament holdout | Euro 2024 `(55,282)` | 51 | 1,304 |

All counts are label-free cohort facts measured on the pinned source revision
`b0bc9f22dd77c206ddedc1d742893b3bbe64baec` over exactly WP2.1's 5,606 eligible non-penalty shots.
The split is a match-level object: all 230 ingested tournament matches are assigned exactly once,
and every eligible shot belongs to exactly one top-level split through its match. Measured
evidence: [`reports/wp2.3-split-evidence.md`](wp2.3-split-evidence.md).

**Fold rule.** Development matches are sorted by `(match_date, match_id)` and assigned
`fold = index % 5`, giving exactly 23 matches per fold. **The five development folds are
deterministic match-grouped folds**: a partition of development matches that protects shared match
context. They are NOT temporal folds and NOT forward-chaining folds; no chronological claim is
made within development or between folds. Chronological separation applies only between the
top-level splits, proven separately for both boundaries: `max(development) < min(calibration)`
and `max(calibration) < min(holdout)`.

## Target access

**No outcome value is used in the split assignment, fold balancing, calibration, selection, or
protocol decisions.** The assignment is a pure function of match identity, scope and date; the
assignment input type carries no outcome field; the split manifest contains no goal counts.

The WP2.3 SQL queries duplicate WP2.1's eligibility predicate set verbatim, which necessarily
includes the inherited `outcome_name IS NOT NULL` check — the only place either query touches
outcome data. They never inspect outcome categories or values and never project the target or any
outcome-derived field. The WP2.1 cohort query is executed by the WP2.3 full-cohort tests solely
to compare shot-id sets, consuming only its `shot_id` column.

This is not a claim that no historical query ever read the target. WP2.1's published
reconciliation reported descriptive per-tournament goal counts (including Euro 2024's), and WP2.2
recorded exploratory viewing of aggregate outcome rates before this split was frozen.

## Holdout status — locked, not blind

Euro 2024 is the **tournament holdout, locked from WP2.3 onward**. It is *locked, not blind*, and
this contract makes no blindness claim: the descriptive exposures above are history, stated
rather than hidden. The lock means that from WP2.3 onward, Euro 2024 outcomes are prohibited from
**model, feature, calibration, threshold, and selection decisions**. The single remaining
permitted outcome use is the pre-registered final evaluation after model selection, reported
as-is.

The holdout is a **tournament holdout, not a temporal one**: holding out Euro 2024 changes time
and competition composition together, and that confounding is stated wherever the holdout is
evaluated rather than glossed over.

## Evaluation protocol (fixed for WP2.4+, without holdout labels)

- **Primary probability-quality metrics:** log loss and Brier score. **Discrimination** (ROC AUC
  and PR AUC with class prevalence) is secondary; discrimination without calibration is
  insufficient for a chance-valuation use case.
- **Reliability:** a calibration table with **five equal-width bins fixed a priori**. The bin
  count is not derived from any measured holdout outcome; its label-free justification is the
  holdout's 51 matches and 1,304 eligible shots, fixed in advance. Alternative binning may appear
  in WP2.7 only as labelled sensitivity analysis, never as selection.
- **Selection:** model, feature, and hyperparameter selection happen on the development folds
  only, under a pre-registered replacement rule (a candidate replaces the incumbent regularized
  logistic regression only if it wins on log loss beyond the incumbent's cross-fold spread, with
  no worse Brier, no worse calibration, and no worse stability). Calibration is fitted on the
  WC 2022 split only, after selection, never on development or the holdout.
- **Holdout:** evaluated exactly once, at the end, under the same metrics protocol, and reported
  whatever it shows. It is never used for selection, calibration, threshold decisions (none
  exist: the output is a calibrated probability, so no threshold is tuned), or any re-derivation
  of protocol parameters.
- **Baselines:** the constant-prediction baseline is estimated from training rows only; the
  descriptive public prevalence endpoint is not an evaluation baseline.
- **WC 2022 public status:** WC 2022 is the calibration split. Any future public-facing output
  derived from WC 2022 rows is a **calibration-set output** and must not be presented as
  held-out evaluation.

## Identifier convention

`shot_id` in WP2.3 SQL, tests and evidence is `events.event_id` — the `shots` primary key —
aliased per WP2.1 convention. No new identifier is introduced.

## WP2.4 obligations

- `shot_type_name = 'Corner'` (6 shots, WC 2022 + Euro 2024 only) is **absent from development**:
  WP2.4 must carry an explicit unseen-level policy; "the encoder handled it" is not a policy.
- `under_pressure` (16.6%–29.7% true-rate across tournaments) and `first_time` (21.8%–32.7%) are
  partly annotation intensity rather than football, and the split is by tournament: admitting such
  a field means admitting something partly confounded with the split. Any feature decision must
  be recorded against this.
- The six optional boolean annotations are true-only in the pinned source: absence cannot be
  separated from "annotated as not the case", so any feature built on them is a presence
  indicator, not a boolean.

## Boundaries

- WP2.3 changes no schema, migration, dependency, public endpoint, or WP2.1/WP2.2 contract.
- The locked artifacts are `data/model/wp2_3_match_assignments.csv` (byte-pinned) and
  `data/model/wp2_3_split_manifest.json` (validated field-by-field against an exact allowed-key
  schema; not byte-pinned because it carries `generated_utc`).
- Reproduction commands and measured evidence: [`reports/wp2.3-split-evidence.md`](wp2.3-split-evidence.md).

Data provided by StatsBomb.
