# WP2.1 model cohort SQL

These four read-only queries version the population contract before any feature engineering,
splitting, or model fitting:

1. `01_model_shot_cohort.sql` returns one row per eligible non-penalty Shot event. It carries stable
   source IDs, the match grouping/date fields needed later, raw event-time candidates, and one binary
   target. Outcome is not exposed as an input column.
2. `02_cohort_reconciliation.sql` makes every exclusion count explicit, including regulation
   penalties, shootout penalties, missing required fields, and own-goal event rows.
3. `03_category_coverage.sql` reports every observed value and its support without silently merging
   rare categories. It deliberately exposes no target aggregates before splits are locked.
4. `04_penalty_breakdown.sql` reproduces the separate regulation/shootout counts for each declared
   tournament.

The scope is exactly `(43,3), (55,43), (43,106), (55,282)`. The cohort SQL is internal model
development infrastructure. It does not expand the public `/shots` endpoint while the row-level
publication question in `DATA_SOURCE.md` remains unresolved.

The SQL does not define geometry, final model features, splits, or an evaluation baseline. Those
belong to WP2.2 through WP2.4. In particular, the descriptive public `/baseline` rate must never be
used as a prediction on these rows.

Data provided by StatsBomb.
