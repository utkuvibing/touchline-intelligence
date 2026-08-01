-- Existing shot-detail contract over the normalized WP1.2 event/shot schema.
-- Run: docker exec -i touchline-postgres psql -U touchline -d touchline -f - < backend/sql/wp0_3_shot_detail.sql

SELECT
    s.event_id::text AS shot_id,
    m.match_date,
    m.competition_stage,
    shooting.team_name AS shooting_team,
    opponent.team_name AS opponent_team,
    p.player_name,
    e.period,
    e.minute,
    e.second,
    e.location_x,
    e.location_y,
    s.shot_type_name AS shot_type,
    s.body_part_name AS body_part,
    s.technique_name AS technique,
    s.outcome_name AS outcome
FROM shots AS s
JOIN events AS e USING (event_id)
JOIN matches AS m USING (match_id)
JOIN teams AS shooting ON shooting.team_id = e.team_id
JOIN teams AS opponent
  ON opponent.team_id = CASE
      WHEN e.team_id = m.home_team_id THEN m.away_team_id
      ELSE m.home_team_id
  END
LEFT JOIN players AS p ON p.player_id = e.player_id
ORDER BY m.match_date, e.match_id, e.period, e.minute, e.second, e.event_id;
