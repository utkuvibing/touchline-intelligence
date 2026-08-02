-- Question: What is the distribution of recorded event types across the loaded cohort?
-- Grain: one row per event type.
-- Joins: none; event_type_name is a typed fact at event grain.
-- NULLs: event_type_name is NOT NULL by schema. Percentage uses the full event-table denominator.
SELECT
    event_type_name,
    count(*) AS event_count,
    round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS event_pct
FROM events
GROUP BY event_type_name
ORDER BY event_count DESC, event_type_name;
