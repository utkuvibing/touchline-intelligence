# WP2.3 split SQL

Two read-only queries supporting WP2.3's locked three-way split. Both are repository-local
model-development infrastructure and neither expands the public API surface.

1. `01_split_match_population.sql` returns one row per ingested match in the locked
   four-tournament scope with its label-free eligible-shot count. Expected row count 230.
   `eligible_shots` duplicates WP2.1's cohort predicate set verbatim rather than importing it, so
   a divergence fails the row-count / shot-sum anchors in the WP2.3 tests instead of silently
   re-scoping the split. Matches with zero eligible shots are included: the split is a
   match-level object, and every cohort match must be assigned exactly once.
2. `02_split_shot_membership.sql` returns `shot_id` (an alias of `events.event_id`, the `shots`
   primary key, per WP2.1 convention) and `match_id` for every eligible non-penalty Shot.
   Expected row count 5,606. It powers the shot-level partition proof: every shot id joins to
   exactly one match assignment and exactly one top-level split, with no duplicates and no
   unassigned shots.

## Target access

**Neither query projects or inspects the target.** Each duplicates WP2.1's eligibility predicate
set, which necessarily includes the inherited `outcome_name IS NOT NULL` check — removing it
would break the cohort set-equality proof — and that predicate is the only place either query
touches outcome data. The queries never inspect outcome categories or values, never project the
target or any outcome-derived field, and no outcome value is used in the split assignment, fold
balancing, calibration, selection, or protocol decisions. The assignment itself is a pure
function of match identity, scope and date, and the split manifest carries no goal counts.
Holdout outcomes belong to the final evaluation evidence.

The WP2.1 cohort query is executed by the full-cohort tests only to compare shot-id sets
(consuming nothing but the `shot_id` column). This is not a claim that no historical query ever
read the target: WP2.1's published reconciliation did, and that exposure is disclosed in the
[WP2.3 split contract](../../../reports/wp2.3-split-contract.md).

Both queries are `SELECT`-only and are executed inside a `READ ONLY` transaction by the
integration tests. None creates schema, applies migrations, seeds fixtures, or writes anything.

The measured output is recorded in [`reports/wp2.3-split-evidence.md`](../../../reports/wp2.3-split-evidence.md).

These queries define no model, no metric, no feature set, and no evaluation baseline. The split
rule itself — development = World Cup 2018 + Euro 2020, calibration = World Cup 2022, holdout =
Euro 2024, five deterministic match-grouped development folds — is implemented in
`touchline.modeling.splits` and documented in the
[WP2.3 split contract](../../../reports/wp2.3-split-contract.md).

Data provided by StatsBomb.
