-- WP0.3 reconciliation and coverage checks.
--
-- Read alongside the loader's own reconciliation output. These answer questions about the loaded
-- slice that shape the M2 cohort, and they are the reason the numbers in ADR 0004 could be
-- replaced with measured ones for WC 2022.

\echo '== row counts per table =='
SELECT 'competitions' AS table_name, count(*) FROM competitions
UNION ALL SELECT 'teams',   count(*) FROM teams
UNION ALL SELECT 'players', count(*) FROM players
UNION ALL SELECT 'matches', count(*) FROM matches
UNION ALL SELECT 'shots',   count(*) FROM shots;

\echo ''
\echo '== shot type distribution =='
SELECT shot_type, count(*) FROM shots GROUP BY shot_type ORDER BY count(*) DESC;

\echo ''
\echo '== period distribution (period 5 is the penalty shootout) =='
SELECT period, count(*) FROM shots GROUP BY period ORDER BY period;

\echo ''
\echo '== the M2 cohort: non-penalty, excluding shootouts =='
SELECT
    count(*)                                    AS shots,
    count(*) FILTER (WHERE outcome = 'Goal')    AS goals,
    round(100.0 * count(*) FILTER (WHERE outcome = 'Goal') / count(*), 1) AS conversion_pct
FROM shots
WHERE shot_type <> 'Penalty'
  AND period <> 5;

\echo ''
\echo '== coverage: nulls that would matter to a model =='
SELECT
    count(*) FILTER (WHERE location_x IS NULL) AS missing_location,
    count(*) FILTER (WHERE player_id  IS NULL) AS missing_player,
    count(*) FILTER (WHERE outcome    IS NULL) AS missing_outcome,
    count(*) FILTER (WHERE body_part  IS NULL) AS missing_body_part,
    count(*) FILTER (WHERE technique  IS NULL) AS missing_technique
FROM shots;

\echo ''
\echo '== defensive orphan verification (foreign keys should keep this at zero) =='
SELECT
    (SELECT count(*) FROM shots s LEFT JOIN matches m ON m.match_id = s.match_id
      WHERE m.match_id IS NULL) AS shots_without_match,
    (SELECT count(*) FROM shots s LEFT JOIN teams t ON t.team_id = s.team_id
      WHERE t.team_id IS NULL)  AS shots_without_team,
    (SELECT count(*) FROM shots s LEFT JOIN players p ON p.player_id = s.player_id
      WHERE s.player_id IS NOT NULL AND p.player_id IS NULL) AS shots_with_unknown_player;
