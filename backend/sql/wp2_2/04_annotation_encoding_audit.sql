-- WP2.2 Slice B annotation encoding audit, version 1.
-- Grain: one row per candidate optional boolean over exactly the WP2.1 non-penalty cohort.
-- Expected cohort size behind these counts: 5,606 shots.
--
-- Purpose: WP2.1 classified all six of these fields `Uncertain` for one shared reason -- their
-- absent-versus-false encoding was unverified -- and blocked their use until it was resolved.
-- This query resolves it by measurement.
--
-- The question is exactly this: when the column is NULL, does that mean the provider recorded the
-- situation as false, or that the provider recorded nothing? Ingestion answers half of it already:
-- `touchline.ingest.parse` maps an absent JSON key to NULL and never invents a value, so a
-- recorded `false` would survive into the column as FALSE. That makes `recorded_false` the whole
-- test:
--
--   * `recorded_false > 0` for a field means the source distinguishes false from absent, and NULL
--     for that field is genuinely missing data.
--   * `recorded_false = 0` means the source is true-only: absence is the only encoding of "not
--     annotated", and it cannot be separated from "annotated as not the case". A feature built on
--     such a field is a presence indicator, not a boolean, and must be described as one.
--
-- The per-tournament true counts answer a second question that the totals hide. These are
-- provider annotations, not measurements, and annotation intensity can drift between collection
-- rounds. WP2.3 splits by tournament, so a field whose true-rate moves across tournaments is
-- partly confounded with the split itself -- a fact that has to be visible before the field is
-- admitted, not after a fold reports an unexplained shift.
--
-- This query does not read or project the target, for the same reason as
-- `03_categorical_support.sql`: encoding semantics and coverage decide admissibility here, and
-- conversion rates measured over a cohort that contains WP2.3's holdout must not. The same
-- scoping applies -- that is a property of this query, not a claim about the whole development
-- process. See the "Target access" section of
-- `reports/wp2.2-slice-b-coverage-evidence.md`.
WITH core_scope (competition_id, season_id) AS (
    VALUES (43, 3), (55, 43), (43, 106), (55, 282)
),
cohort AS (
    SELECT
        m.competition_id,
        m.season_id,
        e.under_pressure,
        s.aerial_won,
        s.follows_dribble,
        s.first_time,
        s.open_goal,
        s.one_on_one
    FROM shots AS s
    JOIN events AS e USING (event_id)
    JOIN matches AS m USING (match_id)
    JOIN core_scope AS scope USING (competition_id, season_id)
    WHERE e.player_id IS NOT NULL
      AND e.period IS NOT NULL
      AND e.location_x IS NOT NULL
      AND e.location_y IS NOT NULL
      AND s.outcome_name IS NOT NULL
      AND s.body_part_name IS NOT NULL
      AND s.technique_name IS NOT NULL
      AND s.shot_type_name IS NOT NULL
      AND s.shot_type_name <> 'Penalty'
      AND e.period <> 5
),
-- One (field, flag) pair per cohort row per candidate field, so every field is counted by the
-- same three-way rule instead of six near-identical expressions that can drift apart.
flagged AS (
    SELECT competition_id, season_id, 'aerial_won' AS field, aerial_won AS flag FROM cohort
    UNION ALL
    SELECT competition_id, season_id, 'first_time', first_time FROM cohort
    UNION ALL
    SELECT competition_id, season_id, 'follows_dribble', follows_dribble FROM cohort
    UNION ALL
    SELECT competition_id, season_id, 'one_on_one', one_on_one FROM cohort
    UNION ALL
    SELECT competition_id, season_id, 'open_goal', open_goal FROM cohort
    UNION ALL
    SELECT competition_id, season_id, 'under_pressure', under_pressure FROM cohort
)
SELECT
    field,
    count(*) FILTER (WHERE flag IS TRUE)                                AS recorded_true,
    count(*) FILTER (WHERE flag IS FALSE)                               AS recorded_false,
    count(*) FILTER (WHERE flag IS NULL)                                AS absent,
    count(*) FILTER (
        WHERE flag IS TRUE AND competition_id = 43 AND season_id = 3
    )                                                                   AS true_wc_2018,
    count(*) FILTER (
        WHERE flag IS TRUE AND competition_id = 55 AND season_id = 43
    )                                                                   AS true_euro_2020,
    count(*) FILTER (
        WHERE flag IS TRUE AND competition_id = 43 AND season_id = 106
    )                                                                   AS true_wc_2022,
    count(*) FILTER (
        WHERE flag IS TRUE AND competition_id = 55 AND season_id = 282
    )                                                                   AS true_euro_2024
FROM flagged
GROUP BY field
ORDER BY field;
