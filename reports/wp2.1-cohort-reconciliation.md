# WP2.1 full-cohort reconciliation

Executed 2026-08-02 against the local PostgreSQL clean-rebuild state for pinned StatsBomb Open Data
commit `b0bc9f22dd77c206ddedc1d742893b3bbe64baec`.

| Tournament | Eligible non-penalty shots | Goals | Regulation penalties | Shootout penalties |
|---|---:|---:|---:|---:|
| World Cup 2018 `(43,3)` | 1,638 | 135 | 29 | 39 |
| Euro 2020 `(55,43)` | 1,234 | 122 | 17 | 38 |
| World Cup 2022 `(43,106)` | 1,430 | 152 | 23 | 41 |
| Euro 2024 `(55,282)` | 1,304 | 98 | 12 | 24 |
| **Total** | **5,606** | **507** | **81** | **142** |

The tournament penalty columns are reproduced by
`backend/sql/wp2_1/04_penalty_breakdown.sql`; the global totals and exclusion/missingness counts are
reproduced by `02_cohort_reconciliation.sql`.

All 5,829 typed shots reconcile as 5,606 eligible non-penalty shots plus 223 penalties. There are no
period-5 non-penalty shots. Required-field missing counts are zero for player, period, coordinate
pair, outcome, body part, technique, and shot type.

Own goals are outside the typed Shot population. The source has 36 `Own Goal For` event rows and 36
paired `Own Goal Against` event rows; neither event type is coerced into the shot target.

Low-support observed categories remain explicit rather than being silently pooled: `Corner` shot
type has 6 rows; `Other` play pattern 15; `Other` body part 38; and techniques include `Backheel` 20,
`Overhead Kick` 30, `Diving Header` 36, and `Lob` 42. WP2.2 must decide any category handling using
training data only.

Optional boolean annotations are stored as true or NULL in this snapshot. Examples include
`follows_dribble` 7 true, `redirect` 11, `saved_to_post` 11, `saved_off_target` 12, `open_goal` 54,
`deflected` 93, `one_on_one` 229, `aerial_won` 520, `under_pressure` 1,259, and `first_time` 1,599.
NULL is not converted to false in WP2.1; semantics and coverage are a WP2.2 gate.

This is descriptive cohort evidence, not model evaluation. No split was created and no holdout was
opened.

Data provided by StatsBomb.
