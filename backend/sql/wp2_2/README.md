# WP2.2 geometry and coverage SQL

Four read-only queries supporting WP2.2 — two for Slice A geometry, two for Slice B coverage. All
are repository-local model-development infrastructure and none expands the public API surface.

1. `01_geometry_inputs.sql` projects the geometry columns for exactly the WP2.1 non-penalty cohort:
   `shot_id`, `match_id` and the two raw coordinates. Expected row count 5,606. It deliberately
   duplicates WP2.1's predicate set rather than importing it, so a divergence fails the row-count
   anchor in `backend/tests/test_wp2_2_geometry_integration.py` instead of silently re-scoping the
   evidence. `is_goal` is not projected — Slice A has no use for the target, and not reading it is
   cheaper than arguing that it was not misused.
2. `02_coordinate_boundary_audit.sql` returns one aggregate row deciding the geometry contract's
   boundary policy from measurement: coordinate ranges, rows on or past the goal line, rows exactly
   on a goalpost, rows in the region where the naive angle formula fails, and the shot count below
   the halfway line used as the attacking-direction check.

3. `03_categorical_support.sql` returns one row per (field, recorded value) for the four candidate
   categorical fields, with overall support and a per-tournament breakdown. The WP2.2 plan admits
   context features only after coverage is documented, and this is that documentation; the
   per-tournament columns exist so that a level missing from a whole tournament is visible before
   WP2.3 designs a tournament-grouped split rather than after a fold fails on it.
4. `04_annotation_encoding_audit.sql` returns one row per candidate optional boolean with its
   true / false / absent counts and per-tournament true counts. It resolves the single question
   WP2.1 left open for all six fields: whether NULL means "recorded as false" or "not recorded".
   Because ingestion maps an absent key to NULL and never invents a value, a non-zero
   `recorded_false` would prove the source distinguishes them — none does.

Neither Slice B query reads or projects the target. Deciding which levels or fields to keep from
their conversion rate is possible here and would be selection measured over a cohort that contains
WP2.3's holdout. The same reasoning kept `is_goal` out of `01_geometry_inputs.sql`.

That is a property of these committed queries and not a claim about the whole development process.
Aggregate outcome rates by candidate context level were viewed during untracked exploratory work
before the split was frozen; they were not recorded in the evidence and no feature was selected in
this slice. The consequences for later feature decisions are stated under "Target access" in
[`reports/wp2.2-slice-b-coverage-evidence.md`](../../../reports/wp2.2-slice-b-coverage-evidence.md).

All four are `SELECT`-only and are executed inside a `READ ONLY` transaction by the integration
tests. None creates schema, applies migrations, seeds fixtures, or writes anything.

The measured output is recorded in
[`reports/wp2.2-geometry-evidence.md`](../../../reports/wp2.2-geometry-evidence.md) for Slice A and
[`reports/wp2.2-slice-b-coverage-evidence.md`](../../../reports/wp2.2-slice-b-coverage-evidence.md)
for Slice B.

These queries define no split, no model feature set, and no evaluation baseline. Slice B's coverage
evidence documents what a feature set may be decided from and explicitly decides none of it; the
feature set, the split and the baseline belong to the rest of WP2.2, WP2.3 and WP2.4.

Data provided by StatsBomb.
