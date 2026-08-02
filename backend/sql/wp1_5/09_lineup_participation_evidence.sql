-- Question: How much recorded position-interval and event evidence accompanies lineup membership?
-- Grain: one row per competition-season.
-- Joins: position and event evidence are reduced to membership grain before joining. This avoids
-- multiplying a membership that has several position intervals and several events.
-- NULLs: absence is retained as an explicit coverage count.
-- Interpretation: none of these columns proves an appearance or minutes played.
WITH position_evidence AS (
    SELECT DISTINCT match_id, team_id, player_id
    FROM lineup_positions
), event_evidence AS (
    SELECT DISTINCT match_id, team_id, player_id
    FROM events
    WHERE team_id IS NOT NULL AND player_id IS NOT NULL
)
SELECT
    c.competition_name,
    se.season_name,
    count(*) AS lineup_memberships,
    count(pe.player_id) AS memberships_with_position_interval,
    count(ee.player_id) AS memberships_with_recorded_event,
    count(*) FILTER (
        WHERE pe.player_id IS NULL AND ee.player_id IS NULL
    ) AS memberships_without_either_evidence
FROM lineup_memberships AS lm
JOIN matches AS m USING (match_id)
JOIN competitions AS c USING (competition_id)
JOIN seasons AS se USING (season_id)
LEFT JOIN position_evidence AS pe USING (match_id, team_id, player_id)
LEFT JOIN event_evidence AS ee USING (match_id, team_id, player_id)
GROUP BY m.competition_id, m.season_id, c.competition_name, se.season_name
ORDER BY min(m.match_date), c.competition_name;
