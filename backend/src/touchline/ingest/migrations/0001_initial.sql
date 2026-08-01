-- Reproduce the M0 five-table schema without destroying existing data.
-- IF NOT EXISTS lets an unversioned M0 database adopt the migration ledger before 0002 upgrades it.

CREATE TABLE IF NOT EXISTS competitions (
    competition_id   integer NOT NULL,
    season_id        integer NOT NULL,
    competition_name text    NOT NULL,
    season_name      text    NOT NULL,
    country_name     text,
    PRIMARY KEY (competition_id, season_id)
);

CREATE TABLE IF NOT EXISTS teams (
    team_id   integer PRIMARY KEY,
    team_name text NOT NULL
);

CREATE TABLE IF NOT EXISTS players (
    player_id   integer PRIMARY KEY,
    player_name text NOT NULL
);

CREATE TABLE IF NOT EXISTS matches (
    match_id          integer PRIMARY KEY,
    competition_id    integer NOT NULL,
    season_id         integer NOT NULL,
    match_date        date,
    kick_off          text,
    home_team_id      integer NOT NULL,
    away_team_id      integer NOT NULL,
    home_score        integer,
    away_score        integer,
    competition_stage text
);

CREATE TABLE IF NOT EXISTS shots (
    shot_id    text PRIMARY KEY,
    match_id   integer NOT NULL,
    team_id    integer NOT NULL,
    player_id  integer,
    period     integer,
    minute     integer,
    second     integer,
    location_x double precision,
    location_y double precision,
    outcome    text,
    body_part  text,
    technique  text,
    shot_type  text
);
