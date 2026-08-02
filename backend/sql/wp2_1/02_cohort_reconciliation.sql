-- WP2.1 reconciliation for the complete declared source population.
-- Grain: one named count. These counts explain every exclusion without relying on SQL NULL
-- behaviour. Own-goal events are reported separately because they are not typed Shot details and
-- therefore cannot enter the shot target implicitly.
WITH core_scope (competition_id, season_id) AS (
    VALUES (43, 3), (55, 43), (43, 106), (55, 282)
),
scoped_shots AS (
    SELECT e.*, s.outcome_name, s.body_part_name, s.technique_name, s.shot_type_name
    FROM shots AS s
    JOIN events AS e USING (event_id)
    JOIN matches AS m USING (match_id)
    JOIN core_scope AS scope USING (competition_id, season_id)
),
scoped_events AS (
    SELECT e.*
    FROM events AS e
    JOIN matches AS m USING (match_id)
    JOIN core_scope AS scope USING (competition_id, season_id)
),
metrics (metric, value) AS (
    SELECT 'typed_shots', count(*) FROM scoped_shots
    UNION ALL
    SELECT 'eligible_non_penalty_shots', count(*) FROM scoped_shots
    WHERE player_id IS NOT NULL
      AND period IS NOT NULL
      AND location_x IS NOT NULL
      AND location_y IS NOT NULL
      AND outcome_name IS NOT NULL
      AND body_part_name IS NOT NULL
      AND technique_name IS NOT NULL
      AND shot_type_name IS NOT NULL
      AND shot_type_name <> 'Penalty'
      AND period <> 5
    UNION ALL
    SELECT 'eligible_goals', count(*) FROM scoped_shots
    WHERE player_id IS NOT NULL
      AND period IS NOT NULL
      AND location_x IS NOT NULL
      AND location_y IS NOT NULL
      AND outcome_name IS NOT NULL
      AND body_part_name IS NOT NULL
      AND technique_name IS NOT NULL
      AND shot_type_name IS NOT NULL
      AND shot_type_name <> 'Penalty'
      AND period <> 5
      AND outcome_name = 'Goal'
    UNION ALL
    SELECT 'regulation_penalties', count(*) FROM scoped_shots
    WHERE shot_type_name = 'Penalty' AND period <> 5
    UNION ALL
    SELECT 'shootout_penalties', count(*) FROM scoped_shots
    WHERE shot_type_name = 'Penalty' AND period = 5
    UNION ALL
    SELECT 'period_five_non_penalties', count(*) FROM scoped_shots
    WHERE shot_type_name <> 'Penalty' AND period = 5
    UNION ALL
    SELECT 'missing_player', count(*) FROM scoped_shots WHERE player_id IS NULL
    UNION ALL
    SELECT 'missing_period', count(*) FROM scoped_shots WHERE period IS NULL
    UNION ALL
    SELECT 'missing_location_pair', count(*) FROM scoped_shots
    WHERE location_x IS NULL OR location_y IS NULL
    UNION ALL
    SELECT 'missing_outcome', count(*) FROM scoped_shots WHERE outcome_name IS NULL
    UNION ALL
    SELECT 'missing_body_part', count(*) FROM scoped_shots WHERE body_part_name IS NULL
    UNION ALL
    SELECT 'missing_technique', count(*) FROM scoped_shots WHERE technique_name IS NULL
    UNION ALL
    SELECT 'missing_shot_type', count(*) FROM scoped_shots WHERE shot_type_name IS NULL
    UNION ALL
    SELECT 'own_goal_for_events', count(*) FROM scoped_events
    WHERE event_type_name = 'Own Goal For'
    UNION ALL
    SELECT 'own_goal_against_events', count(*) FROM scoped_events
    WHERE event_type_name = 'Own Goal Against'
)
SELECT metric, value
FROM metrics
ORDER BY metric;
