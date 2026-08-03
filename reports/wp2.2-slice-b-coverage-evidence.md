# WP2.2 Slice B coverage and annotation-encoding evidence

Measured 2026-08-04 against the local full-cohort PostgreSQL state for pinned StatsBomb Open Data
commit `b0bc9f22dd77c206ddedc1d742893b3bbe64baec`. Every query ran read-only, in a `READ ONLY`
transaction; no migration, insert, update, delete or seed was executed. The deployed database was
not queried.

This document **admits no feature**. The WP2.2 plan admits context features only after coverage is
documented, and WP2.1 blocked six boolean fields as `Uncertain` pending their absent-versus-false
encoding. This is that documentation and nothing further: no split was created, no preprocessing
was fitted, and no model exists.

## Target access

**The committed coverage queries do not read or project the target.**

During exploratory development, aggregate outcome rates by candidate context level were viewed
before the formal split was frozen. They were not recorded in this evidence or used to select
features in this slice. Future feature decisions are therefore restricted to pre-registered
semantic, coverage and stability rules, and the eventual tournament holdout must not be described
as entirely unseen at the descriptive-summary level.

Three separate statements, kept apart deliberately because collapsing them would overclaim:

| | Status |
|---|---|
| Committed coverage evidence (`03_`/`04_` queries, this document) | target-free — no outcome column read or projected |
| Earlier untracked exploratory inspection | aggregate outcome rates by candidate level **were viewed** |
| This slice's feature set | no feature selection decision was taken, from either source |

The reason the committed queries stay target-free is that conversion rate per level is measurable
only over a cohort containing the tournament WP2.3 reserves as its holdout, so deciding a feature
set from it is selection on the holdout. Keeping the queries clean does not undo the exploratory
viewing; it limits what this evidence contributes, and the restriction above is what carries the
rest.

Reproduce against a local database that has been migrated and ingested:

```bash
TOUCHLINE_FULL_COHORT_DB_URL='postgresql://touchline:localdev@localhost:5433/touchline' \
    uv run pytest backend/tests/test_wp2_2_coverage_integration.py -m full_cohort
```

GitHub Actions does **not** run these tests. Its PostgreSQL service container is empty by design —
CI never downloads or ingests the StatsBomb dataset — so `TOUCHLINE_FULL_COHORT_DB_URL` is unset
there and the module skips with that reason stated. The numbers below come from a local run.

## Population

Both queries duplicate WP2.1's predicate set rather than importing it, exactly as Slice A does.
Each of the four categorical fields partitions the same **5,606 rows**, and the three-way
true/false/absent count for each boolean sums to the same 5,606; both are asserted, so a divergence
from WP2.1 fails the anchor instead of quietly re-scoping this evidence.

Tournament columns are WC 2018 (43/3), Euro 2020 (55/43), WC 2022 (43/106), Euro 2024 (55/282).

## Categorical support

`backend/sql/wp2_2/03_categorical_support.sql`:

| Field | Value | Shots | WC 2018 | Euro 2020 | WC 2022 | Euro 2024 |
|---|---|---:|---:|---:|---:|---:|
| `body_part_name` | Right Foot | 2,865 | 825 | 632 | 732 | 676 |
| `body_part_name` | Left Foot | 1,692 | 489 | 377 | 433 | 393 |
| `body_part_name` | Head | 1,011 | 310 | 221 | 252 | 228 |
| `body_part_name` | Other | 38 | 14 | 4 | 13 | 7 |
| `play_pattern_name` | Regular Play | 1,941 | 654 | 411 | 446 | 430 |
| `play_pattern_name` | From Free Kick | 1,071 | 309 | 234 | 285 | 243 |
| `play_pattern_name` | From Throw In | 1,016 | 257 | 230 | 298 | 231 |
| `play_pattern_name` | From Corner | 934 | 279 | 208 | 223 | 224 |
| `play_pattern_name` | From Goal Kick | 233 | 42 | 51 | 80 | 60 |
| `play_pattern_name` | From Counter | 228 | 60 | 56 | 56 | 56 |
| `play_pattern_name` | From Keeper | 103 | 22 | 22 | 21 | 38 |
| `play_pattern_name` | From Kick Off | 65 | 13 | 16 | 17 | 19 |
| `play_pattern_name` | Other | 15 | 2 | 6 | 4 | 3 |
| `shot_type_name` | Open Play | 5,388 | 1,556 | 1,193 | 1,382 | 1,257 |
| `shot_type_name` | Free Kick | 212 | 82 | 41 | 46 | 43 |
| `shot_type_name` | **Corner** | **6** | **0** | **0** | **2** | **4** |
| `technique_name` | Normal | 4,443 | 1,361 | 948 | 1,087 | 1,047 |
| `technique_name` | Half Volley | 685 | 118 | 186 | 212 | 169 |
| `technique_name` | Volley | 350 | 117 | 76 | 92 | 65 |
| `technique_name` | Lob | 42 | 11 | 6 | 13 | 12 |
| `technique_name` | Diving Header | 36 | 12 | 8 | 14 | 2 |
| `technique_name` | Overhead Kick | 30 | 13 | 4 | 7 | 6 |
| `technique_name` | Backheel | 20 | 6 | 6 | 5 | 3 |

