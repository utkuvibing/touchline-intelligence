-- Question: Which optional generic-event fields are absent, by event type?
-- Grain: one row per event type.
-- Joins: none; all fields are at event grain.
-- NULLs: NULL is reported as source coverage, not coerced to a category and not called an error.
-- Duration and position are not expected for every event type, so these rates are descriptive only.
SELECT
    event_type_name,
    count(*) AS event_count,
    count(*) FILTER (WHERE player_id IS NULL) AS missing_player,
    round(100.0 * count(*) FILTER (WHERE player_id IS NULL) / count(*), 2)
        AS missing_player_pct,
    count(*) FILTER (WHERE location_x IS NULL) AS missing_location,
    round(100.0 * count(*) FILTER (WHERE location_x IS NULL) / count(*), 2)
        AS missing_location_pct,
    count(*) FILTER (WHERE position_id IS NULL) AS missing_position,
    round(100.0 * count(*) FILTER (WHERE position_id IS NULL) / count(*), 2)
        AS missing_position_pct,
    count(*) FILTER (WHERE duration IS NULL) AS missing_duration,
    round(100.0 * count(*) FILTER (WHERE duration IS NULL) / count(*), 2)
        AS missing_duration_pct
FROM events
GROUP BY event_type_name
ORDER BY event_count DESC, event_type_name;
