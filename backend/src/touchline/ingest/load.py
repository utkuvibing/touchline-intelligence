"""Writing parsed records into PostgreSQL.

The relational schema is managed by ordered, hand-written SQL migrations through psycopg. There is
no ORM: SQL is an explicit project artifact and learning objective.

**This loader is not idempotent.** Every insert is a plain INSERT, so a second run against a
populated database fails on the primary keys. That failure is intentional - it is louder and safer
than a silent duplicate. To re-run, reset the schema first.

**Nothing in this module commits.** The caller owns the transaction, because the decision to keep a
load is not the loader's to make: rows must be written, counted, and reconciled against the source
*before* anything is durable. Committing here would make a failed reconciliation a report about
data that had already been kept.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import psycopg
from psycopg import sql

from touchline.ingest.migrate import apply_migrations

if TYPE_CHECKING:
    from touchline.ingest.records import Competition, Match, Player, Shot, Team


class NotIdempotentError(RuntimeError):
    """Raised when loading into a database that already holds rows.

    Explicit refusal, rather than a duplicate-key traceback, so the operator is told what to do.
    """


@dataclass(frozen=True, slots=True)
class LoadCounts:
    """Row counts actually written, for reconciliation against the source."""

    competitions: int
    teams: int
    players: int
    matches: int
    shots: int


def reset_schema(conn: psycopg.Connection) -> None:
    """Drop every managed table and rebuild through ordered migrations.

    Does not commit. PostgreSQL DDL is transactional, so a reset that is followed by a failed load
    rolls back with it and leaves the previous data intact - which is what makes an aborted re-run
    safe rather than merely loud.
    """
    with conn.cursor() as cur:
        for table in (
            "shots",
            "matches",
            "players",
            "teams",
            "competitions",
            "schema_migrations",
        ):
            cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(table)))
    apply_migrations(conn)


def _existing_rows(conn: psycopg.Connection) -> int:
    total = 0
    with conn.cursor() as cur:
        for table in ("competitions", "teams", "players", "matches", "shots"):
            cur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table)))
            row = cur.fetchone()
            total += int(row[0]) if row else 0
    return total


def _copy(
    conn: psycopg.Connection,
    table: str,
    columns: tuple[str, ...],
    rows: list[tuple[object, ...]],
) -> int:
    """Bulk-insert with COPY.

    COPY rather than executemany because a World Cup is ~2,500 shots and COPY moves them in one
    round trip. It also fails the whole batch on a bad row, which is the behaviour we want while
    there is no partial-failure handling.
    """
    if not rows:
        return 0
    statement = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(table),
        sql.SQL(", ").join(sql.Identifier(c) for c in columns),
    )
    with conn.cursor() as cur, cur.copy(statement) as copy:
        for row in rows:
            copy.write_row(row)
    return len(rows)


def load_all(
    conn: psycopg.Connection,
    *,
    competitions: list[Competition],
    teams: list[Team],
    players: list[Player],
    matches: list[Match],
    shots: list[Shot],
    allow_non_empty: bool = False,
) -> LoadCounts:
    """Write every record set in dependency order.

    Does not commit - see the module docstring. The caller must commit only after reconciling the
    resulting counts against the source, and roll back otherwise.
    """
    if not allow_non_empty and _existing_rows(conn) > 0:
        raise NotIdempotentError(
            "database already contains rows and this loader is not idempotent. "
            "Re-run with a destructive reset (`uv run poe ingest --reset`)."
        )

    counts = LoadCounts(
        competitions=_copy(
            conn,
            "competitions",
            ("competition_id", "season_id", "competition_name", "season_name", "country_name"),
            [
                (c.competition_id, c.season_id, c.competition_name, c.season_name, c.country_name)
                for c in competitions
            ],
        ),
        teams=_copy(
            conn, "teams", ("team_id", "team_name"), [(t.team_id, t.team_name) for t in teams]
        ),
        players=_copy(
            conn,
            "players",
            ("player_id", "player_name"),
            [(p.player_id, p.player_name) for p in players],
        ),
        matches=_copy(
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
        shots=_copy(
            conn,
            "shots",
            (
                "shot_id",
                "match_id",
                "team_id",
                "player_id",
                "period",
                "minute",
                "second",
                "location_x",
                "location_y",
                "outcome",
                "body_part",
                "technique",
                "shot_type",
            ),
            [
                (
                    s.shot_id,
                    s.match_id,
                    s.team_id,
                    s.player_id,
                    s.period,
                    s.minute,
                    s.second,
                    s.location_x,
                    s.location_y,
                    s.outcome,
                    s.body_part,
                    s.technique,
                    s.shot_type,
                )
                for s in shots
            ],
        ),
    )
    return counts


def count_rows(conn: psycopg.Connection) -> LoadCounts:
    """Read row counts back out of the database, for reconciliation."""
    values: dict[str, int] = {}
    with conn.cursor() as cur:
        for table in ("competitions", "teams", "players", "matches", "shots"):
            cur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table)))
            row = cur.fetchone()
            values[table] = int(row[0]) if row else 0
    return LoadCounts(**values)
