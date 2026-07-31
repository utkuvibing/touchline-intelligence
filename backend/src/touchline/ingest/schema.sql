-- WP0.3 provisional schema.
--
-- THIS SCHEMA IS TEMPORARY AND IS EXPECTED TO BE REPLACED IN M1.
--
-- What it deliberately does NOT have, and why:
--
--   * No foreign keys. Referential integrity is M1 work, together with the ingestion order and
--     failure handling that make FKs enforceable rather than merely annoying.
--   * No idempotency. Re-running the loader against a populated database fails on the primary
--     keys. The supported way to re-run is a destructive reset (`poe ingest --reset`). Upserts,
--     source-key conflict handling and a run manifest are M1.
--   * No check constraints, no domains, no indexes beyond the primary keys. Indexes are added in
--     M1 against measured query plans, not guessed at now.
--   * No full event model, no lineups, no possessions. WP0.3 stores shots only.
--
-- Primary keys ARE present. They are not "production constraints" - they are what makes a
-- duplicate load fail loudly instead of silently doubling the row counts.
--
-- All identifiers are StatsBomb's own, preserved verbatim, so any row can be traced to its source
-- file. Provider xG is deliberately not stored; see records.py.

DROP TABLE IF EXISTS shots;
DROP TABLE IF EXISTS matches;
DROP TABLE IF EXISTS players;
DROP TABLE IF EXISTS teams;
DROP TABLE IF EXISTS competitions;

CREATE TABLE competitions (
    competition_id   integer NOT NULL,
    season_id        integer NOT NULL,
    competition_name text    NOT NULL,
    season_name      text    NOT NULL,
    country_name     text,
    PRIMARY KEY (competition_id, season_id)
);

CREATE TABLE teams (
    team_id   integer PRIMARY KEY,
    team_name text NOT NULL
);

-- CAUTION: this is NOT a squad list.
--
-- WP0.3 reads only shot events, so a player appears here if and only if they took at least one
-- shot in the loaded scope. WC 2022 yields 431 rows against roughly 830 players actually in the
-- squads. Any per-player denominator computed from this table would be wrong, and wrong in a way
-- that looks plausible. Complete squads arrive with lineups in M1.
CREATE TABLE players (
    player_id   integer PRIMARY KEY,
    player_name text NOT NULL
);

CREATE TABLE matches (
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

CREATE TABLE shots (
    -- StatsBomb's event UUID, kept as the natural key.
    shot_id    text PRIMARY KEY,
    match_id   integer NOT NULL,
    team_id    integer NOT NULL,
    -- Nullable: an event can lack an attributed player, and dropping such a shot would quietly
    -- change the shot count away from the source.
    player_id  integer,
    period     integer,
    minute     integer,
    second     integer,
    -- StatsBomb pitch coordinates, 120 x 80, origin at the defending-left corner. No normalisation
    -- of attacking direction happens here; that is a modelling decision and belongs with the
    -- feature pipeline, not the raw store.
    location_x double precision,
    location_y double precision,
    outcome    text,
    body_part  text,
    technique  text,
    shot_type  text
);
