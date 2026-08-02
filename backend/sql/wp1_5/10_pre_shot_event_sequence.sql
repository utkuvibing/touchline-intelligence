-- Question: Which recorded event type immediately precedes a Shot inside the same source possession?
-- Grain: one row per preceding event type, including an explicit no-predecessor bucket.
-- Window: LAG reads the preceding source-ordered event within match + possession partitions.
-- Joins: none. Filtering to Shot occurs after the window is calculated; filtering before it would
-- incorrectly compare each shot only with earlier shots.
-- NULLs: missing possession or event index cannot be ordered safely and is excluded. A NULL LAG
-- means the Shot is the first recorded event in that possession and is labelled explicitly.
-- Interpretation: adjacency in provider event order is not a causal claim.
WITH ordered_events AS (
    SELECT
        match_id,
        possession_id,
        event_index,
        event_type_name,
        lag(event_type_name) OVER (
            PARTITION BY match_id, possession_id
            ORDER BY event_index
        ) AS previous_event_type
    FROM events
    WHERE possession_id IS NOT NULL
      AND event_index IS NOT NULL
)
SELECT
    coalesce(previous_event_type, '[first event in possession]') AS previous_event_type,
    count(*) AS shot_count
FROM ordered_events
WHERE event_type_name = 'Shot'
GROUP BY previous_event_type
ORDER BY shot_count DESC, previous_event_type;
