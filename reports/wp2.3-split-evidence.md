# WP2.3 split evidence

Measured 2026-08-04 against the local full-cohort PostgreSQL state for pinned StatsBomb Open Data
commit `b0bc9f22dd77c206ddedc1d742893b3bbe64baec`. Every query ran in a `READ ONLY` connection; no
migration, insert, update, delete or seed was executed. The deployed database was not queried.

Reproduce:

```bash
TOUCHLINE_DB_URL='postgresql://touchline:localdev@localhost:5433/touchline' \
    uv run pytest backend/tests/test_wp2_3_split_integration.py -q
TOUCHLINE_FULL_COHORT_DB_URL='postgresql://touchline:localdev@localhost:5433/touchline' \
    uv run pytest backend/tests/test_wp2_3_split_full_cohort.py -m full_cohort
TOUCHLINE_FULL_COHORT_DB_URL='postgresql://touchline:localdev@localhost:5433/touchline' \
    uv run python scripts/write_wp2_3_split_manifest.py
```

GitHub Actions does not run the full-cohort module: its PostgreSQL is empty by design — CI never
downloads or ingests the StatsBomb dataset — so `TOUCHLINE_FULL_COHORT_DB_URL` is unset there and
the module skips with that reason stated. The numbers below come from a local run.

## The locked split

The split is a match-level object: all 230 ingested tournament matches are assigned exactly once.
Per-split counts are label-free (eligible shots, not goals):

| Split | Scopes | Matches | Eligible shots | First match date | Last match date |
|---|---|---|---:|---|---|
| development | `(43,3)` + `(55,43)` | 115 | 2,872 | 2018-06-14 | 2021-07-11 |
| calibration | `(43,106)` | 64 | 1,430 | 2022-11-20 | 2022-12-18 |
| tournament holdout | `(55,282)` | 51 | 1,304 | 2024-06-14 | 2024-07-14 |
| **Total** | — | **230** | **5,606** | — | — |

**Fold rule:** development matches sorted by `(match_date, match_id)`, `fold = index % 5`. The
five folds are deterministic **match-grouped** folds — not temporal, not forward-chaining; each
fold spans the full development time range, which is exactly why they are grouped, not temporal:

| Fold | Matches | Eligible shots | First match date | Last match date |
|---|---:|---:|---|---|
| 0 | 23 | 570 | 2018-06-14 | 2021-07-03 |
| 1 | 23 | 552 | 2018-06-15 | 2021-07-03 |
| 2 | 23 | 602 | 2018-06-15 | 2021-07-06 |
| 3 | 23 | 576 | 2018-06-15 | 2021-07-07 |
| 4 | 23 | 572 | 2018-06-16 | 2021-07-11 |

**Chronology, strict and measured — both boundaries shown separately:** development ends on
`2021-07-11` (max) before calibration starts on `2022-11-20` (min), and calibration ends on
`2022-12-18` (max) before the holdout starts on `2024-06-14` (min):

- `max(development) = 2021-07-11 < min(calibration) = 2022-11-20`
- `max(calibration) = 2022-12-18 < min(holdout) = 2024-06-14`

Both inequalities are asserted independently by the full-cohort test
`test_strict_chronology_between_top_level_splits`. Chronological separation applies only between
the top-level splits.

## Shot-level partition proof

Over `backend/sql/wp2_3/02_split_shot_membership.sql` (5,606 rows):

- all shot ids are unique — **no duplicates**;
- every shot's match id is in the assignment plan — **no unassigned shots**;
- every shot maps through its match to exactly one top-level split;
- per-split totals: development 2,872, calibration 1,430, holdout 1,304 (sum 5,606);
- the set of shot match ids equals the set of matches with `eligible_shots > 0`.

**Cohort equivalence:** the WP2.3 shot-membership query's shot-id set is exactly equal (both
directions) to the WP2.1 cohort query's shot-id set — 5,606 ids, zero missing, zero extra. Query
01's `eligible_shots` agrees with query 02 grouped by `match_id` for **every one of the 230
matches**, including matches with zero eligible shots.

## Determinism and failure modes

- Reversed and rotated input row orders produce the identical assignment plan (asserted in unit,
  fixture-integration and full-cohort tests).
- A NULL `match_date` raises `SplitAssignmentError` naming the match; the real cohort has none.
- Out-of-scope scope pairs, duplicate match ids, empty input and an empty development set all
  raise explicitly.

## Locked artifacts

`scripts/write_wp2_3_split_manifest.py` generated, from the read-only population query:

- `data/model/wp2_3_match_assignments.csv` — 230 rows, header
  `match_id,competition_id,season_id,match_date,split,fold`, ordered by `match_id`, LF line
  endings. **Byte-pinned:** a fresh recomputation from the database reproduces the committed bytes
  exactly. SHA-256:
  `e2d5517d96aa81d2229e1ef00a3c692f44f280630c3e75b7f6735e7cdc1787d8`
- `data/model/wp2_3_split_manifest.json` — version 1, `generated_utc` 2026-08-04T13:20:23Z,
  `source_commit` `b0bc9f22dd77c206ddedc1d742893b3bbe64baec`, `cohort_sql_sha256`
  `379c25d26d17805f23b280691f329b586928a2267917c45279388fc44bac8d58`. Validated field-by-field
  against the exact allowed-key schema at every nesting level (unexpected keys fail), with every
  value independently recomputed from the database; not byte-pinned because it carries
  `generated_utc`.

## Target access

The committed WP2.3 SQL never projects or inspects the target: each query duplicates WP2.1's
eligibility predicate set, and the inherited `outcome_name IS NOT NULL` check is the only place
either query touches outcome data. The split manifest contains no goal counts; the assignment
input type carries no outcome field. The full-cohort tests execute the WP2.1 cohort query solely
to compare its `shot_id` column. **No outcome value enters WP2.3's split logic, artifacts,
protocol decisions, or assertions.**

That is a property of WP2.3's artifacts, not a claim about the whole development process: WP2.1's
published reconciliation exposed descriptive per-tournament goal counts (including Euro 2024's),
and WP2.2 recorded exploratory viewing of aggregate outcome rates before this split was frozen.
See "Target access" in [`reports/wp2.3-split-contract.md`](wp2.3-split-contract.md). The holdout
is locked from WP2.3 onward, **not blind**; it is prohibited from model, feature, calibration,
threshold, and selection decisions, and the reliability-bin count is fixed a priori without holdout
labels (ADR 0004 amendment, 2026-08-04).

## Limitations

- Measured on one pinned source revision and one four-tournament cohort; nothing generalises to
  other competitions, and the counts are pinned to this revision by design.
- The holdout is a tournament holdout: holding out Euro 2024 changes time and competition
  composition together. That confounding is stated, not removed.
- Calibration is drawn from a single tournament's (WC 2022's) annotation regime; annotation
  intensity differences across tournaments (measured in WP2.2 Slice B for `under_pressure` and
  `first_time`) are a documented input to WP2.4 feature decisions.
- `shot_type_name = 'Corner'` exists only in WC 2022 and Euro 2024, so development never trains
  on it; WP2.4 must carry an explicit unseen-level policy.

Data provided by StatsBomb.
