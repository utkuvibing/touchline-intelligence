-- Split the M0 competition-season composite into its source entities.
-- Existing matches and shots remain in place; this migration only rehomes dimensions and
-- materialises the two recorded participants of every existing match.

ALTER TABLE matches DROP CONSTRAINT matches_competition_fk;

ALTER TABLE competitions RENAME TO competition_seasons;

CREATE TABLE competitions (
    competition_id   integer PRIMARY KEY,
    competition_name text NOT NULL,
    country_name     text
);

CREATE TABLE seasons (
    season_id   integer PRIMARY KEY,
    season_name text NOT NULL
);

INSERT INTO competitions (competition_id, competition_name, country_name)
SELECT DISTINCT ON (competition_id) competition_id, competition_name, country_name
FROM competition_seasons
ORDER BY competition_id, season_id;

INSERT INTO seasons (season_id, season_name)
SELECT DISTINCT ON (season_id) season_id, season_name
FROM competition_seasons
ORDER BY season_id, competition_id;

ALTER TABLE competition_seasons
    DROP COLUMN competition_name,
    DROP COLUMN season_name,
    DROP COLUMN country_name;

CREATE TABLE match_teams (
    match_id integer NOT NULL,
    team_id  integer NOT NULL,
    role     text NOT NULL,
    PRIMARY KEY (match_id, team_id),
    UNIQUE (match_id, role)
);

INSERT INTO match_teams (match_id, team_id, role)
SELECT match_id, home_team_id, 'home' FROM matches
UNION ALL
SELECT match_id, away_team_id, 'away' FROM matches;
