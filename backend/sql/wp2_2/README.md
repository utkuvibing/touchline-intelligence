# WP2.2 geometry SQL

Two read-only queries supporting WP2.2 Slice A. Both are repository-local model-development
infrastructure and neither expands the public API surface.

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

Both are `SELECT`-only and are executed inside a `READ ONLY` transaction by the integration test.
Neither creates schema, applies migrations, seeds fixtures, or writes anything.

The measured output is recorded in [`reports/wp2.2-geometry-evidence.md`](../../../reports/wp2.2-geometry-evidence.md);
the decisions it supports are in
[`docs/modeling/wp2_2-geometry-contract.md`](../../../docs/modeling/wp2_2-geometry-contract.md).

These queries define no split, no model feature set, and no evaluation baseline. Those belong to
WP2.2 Slice B, WP2.3 and WP2.4.

Data provided by StatsBomb.