No level is NULL: WP2.1's cohort predicate already requires `body_part_name`, `technique_name` and
`shot_type_name` to be known, and `play_pattern_name` is populated on every cohort row.

One measurement about the predicate set itself, recorded because it changes what the tests here can
claim: the four-tournament scope holds **142 period-five shots, all of them Penalty shots and none
otherwise**. On this pinned revision WP2.1's `e.period <> 5` exclusion is therefore fully redundant
with its `shot_type_name <> 'Penalty'` exclusion, and no full-cohort test can demonstrate the two
are independent — removing either one alone changes no count. That independence is real and is
proven by WP2.1's fixture-based test, which seeds a period-five non-penalty shot precisely because
the real data contains none. `scripts/verify_tests_fail.py` therefore carries no period-five
mutation against the Slice B queries: a mutation that cannot fail is a green tick that means
nothing.

## Annotation encoding

`backend/sql/wp2_2/04_annotation_encoding_audit.sql`:

| Field | True | **False** | Absent | WC 2018 | Euro 2020 | WC 2022 | Euro 2024 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `aerial_won` | 520 | **0** | 5,086 | 124 (7.6%) | 134 (10.9%) | 129 (9.0%) | 133 (10.2%) |
| `first_time` | 1,599 | **0** | 4,007 | 357 (21.8%) | 394 (31.9%) | 468 (32.7%) | 380 (29.1%) |
| `follows_dribble` | 7 | **0** | 5,599 | 2 (0.1%) | 1 (0.1%) | 3 (0.2%) | 1 (0.1%) |
| `one_on_one` | 229 | **0** | 5,377 | 55 (3.4%) | 43 (3.5%) | 79 (5.5%) | 52 (4.0%) |
| `open_goal` | 54 | **0** | 5,552 | 17 (1.0%) | 15 (1.2%) | 13 (0.9%) | 9 (0.7%) |
| `under_pressure` | 1,259 | **0** | 4,347 | 329 (20.1%) | 305 (24.7%) | 238 (16.6%) | 387 (29.7%) |

Percentages are of that tournament's cohort rows: 1,638 / 1,234 / 1,430 / 1,304.

## What the measurement settled

**All six candidate booleans are true-only annotations.** `touchline.ingest.parse` maps an absent
JSON key to NULL and never invents a value, so a provider-recorded `false` would have arrived as
FALSE. Not one did, in 33,636 field-observations. WP2.1's open question therefore resolves in the
restrictive direction: NULL means *not annotated*, and it cannot be separated from *annotated as
not the case*. Any feature built on these fields is a **presence indicator**, not a boolean, and
has to be described as one wherever its coefficient is interpreted. Encoding absence as `0` is
defensible; calling that `0` "false" is not.

This is asserted, not just recorded — `test_no_candidate_boolean_ever_records_an_explicit_false`
fails if a future pinned revision starts distinguishing the two, forcing the decision to be retaken
rather than inherited.

## What the measurement hands forward, unresolved

These are open decisions. They are stated here with their evidence so they are taken deliberately;
none of them is taken by this document.

1. **`shot_type_name = 'Corner'` is absent from two of the four tournaments** (6 shots total, none
   before WC 2022). WP2.3 splits by tournament, so a fold can meet this level having never trained
   on it. Some explicit rare-level policy is required — it is not optional, and "the encoder
   handled it" is not a policy.
2. **`follows_dribble` has 7 positives across the whole cohort**, 1–3 per tournament. WP2.1 already
   said "do not merge or use without review"; the measurement supports that reading.
3. **`under_pressure`'s true-rate ranges 16.6% → 29.7% across tournaments**, a 1.8× spread, and
   `first_time`'s ranges 21.8% → 32.7%. These are provider annotations rather than measurements, so
   the spread is at least partly annotation intensity rather than football. Because the split is by
   tournament, admitting such a field means admitting something partly confounded with the split.
4. **`open_goal` (54) and `one_on_one` (229) are thin**, and both encode a *situation* rather than
   an action. WP2.1 flagged their provider annotation semantics as unreviewed; that review is a
   football judgement about what is observable at the moment of the shot, and it has not been made.
5. **Rare categorical tails** — `technique_name` Backheel (20), Overhead Kick (30), Diving Header
   (36), Lob (42); `body_part_name` Other (38); `play_pattern_name` Other (15) — need the same
   explicit level policy as (1).
6. **`Other` as a level** appears in two fields and is a provider bucket, not a football category.
   Whether it is kept, merged, or dropped is a decision, and the two `Other`s are unrelated to each
   other.

## Limitations

- Measured on one pinned source revision and one four-tournament cohort. Nothing here generalises
  to other competitions, and the counts are pinned to this revision by design.
- Coverage is not evidence of predictive value, and nothing here claims any. The committed queries
  read no target, no split exists, and no model has been fitted — but see "Target access" above:
  the exploratory viewing of aggregate outcome rates is a real constraint on what later feature
  decisions may claim, and it is not undone by this document being target-free.
- The three remaining WP2.1 `Uncertain` families — key-pass/event relations, embedded shot
  freeze-frame players, and event position — are **not** covered by this audit. Each needs its own
  contract, and freeze frames in particular are neither StatsBomb 360 nor tracking data.
- Annotation intensity is measured across tournaments only. Within-tournament variation between
  collection rounds or matches is not measured here.

Data provided by StatsBomb.
