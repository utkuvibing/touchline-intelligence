-- WP2.2 Slice B categorical support, version 1.
-- Grain: one row per (field, recorded value) over exactly the WP2.1 non-penalty cohort.
-- Expected cohort size behind these counts: 5,606 shots.
--
-- Purpose: WP2.1 classified body part, technique, shot type and play pattern as `Available`
-- "after coverage", and the WP2.2 plan admits context features only after coverage is documented.
-- This query is that documentation, measured rather than assumed.
--
-- Two questions it answers, neither of which is safe to guess:
--
--   1. How thin is each category's tail? A level with a handful of shots cannot support its own
--      coefficient, and deciding that from an eyeballed sample is how a rare level ends up
--      carrying a spurious effect.
--   2. Is every level present in every tournament? WP2.3 splits by tournament, so a level that
--      appears in only some of them is a level a fold can meet without ever having trained on it.
--      The per-tournament columns exist so that case is visible before the split is designed,
--      not discovered as an encoder failure afterwards.
--
-- This query does not read or project the target. Choosing which levels to keep by looking at
-- their conversion rate over the whole cohort -- which contains the tournament reserved as WP2.3's
-- holdout -- would be selection on the holdout, so support and presence decide level handling here
-- and outcome does not.
--
-- That is a statement about this query, not about the whole development process. Aggregate outcome
-- rates by candidate level were viewed during untracked exploratory work before the split was
-- frozen; see the "Target access" section of
-- `reports/wp2.2-slice-b-coverage-evidence.md` for what that does and does not permit later.
WITH core_scope (competition_id, season_id) AS (
    VALUES (43, 3), (55, 43), (43, 106), (55, 282)
),
cohort AS (
    SELECT
        m.competition_id,
        m.season_id,
        e.play_pattern_name,
        s.body_part_name,
        s.technique_name,
        s.shot_type_name
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
-- One (field, value) pair per cohort row per candidate field. Unpivoting here keeps the
-- aggregation below identical for every field, so a field cannot be counted by a subtly
-- different rule than its neighbour.
labelled AS (
    SELECT competition_id, season_id, 'body_part_name' AS field, body_part_name AS value
    FROM cohort
    UNION ALL
    SELECT competition_id, season_id, 'play_pattern_name', play_pattern_name FROM cohort
    UNION ALL
    SELECT competition_id, season_id, 'shot_type_name', shot_type_name FROM cohort
    UNION ALL
    SELECT competition_id, season_id, 'technique_name', technique_name FROM cohort
)
SELECT
    field,
    value,
    count(*)                                                            AS shots,
    count(*) FILTER (WHERE competition_id = 43 AND season_id = 3)       AS wc_2018,
    count(*) FILTER (WHERE competition_id = 55 AND season_id = 43)      AS euro_2020,
    count(*) FILTER (WHERE competition_id = 43 AND season_id = 106)     AS wc_2022,
    count(*) FILTER (WHERE competition_id = 55 AND season_id = 282)     AS euro_2024
FROM labelled
GROUP BY field, value
ORDER BY field, shots DESC, value;
