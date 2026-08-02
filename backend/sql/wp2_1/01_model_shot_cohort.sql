-- WP2.1 model-development cohort, version 1.
-- Grain: one row per eligible typed Shot event (`shot_id`).
-- Scope: the accepted four-tournament core cohort only.
-- Target: `is_goal` is 1 exactly when the recorded shot outcome is Goal, otherwise 0.
-- Exclusions: all required model-cohort fields must be known; Penalty shots and period 5 are
-- excluded independently so neither source convention can silently admit shootout kicks.
-- Leakage boundary: outcome is projected only through the target. Post-shot location/flags,
-- provider xG, future events, and related-event facts are not projected.
WITH core_scope (competition_id, season_id) AS (
    VALUES (43, 3), (55, 43), (43, 106), (55, 282)
)
SELECT
    e.event_id AS shot_id,
    e.match_id,
    m.match_date,
    m.competition_id,
    m.season_id,
    e.event_index,
    e.period,
    e.minute,
    e.second,
    e.team_id,
    e.player_id,
    e.possession_id,
    e.location_x AS raw_location_x,
    e.location_y AS raw_location_y,
    e.play_pattern_id,
    e.play_pattern_name,
    e.under_pressure,
    s.body_part_id,
    s.body_part_name,
    s.technique_id,
    s.technique_name,
    s.shot_type_id,
    s.shot_type_name,
    s.aerial_won,
    s.follows_dribble,
    s.first_time,
    s.open_goal,
    s.one_on_one,
    CASE WHEN s.outcome_name = 'Goal' THEN 1 ELSE 0 END AS is_goal
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
ORDER BY m.match_date, e.match_id, e.event_index, e.event_id;
