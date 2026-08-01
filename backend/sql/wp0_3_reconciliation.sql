-- WC 2022 reconciliation and coverage checks over the normalized WP1.2 schema.

\echo '== row counts per source-shaped table =='
SELECT 'competitions' AS table_name, count(*) FROM competitions
UNION ALL SELECT 'seasons', count(*) FROM seasons
UNION ALL SELECT 'competition_seasons', count(*) FROM competition_seasons
UNION ALL SELECT 'teams', count(*) FROM teams
UNION ALL SELECT 'players', count(*) FROM players
UNION ALL SELECT 'matches', count(*) FROM matches
UNION ALL SELECT 'match_teams', count(*) FROM match_teams
UNION ALL SELECT 'lineups', count(*) FROM lineups
UNION ALL SELECT 'lineup_memberships', count(*) FROM lineup_memberships
UNION ALL SELECT 'lineup_positions', count(*) FROM lineup_positions
UNION ALL SELECT 'lineup_cards', count(*) FROM lineup_cards
UNION ALL SELECT 'possessions', count(*) FROM possessions
UNION ALL SELECT 'events', count(*) FROM events
UNION ALL SELECT 'event_relations', count(*) FROM event_relations
UNION ALL SELECT 'shots', count(*) FROM shots
UNION ALL SELECT 'shot_freeze_frame_players', count(*) FROM shot_freeze_frame_players;

\echo ''
\echo '== shot type and period distributions =='
SELECT s.shot_type_name, count(*)
FROM shots AS s GROUP BY s.shot_type_name ORDER BY count(*) DESC;
SELECT e.period, count(*)
FROM shots AS s JOIN events AS e USING (event_id)
GROUP BY e.period ORDER BY e.period;

\echo ''
\echo '== descriptive non-penalty cohort, excluding shootouts =='
SELECT
    count(*) AS shots,
    count(*) FILTER (WHERE s.outcome_name = 'Goal') AS goals,
    round(100.0 * count(*) FILTER (WHERE s.outcome_name = 'Goal') / count(*), 1)
        AS conversion_pct
FROM shots AS s
JOIN events AS e USING (event_id)
WHERE s.shot_type_name IS NOT NULL
  AND e.period IS NOT NULL
  AND s.outcome_name IS NOT NULL
  AND s.shot_type_name <> 'Penalty'
  AND e.period <> 5;

\echo ''
\echo '== leakage and orphan checks; every value must be zero =='
SELECT
    (SELECT count(*) FROM information_schema.columns
      WHERE table_schema = current_schema() AND lower(column_name) LIKE '%xg%') AS xg_columns,
    (SELECT count(*) FROM events
      WHERE type_data::text ILIKE '%statsbomb_xg%') AS jsonb_with_provider_xg,
    (SELECT count(*) FROM events e LEFT JOIN matches m USING (match_id)
      WHERE m.match_id IS NULL) AS events_without_match,
    (SELECT count(*) FROM event_relations r LEFT JOIN events e
      ON (e.match_id, e.event_id) = (r.match_id, r.source_event_id)
      WHERE e.event_id IS NULL) AS relations_without_source,
    (SELECT count(*) FROM event_relations r LEFT JOIN events e
      ON (e.match_id, e.event_id) = (r.match_id, r.related_event_id)
      WHERE e.event_id IS NULL) AS relations_without_target,
    (SELECT count(*) FROM shots s LEFT JOIN events e USING (event_id)
      WHERE e.event_id IS NULL) AS shots_without_event;
