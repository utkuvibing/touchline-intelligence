"""Transactional bulk loading for the normalized source-shaped schema."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from touchline.ingest.migrate import apply_migrations

if TYPE_CHECKING:
    from touchline.ingest.records import (
        Competition,
        Event,
        EventRelation,
        Lineup,
        LineupCard,
        LineupMembership,
        LineupPosition,
        Match,
        Player,
        Possession,
        Shot,
        ShotFreezeFramePlayer,
        Team,
    )


class NotIdempotentError(RuntimeError):
    """The WP1.2 loader deliberately refuses a populated schema."""


@dataclass(frozen=True, slots=True)
class LoadCounts:
    competitions: int
    seasons: int
    competition_seasons: int
    teams: int
    players: int
    matches: int
    match_teams: int
    lineups: int
    lineup_memberships: int
    lineup_positions: int
    lineup_cards: int
    possessions: int
    events: int
    event_relations: int
    shots: int
    shot_freeze_frame_players: int


TABLES = (
    "ingestion_run_scopes",
    "ingestion_runs",
    "shot_freeze_frame_players",
    "shots",
    "event_relations",
    "events",
    "possessions",
    "lineup_cards",
    "lineup_positions",
    "lineup_memberships",
    "lineups",
    "match_teams",
    "matches",
    "players",
    "teams",
    "competition_seasons",
    "seasons",
    "competitions",
)


def reset_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        for table in (*TABLES, "schema_migrations"):
            cur.execute(sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(sql.Identifier(table)))
    apply_migrations(conn)


def _copy(
    conn: psycopg.Connection,
    table: str,
    columns: tuple[str, ...],
    rows: Sequence[tuple[object, ...]],
) -> int:
    if not rows:
        return 0
    statement = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(table), sql.SQL(", ").join(sql.Identifier(c) for c in columns)
    )
    with conn.cursor() as cur, cur.copy(statement) as copy:
        for row in rows:
            copy.write_row(row)
    return len(rows)


def _existing_rows(conn: psycopg.Connection) -> int:
    total = 0
    with conn.cursor() as cur:
        for table in TABLES:
            cur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table)))
            row = cur.fetchone()
            total += 0 if row is None else int(row[0])
    return total


def load_all(
    conn: psycopg.Connection,
    *,
    competitions: list[Competition],
    teams: list[Team],
    players: list[Player],
    matches: list[Match],
    shots: list[Shot],
    lineups: list[Lineup],
    memberships: list[LineupMembership],
    positions: list[LineupPosition],
    cards: list[LineupCard],
    possessions: list[Possession],
    events: list[Event],
    relations: list[EventRelation],
    freeze_frames: list[ShotFreezeFramePlayer],
    allow_non_empty: bool = False,
) -> LoadCounts:
    if not allow_non_empty and _existing_rows(conn):
        raise NotIdempotentError("database already contains rows and this loader is not idempotent")
    event_rows = [
        (
            r.event_id,
            r.match_id,
            r.source_index,
            r.period,
            r.timestamp,
            r.minute,
            r.second,
            r.team_id,
            r.player_id,
            r.possession_id,
            r.under_pressure,
            r.off_camera,
            r.out,
            r.counterpress,
            r.play_pattern_id,
            r.play_pattern_name,
            r.position_id,
            r.position_name,
            r.duration,
            r.location_x,
            r.location_y,
            r.type_id,
            r.type_name,
            None if r.type_data is None else Jsonb(r.type_data),
        )
        for r in events
    ]
    seasons = {(c.season_id, c.season_name) for c in competitions}
    counts = {
        "competitions": _copy(
            conn,
            "competitions",
            ("competition_id", "competition_name", "country_name"),
            [(c.competition_id, c.competition_name, c.country_name) for c in competitions],
        ),
        "seasons": _copy(conn, "seasons", ("season_id", "season_name"), list(seasons)),
        "competition_seasons": _copy(
            conn,
            "competition_seasons",
            ("competition_id", "season_id"),
            [(c.competition_id, c.season_id) for c in competitions],
        ),
        "teams": _copy(
            conn, "teams", ("team_id", "team_name"), [(t.team_id, t.team_name) for t in teams]
        ),
        "players": _copy(
            conn,
            "players",
            ("player_id", "player_name"),
            [(p.player_id, p.player_name) for p in players],
        ),
        "matches": _copy(
            conn,
            "matches",
            (
                "match_id",
                "competition_id",
                "season_id",
                "match_date",
                "kick_off",
                "home_team_id",
                "away_team_id",
                "home_score",
                "away_score",
                "competition_stage",
            ),
            [
                (
                    m.match_id,
                    m.competition_id,
                    m.season_id,
                    m.match_date,
                    m.kick_off,
                    m.home_team_id,
                    m.away_team_id,
                    m.home_score,
                    m.away_score,
                    m.competition_stage,
                )
                for m in matches
            ],
        ),
        "match_teams": _copy(
            conn,
            "match_teams",
            ("match_id", "team_id", "role"),
            [(m.match_id, m.home_team_id, "home") for m in matches]
            + [(m.match_id, m.away_team_id, "away") for m in matches],
        ),
        "lineups": _copy(
            conn, "lineups", ("match_id", "team_id"), [(r.match_id, r.team_id) for r in lineups]
        ),
        "lineup_memberships": _copy(
            conn,
            "lineup_memberships",
            (
                "match_id",
                "team_id",
                "player_id",
                "jersey_number",
                "player_name",
                "player_nickname",
                "country_id",
                "country_name",
            ),
            [
                (
                    r.match_id,
                    r.team_id,
                    r.player_id,
                    r.jersey_number,
                    r.player_name,
                    r.player_nickname,
                    r.country_id,
                    r.country_name,
                )
                for r in memberships
            ],
        ),
        "lineup_positions": _copy(
            conn,
            "lineup_positions",
            (
                "match_id",
                "team_id",
                "player_id",
                "source_order",
                "position_id",
                "position_name",
                "from_period",
                "from_time",
                "to_period",
                "to_time",
                "start_reason",
                "end_reason",
            ),
            [
                (
                    r.match_id,
                    r.team_id,
                    r.player_id,
                    r.source_order,
                    r.position_id,
                    r.position_name,
                    r.from_period,
                    r.from_time,
                    r.to_period,
                    r.to_time,
                    r.start_reason,
                    r.end_reason,
                )
                for r in positions
            ],
        ),
        "lineup_cards": _copy(
            conn,
            "lineup_cards",
            (
                "match_id",
                "team_id",
                "player_id",
                "source_order",
                "card_type",
                "reason",
                "period",
                "time",
            ),
            [
                (
                    r.match_id,
                    r.team_id,
                    r.player_id,
                    r.source_order,
                    r.card_type,
                    r.reason,
                    r.period,
                    r.time,
                )
                for r in cards
            ],
        ),
        "possessions": _copy(
            conn,
            "possessions",
            ("match_id", "possession_id", "team_id"),
            [(r.match_id, r.possession_id, r.team_id) for r in possessions],
        ),
        "events": _copy(
            conn,
            "events",
            (
                "event_id",
                "match_id",
                "event_index",
                "period",
                "timestamp",
                "minute",
                "second",
                "team_id",
                "player_id",
                "possession_id",
                "under_pressure",
                "off_camera",
                "out",
                "counterpress",
                "play_pattern_id",
                "play_pattern_name",
                "position_id",
                "position_name",
                "duration",
                "location_x",
                "location_y",
                "event_type_id",
                "event_type_name",
                "type_data",
            ),
            event_rows,
        ),
        "event_relations": _copy(
            conn,
            "event_relations",
            ("match_id", "source_event_id", "related_event_id", "source_order"),
            [(r.match_id, r.event_id, r.related_event_id, r.source_order) for r in relations],
        ),
        "shots": _copy(
            conn,
            "shots",
            (
                "event_id",
                "outcome_id",
                "outcome_name",
                "body_part_id",
                "body_part_name",
                "technique_id",
                "technique_name",
                "shot_type_id",
                "shot_type_name",
                "end_location_x",
                "end_location_y",
                "end_location_z",
                "key_pass_event_id",
                "aerial_won",
                "follows_dribble",
                "first_time",
                "open_goal",
                "one_on_one",
                "deflected",
                "redirect",
                "saved_off_target",
                "saved_to_post",
            ),
            [
                (
                    r.shot_id,
                    r.outcome_id,
                    r.outcome,
                    r.body_part_id,
                    r.body_part,
                    r.technique_id,
                    r.technique,
                    r.shot_type_id,
                    r.shot_type,
                    r.end_location_x,
                    r.end_location_y,
                    r.end_location_z,
                    r.key_pass_event_id,
                    r.aerial_won,
                    r.follows_dribble,
                    r.first_time,
                    r.open_goal,
                    r.one_on_one,
                    r.deflected,
                    r.redirect,
                    r.saved_off_target,
                    r.saved_to_post,
                )
                for r in shots
            ],
        ),
        "shot_freeze_frame_players": _copy(
            conn,
            "shot_freeze_frame_players",
            (
                "event_id",
                "source_order",
                "player_id",
                "teammate",
                "position_id",
                "position_name",
                "location_x",
                "location_y",
            ),
            [
                (
                    r.shot_id,
                    r.source_order,
                    r.player_id,
                    r.teammate,
                    r.position_id,
                    r.position_name,
                    r.location_x,
                    r.location_y,
                )
                for r in freeze_frames
            ],
        ),
    }
    return LoadCounts(**counts)


def count_rows(conn: psycopg.Connection) -> LoadCounts:
    values: dict[str, int] = {}
    with conn.cursor() as cur:
        for table in LoadCounts.__dataclass_fields__:
            cur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table)))
            row = cur.fetchone()
            values[table] = int(row[0]) if row is not None else 0
    return LoadCounts(**values)
