-- WP2.1 categorical coverage on exactly the eligible non-penalty cohort.
-- Grain: one observed value per candidate categorical field. Low-support values remain visible;
-- this query does not merge, drop, or declare an arbitrary rarity threshold.
WITH core_scope (competition_id, season_id) AS (
    VALUES (43, 3), (55, 43), (43, 106), (55, 282)
),
cohort AS (
    SELECT
        s.body_part_name,
        s.technique_name,
        s.shot_type_name,
        e.play_pattern_name
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
categories (field_name, observed_value) AS (
    SELECT 'body_part_name', body_part_name FROM cohort
    UNION ALL
    SELECT 'technique_name', technique_name FROM cohort
    UNION ALL
    SELECT 'shot_type_name', shot_type_name FROM cohort
    UNION ALL
    SELECT 'play_pattern_name', coalesce(play_pattern_name, '[missing]')
    FROM cohort
)
SELECT
    field_name,
    observed_value,
    count(*) AS shots
FROM categories
GROUP BY field_name, observed_value
ORDER BY field_name, shots, observed_value;
