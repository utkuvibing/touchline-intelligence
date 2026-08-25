"""Idempotent, source-pinned WP1.3 cohort ingestion.

The public seam is :func:`run_ingestion`.  It deliberately owns two kinds of transaction:

* a control connection holds session advisory locks and durably records lifecycle state;
* a separate data transaction stages, validates, merges, reconciles and completes one run.

The split is intentional.  A failed data transaction must roll back every source fact, while a
failed or interrupted invocation must still leave an honest manifest behind.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, fields

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from touchline.ingest.cli import CollectedScope, SourceCounts, collect
from touchline.ingest.source import SOURCE_COMMIT, StatsBombSource
from touchline.sealed_scope import require_unsealed_scopes

# Ordered deliberately: provenance and reconciliation reports should not depend on an incidental
# directory traversal order.  These are tournament competition-seasons, never league seasons.
CORE_COHORT: tuple[tuple[int, int], ...] = ((43, 3), (55, 43), (43, 106), (55, 282))

ConnectionFactory = Callable[[], psycopg.Connection]
EntityCounts = dict[str, dict[str, int]]


class IngestionError(RuntimeError):
    """A WP1.3 run could not safely reach a succeeded manifest."""


class ConcurrentIngestionError(IngestionError):
    """Another invocation holds the database's ingestion control lock."""


class SourceCommitConflictError(IngestionError):
    """A populated database is already bound to a different source revision."""


class SourceConflictError(IngestionError):
    """A stable source key has changed under the same pinned source commit."""

    def __init__(self, table: str, fingerprint: str, source_count: int) -> None:
        super().__init__(f"source conflict in {table}; existing source key has different fields")
        self.table = table
        self.fingerprint = fingerprint
        self.source_count = source_count


class SourceValueError(IngestionError):
    """A caller supplied a source-derived value that violates a non-negotiable policy."""


@dataclass(frozen=True, slots=True)
class IngestionResult:
    run_id: uuid.UUID
    status: str
    entity_counts: EntityCounts
    source_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class _Table:
    name: str
    columns: tuple[str, ...]
    key: tuple[str, ...]
    compare: tuple[str, ...]


def _unique[T](rows: Iterable[T], key: Callable[[T], object]) -> list[T]:
    """Keep the first source label for a shared source identifier, deterministically."""
    values: dict[object, T] = {}
    for row in rows:
        values.setdefault(key(row), row)
    return list(values.values())


def _scope_counts(scope: CollectedScope) -> dict[str, int]:
    return {
        field.name: int(getattr(scope.source_counts, field.name)) for field in fields(SourceCounts)
    }


def collect_cohort(
    source: StatsBombSource, scopes: Sequence[tuple[int, int]] = CORE_COHORT
) -> CollectedScope:
    """Collect the fixed cohort, resolving shared dimensions by source identifier.

    Labels on ``teams`` and ``players`` are not identities.  A source identifier can be present
    in several tournaments with label variants, so the first label in the explicit cohort order is
    retained for that shared dimension.  Match-scoped lineup labels remain in their own records.
    """
    if not scopes:
        raise SourceValueError("an ingestion cohort must contain at least one competition-season")
    if len(set(scopes)) != len(scopes):
        raise SourceValueError("an ingestion cohort must not repeat a competition-season")
    require_unsealed_scopes(scopes)
    collected = [collect(source, competition_id, season_id) for competition_id, season_id in scopes]
    competitions = _unique(
        (row for scope in collected for row in scope.competitions),
        lambda row: (row.competition_id, row.season_id),
    )
    teams = _unique((row for scope in collected for row in scope.teams), lambda row: row.team_id)
    players = _unique(
        (row for scope in collected for row in scope.players), lambda row: row.player_id
    )
    matches = [row for scope in collected for row in scope.matches]
    if len({row.match_id for row in matches}) != len(matches):
        raise SourceValueError("a source match id appears in more than one selected scope")

    lineups = [row for scope in collected for row in scope.lineups]
    memberships = [row for scope in collected for row in scope.memberships]
    positions = [row for scope in collected for row in scope.positions]
    cards = [row for scope in collected for row in scope.cards]
    possessions = [row for scope in collected for row in scope.possessions]
    events = [row for scope in collected for row in scope.events]
    relations = [row for scope in collected for row in scope.relations]
    shots = [row for scope in collected for row in scope.shots]
    freeze_frames = [row for scope in collected for row in scope.freeze_frames]

    def sum_count(name: str) -> int:
        return sum(_scope_counts(scope)[name] for scope in collected)

    source_counts = SourceCounts(
        # `competitions` and `seasons` are shared dimensions; a competition-season is the only
        # selected-scope grain here.  WC 2018 and WC 2022 therefore contribute one competition
        # dimension row but two competition-season rows.
        competitions=len({row.competition_id for row in competitions}),
        seasons=len({row.season_id for row in competitions}),
        competition_seasons=len(competitions),
        teams=len(teams),
        players=len(players),
        matches=len(matches),
        match_teams=len(matches) * 2,
        lineups=len(lineups),
        lineup_memberships=len(memberships),
        lineup_positions=len(positions),
        lineup_cards=len(cards),
        possessions=len(possessions),
        events=len(events),
        event_relations=len(relations),
        shots=len(shots),
        shot_freeze_frame_players=len(freeze_frames),
        shots_without_location=sum(
            scope.source_counts.shots_without_location for scope in collected
        ),
        shots_without_player=sum(scope.source_counts.shots_without_player for scope in collected),
    )
    # Keep this evaluated independent of the output lists: it catches accidental omissions while
    # preserving the original per-file source totals for source-shaped child entities.
    assert source_counts.events == sum_count("events")
    return CollectedScope(
        competitions=competitions,
        teams=teams,
        players=players,
        matches=matches,
        shots=shots,
        source_counts=source_counts,
        lineups=lineups,
        memberships=memberships,
        positions=positions,
        cards=cards,
        possessions=possessions,
        events=events,
        relations=relations,
        freeze_frames=freeze_frames,
    )


def _json(value: object) -> Jsonb:
    return Jsonb(value)


def _rows(scope: CollectedScope) -> dict[str, list[tuple[object, ...]]]:
    """Return exactly the source-owned persisted columns for every entity grain."""
    competitions = _unique(scope.competitions, lambda row: row.competition_id)
    seasons = _unique(
        ((row.season_id, row.season_name) for row in scope.competitions),
        lambda row: row[0],
    )
    season_rows: list[tuple[object, ...]] = [
        (season_id, season_name) for season_id, season_name in seasons
    ]
    return {
        "competitions": [
            (r.competition_id, r.competition_name, r.country_name) for r in competitions
        ],
        "seasons": season_rows,
        "competition_seasons": [(r.competition_id, r.season_id) for r in scope.competitions],
        "teams": [(r.team_id, r.team_name) for r in scope.teams],
        "players": [(r.player_id, r.player_name) for r in scope.players],
        "matches": [
            (
                r.match_id,
                r.competition_id,
                r.season_id,
                r.match_date,
                r.kick_off,
                r.home_team_id,
                r.away_team_id,
                r.home_score,
                r.away_score,
                r.competition_stage,
            )
            for r in scope.matches
        ],
        "match_teams": [
            *[(r.match_id, r.home_team_id, "home") for r in scope.matches],
            *[(r.match_id, r.away_team_id, "away") for r in scope.matches],
        ],
        "lineups": [(r.match_id, r.team_id) for r in scope.lineups],
        "lineup_memberships": [
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
            for r in scope.memberships
        ],
        "lineup_positions": [
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
            for r in scope.positions
        ],
        "lineup_cards": [
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
            for r in scope.cards
        ],
        "possessions": [(r.match_id, r.possession_id, r.team_id) for r in scope.possessions],
        "events": [
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
                None if r.type_data is None else _json(r.type_data),
            )
            for r in scope.events
        ],
        "event_relations": [
            (r.match_id, r.event_id, r.related_event_id, r.source_order) for r in scope.relations
        ],
        "shots": [
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
            for r in scope.shots
        ],
        "shot_freeze_frame_players": [
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
            for r in scope.freeze_frames
        ],
    }


_TABLES: tuple[_Table, ...] = (
    _Table(
        "competitions",
        ("competition_id", "competition_name", "country_name"),
        ("competition_id",),
        ("competition_name", "country_name"),
    ),
    _Table("seasons", ("season_id", "season_name"), ("season_id",), ("season_name",)),
    _Table(
        "competition_seasons", ("competition_id", "season_id"), ("competition_id", "season_id"), ()
    ),
    _Table("teams", ("team_id", "team_name"), ("team_id",), ("team_name",)),
    _Table("players", ("player_id", "player_name"), ("player_id",), ("player_name",)),
    _Table(
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
        ("match_id",),
        (
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
    ),
    _Table("match_teams", ("match_id", "team_id", "role"), ("match_id", "team_id"), ("role",)),
    _Table("lineups", ("match_id", "team_id"), ("match_id", "team_id"), ()),
    _Table(
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
        ("match_id", "team_id", "player_id"),
        ("jersey_number", "player_name", "player_nickname", "country_id", "country_name"),
    ),
    _Table(
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
        ("match_id", "team_id", "player_id", "source_order"),
        (
            "position_id",
            "position_name",
            "from_period",
            "from_time",
            "to_period",
            "to_time",
            "start_reason",
            "end_reason",
        ),
    ),
    _Table(
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
        ("match_id", "team_id", "player_id", "source_order"),
        ("card_type", "reason", "period", "time"),
    ),
    _Table(
        "possessions",
        ("match_id", "possession_id", "team_id"),
        ("match_id", "possession_id"),
        ("team_id",),
    ),
    _Table(
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
        ("event_id",),
        (
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
    ),
    _Table(
        "event_relations",
        ("match_id", "source_event_id", "related_event_id", "source_order"),
        # Source order, not the related UUID, is this child record's stable source grain.  The
        # schema independently enforces it as unique per source event; using it here catches a
        # changed directed target before an INSERT could fail on that alternate constraint.
        ("source_event_id", "source_order"),
        ("match_id", "related_event_id"),
    ),
    _Table(
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
        ("event_id",),
        (
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
    ),
    _Table(
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
        ("event_id", "source_order"),
        ("player_id", "teammate", "position_id", "position_name", "location_x", "location_y"),
    ),
)


def _identifier_list(names: Sequence[str]) -> sql.Composed:
    return sql.SQL(", ").join(sql.Identifier(name) for name in names)


def _stage(conn: psycopg.Connection, table: _Table, rows: Sequence[tuple[object, ...]]) -> str:
    staging = f"_ingest_{table.name}"
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "CREATE TEMP TABLE {} ON COMMIT PRESERVE ROWS AS SELECT {} FROM {} WHERE FALSE"
            ).format(
                sql.Identifier(staging), _identifier_list(table.columns), sql.Identifier(table.name)
            )
        )
        if rows:
            copy_sql = sql.SQL("COPY {} ({}) FROM STDIN").format(
                sql.Identifier(staging), _identifier_list(table.columns)
            )
            with cur.copy(copy_sql) as copy:
                for row in rows:
                    copy.write_row(row)
        # These indexes live only for this transaction and disappear with the temporary tables.
        # They are required for bounded conflict/reconciliation joins at the measured 1.2M-row
        # relation grain; they are not speculative durable query indexes.
        cur.execute(
            sql.SQL("CREATE INDEX ON {} ({})").format(
                sql.Identifier(staging), _identifier_list(table.key)
            )
        )
        cur.execute(sql.SQL("ANALYZE {}").format(sql.Identifier(staging)))
    return staging


def _assert_no_duplicate_keys(conn: psycopg.Connection, table: _Table, staging: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT 1 FROM {} GROUP BY {} HAVING count(*) > 1 LIMIT 1").format(
                sql.Identifier(staging), _identifier_list(table.key)
            )
        )
        if cur.fetchone() is not None:
            raise SourceValueError(f"duplicate source key in {table.name}")


def _conflict_fingerprint(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _raise_if_changed(
    conn: psycopg.Connection, table: _Table, staging: str, source_count: int
) -> None:
    if not table.compare:
        return
    keys = sql.SQL(" AND ").join(
        sql.SQL("f.{} = s.{}").format(sql.Identifier(key), sql.Identifier(key)) for key in table.key
    )
    final_row = sql.SQL("ROW({})").format(
        sql.SQL(", ").join(
            sql.SQL("f.{}").format(sql.Identifier(column)) for column in table.compare
        )
    )
    staged_row = sql.SQL("ROW({})").format(
        sql.SQL(", ").join(
            sql.SQL("s.{}").format(sql.Identifier(column)) for column in table.compare
        )
    )
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "SELECT to_jsonb(s) FROM {} AS s JOIN {} AS f ON {} "
                "WHERE {} IS DISTINCT FROM {} LIMIT 1"
            ).format(
                sql.Identifier(staging), sql.Identifier(table.name), keys, final_row, staged_row
            )
        )
        row = cur.fetchone()
    if row is not None:
        raise SourceConflictError(table.name, _conflict_fingerprint(row[0]), source_count)


def _merge_one(
    conn: psycopg.Connection, table: _Table, staging: str, source_count: int
) -> dict[str, int]:
    _assert_no_duplicate_keys(conn, table, staging)
    _raise_if_changed(conn, table, staging, source_count)
    keys = sql.SQL(" AND ").join(
        sql.SQL("f.{} = s.{}").format(sql.Identifier(key), sql.Identifier(key)) for key in table.key
    )
    conflict_action = sql.SQL("DO NOTHING")
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "SELECT count(*) FROM {} AS s LEFT JOIN {} AS f ON {} WHERE f.{} IS NULL"
            ).format(
                sql.Identifier(staging),
                sql.Identifier(table.name),
                keys,
                sql.Identifier(table.key[0]),
            )
        )
        row = cur.fetchone()
        inserted = int(row[0]) if row else 0
        cur.execute(
            sql.SQL("INSERT INTO {} ({}) SELECT {} FROM {} ON CONFLICT ({}) {}").format(
                sql.Identifier(table.name),
                _identifier_list(table.columns),
                _identifier_list(table.columns),
                sql.Identifier(staging),
                _identifier_list(table.key),
                conflict_action,
            )
        )
        cur.execute(
            sql.SQL("SELECT count(*) FROM {} AS s JOIN {} AS f ON {}").format(
                sql.Identifier(staging), sql.Identifier(table.name), keys
            )
        )
        final_row = cur.fetchone()
    final_count = int(final_row[0]) if final_row else 0
    if final_count != source_count:
        raise IngestionError(
            f"scoped reconciliation failed for {table.name}: "
            f"source {source_count}, final {final_count}"
        )
    return {
        "inserted": inserted,
        "updated": 0,
        "unchanged": source_count - inserted,
        "rejected": 0,
        "source": source_count,
        "final_scoped": final_count,
    }


_MATCH_SCOPED_TABLES = {
    "matches",
    "match_teams",
    "lineups",
    "lineup_memberships",
    "lineup_positions",
    "lineup_cards",
    "possessions",
    "events",
    "event_relations",
    "shots",
    "shot_freeze_frame_players",
}


def _scope_from(table: _Table) -> sql.Composed:
    """Final rows belonging to the selected competition-season(s), including source deletions."""
    final = sql.Identifier(table.name)
    if table.name == "matches":
        return sql.SQL(
            "{} AS f JOIN {} AS cs ON (f.competition_id, f.season_id) = "
            "(cs.competition_id, cs.season_id)"
        ).format(final, sql.Identifier("_ingest_competition_seasons"))
    if table.name in {
        "match_teams",
        "lineups",
        "lineup_memberships",
        "lineup_positions",
        "lineup_cards",
        "possessions",
        "events",
        "event_relations",
    }:
        return sql.SQL("{} AS f JOIN {} AS sm ON sm.match_id = f.match_id").format(
            final, sql.Identifier("_ingest_matches")
        )
    if table.name == "shots":
        return sql.SQL("{} AS f JOIN {} AS se ON se.event_id = f.event_id").format(
            final, sql.Identifier("_ingest_events")
        )
    if table.name == "shot_freeze_frame_players":
        return sql.SQL("{} AS f JOIN {} AS ss ON ss.event_id = f.event_id").format(
            final, sql.Identifier("_ingest_shots")
        )
    raise AssertionError(f"{table.name} is not match scoped")


def _assert_no_scope_extras(
    conn: psycopg.Connection, table: _Table, staging: str, source_count: int
) -> None:
    """Require final selected-scope facts to equal staged source keys, not merely overlap."""
    if table.name not in _MATCH_SCOPED_TABLES:
        return
    keys = sql.SQL(" AND ").join(
        sql.SQL("f.{} = s.{}").format(sql.Identifier(key), sql.Identifier(key)) for key in table.key
    )
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "SELECT to_jsonb(f) FROM {} LEFT JOIN {} AS s ON {} WHERE s.{} IS NULL LIMIT 1"
            ).format(
                _scope_from(table),
                sql.Identifier(staging),
                keys,
                sql.Identifier(table.key[0]),
            )
        )
        row = cur.fetchone()
    if row is not None:
        raise SourceConflictError(table.name, _conflict_fingerprint(row[0]), source_count)


def _contains_provider_xg(value: object) -> bool:
    if isinstance(value, dict):
        return "statsbomb_xg" in value or any(
            _contains_provider_xg(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_provider_xg(item) for item in value)
    return False


def _assert_no_provider_xg(scope: CollectedScope) -> None:
    for event in scope.events:
        if _contains_provider_xg(event.type_data):
            raise SourceValueError("provider StatsBomb xG must not reach staging or persistence")


def _record_running(
    conn: psycopg.Connection,
    run_id: uuid.UUID,
    owner_token: uuid.UUID,
    scopes: Sequence[tuple[int, int]],
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_runs (
                run_id, owner_token, source_commit, status, scopes, owner_host, owner_pid,
                current_phase
            ) VALUES (%s, %s, %s, 'running', %s, %s, %s, 'collecting')
            """,
            (
                run_id,
                owner_token,
                SOURCE_COMMIT,
                _json([{"competition_id": c, "season_id": s} for c, s in scopes]),
                socket.gethostname(),
                os.getpid(),
            ),
        )
        cur.executemany(
            "INSERT INTO ingestion_run_scopes "
            "(run_id, competition_id, season_id) VALUES (%s, %s, %s)",
            [(run_id, competition_id, season_id) for competition_id, season_id in scopes],
        )
    conn.commit()


def _set_phase(
    conn: psycopg.Connection, run_id: uuid.UUID, phase: str, *, counts: dict[str, int] | None = None
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ingestion_runs
            SET current_phase = %s,
                phase_updated_at = CURRENT_TIMESTAMP,
                attempted_counts = COALESCE(%s, attempted_counts)
            WHERE run_id = %s AND status = 'running'
            """,
            (phase, None if counts is None else _json(counts), run_id),
        )
    conn.commit()


def _finish_failure(
    conn: psycopg.Connection,
    run_id: uuid.UUID,
    error_type: str,
    error_message: str,
    fingerprint: str | None = None,
    entity_counts: EntityCounts | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ingestion_runs
            SET status = 'failed', current_phase = 'failed', phase_updated_at = CURRENT_TIMESTAMP,
                finished_at = CURRENT_TIMESTAMP, error_type = %s, error_message = %s,
                error_fingerprint = %s, entity_counts = %s
            WHERE run_id = %s AND status = 'running'
            """,
            (error_type, error_message, fingerprint, _json(entity_counts or {}), run_id),
        )
        if cur.rowcount != 1:
            conn.rollback()
            raise IngestionError("running manifest disappeared before failure transition")
    conn.commit()


def _recover_interrupted(conn: psycopg.Connection) -> None:
    """Mark earlier running rows only while the caller owns both exclusive locks."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ingestion_runs
            SET status = 'interrupted', current_phase = 'interrupted_recovery',
                phase_updated_at = CURRENT_TIMESTAMP, finished_at = CURRENT_TIMESTAMP,
                error_type = 'interrupted_or_abandoned',
                error_message = 'A later invocation acquired the ingestion control lock '
                    'before this run completed.',
                entity_counts = '{}'::jsonb
            WHERE status = 'running'
            """
        )
    conn.commit()


def _lock_lifecycle_shared(conn: psycopg.Connection) -> None:
    """Protect this invocation's manifest from recovery until it reaches a terminal state."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pg_advisory_lock_shared("
            "hashtextextended(current_database() || ':' || current_schema() "
            "|| ':ingestion_manifest_lifecycle', 0))"
        )
    conn.commit()


def _unlock_lifecycle_shared(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pg_advisory_unlock_shared("
            "hashtextextended(current_database() || ':' || current_schema() "
            "|| ':ingestion_manifest_lifecycle', 0))"
        )
    conn.commit()


def _lock_lifecycle_exclusive(conn: psycopg.Connection) -> None:
    """Prove that no active invocation can own a running manifest before recovery."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pg_advisory_lock("
            "hashtextextended(current_database() || ':' || current_schema() "
            "|| ':ingestion_manifest_lifecycle', 0))"
        )
    conn.commit()


def _downgrade_lifecycle_lock(conn: psycopg.Connection) -> None:
    """Keep shared protection continuously while releasing exclusive recovery ownership."""
    with conn.cursor() as cur:
        # PostgreSQL session advisory locks are re-entrant. Acquiring shared while this session
        # owns exclusive succeeds immediately; releasing only exclusive leaves shared held.
        cur.execute(
            "SELECT pg_advisory_lock_shared("
            "hashtextextended(current_database() || ':' || current_schema() "
            "|| ':ingestion_manifest_lifecycle', 0))"
        )
        cur.execute(
            "SELECT pg_advisory_unlock("
            "hashtextextended(current_database() || ':' || current_schema() "
            "|| ':ingestion_manifest_lifecycle', 0))"
        )
    conn.commit()


def _assert_source_commit(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT source_commit FROM ingestion_runs WHERE status = 'succeeded'")
        commits = {str(row[0]) for row in cur.fetchall()}
    if commits and commits != {SOURCE_COMMIT}:
        raise SourceCommitConflictError(
            "database already contains successful ingestion from a different pinned source commit"
        )


def _error_details(exc: Exception) -> tuple[str, str, str | None, EntityCounts | None]:
    if isinstance(exc, SourceConflictError):
        return (
            "source_conflict",
            "A source-derived fact changed for an existing source key.",
            exc.fingerprint,
            {
                exc.table: {
                    "inserted": 0,
                    "updated": 0,
                    "unchanged": 0,
                    "rejected": 1,
                    "source": exc.source_count,
                    "final_scoped": 0,
                }
            },
        )
    if isinstance(exc, SourceCommitConflictError):
        return (
            "source_commit_conflict",
            "The database is bound to a different source commit.",
            None,
            None,
        )
    if isinstance(exc, ConcurrentIngestionError):
        return (
            "concurrent_ingestion",
            "Another ingestion invocation currently owns the control lock.",
            None,
            None,
        )
    if isinstance(exc, SourceValueError):
        return (
            "source_value_error",
            "Source values violated a required ingestion policy.",
            None,
            None,
        )
    if isinstance(exc, psycopg.Error):
        constraint = exc.diag.constraint_name
        return (
            "database_error" if constraint is None else f"database_error:{constraint}",
            "The atomic source-data transaction failed in PostgreSQL.",
            None,
            None,
        )
    return (
        "unexpected_error",
        "The ingestion invocation ended before successful completion.",
        None,
        None,
    )


def run_ingestion(
    connection_factory: ConnectionFactory,
    source: StatsBombSource,
    scopes: Sequence[tuple[int, int]] = CORE_COHORT,
) -> IngestionResult:
    """Collect and atomically merge an idempotent pinned-source cohort.

    The main session lock serializes source-data ownership. Every invocation also holds a shared
    lifecycle lock from before its running-manifest commit through its terminal transition. A main
    owner may recover prior running rows only after taking that lifecycle lock exclusively, which
    proves no active invocation can still own one of them.
    """
    normalized_scopes = tuple(scopes)
    if not normalized_scopes:
        raise SourceValueError("an ingestion cohort must contain at least one competition-season")
    if len(set(normalized_scopes)) != len(normalized_scopes):
        raise SourceValueError("an ingestion cohort must not repeat a competition-season")
    require_unsealed_scopes(normalized_scopes)

    run_id = uuid.uuid4()
    owner_token = uuid.uuid4()
    control = connection_factory()
    try:
        # Lock order is lifecycle-shared then main. A main winner releases shared before waiting
        # for lifecycle-exclusive, so it never attempts an unsafe shared-to-exclusive upgrade.
        _lock_lifecycle_shared(control)
        with control.cursor() as cur:
            cur.execute(
                "SELECT pg_try_advisory_lock("
                "hashtext(current_database()), hashtext(current_schema()))"
            )
            lock_row = cur.fetchone()
        acquired = bool(lock_row and lock_row[0])

        if not acquired:
            # Required audit trail: even a rejected contender first becomes a durable running row,
            # then reaches its terminal state independently.  It never touches another run.
            _record_running(control, run_id, owner_token, normalized_scopes)
            _finish_failure(
                control,
                run_id,
                "concurrent_ingestion",
                "Another ingestion invocation currently owns the control lock.",
            )
            raise ConcurrentIngestionError(
                "another ingestion invocation currently owns the control lock"
            )

        _unlock_lifecycle_shared(control)
        _lock_lifecycle_exclusive(control)
        _recover_interrupted(control)
        _downgrade_lifecycle_lock(control)
        _record_running(control, run_id, owner_token, normalized_scopes)
        try:
            collected = collect_cohort(source, normalized_scopes)
            _assert_no_provider_xg(collected)
            attempted = _scope_counts(collected)
            _set_phase(control, run_id, "staging", counts=attempted)

            with connection_factory() as data:
                _assert_source_commit(data)
                row_sets = _rows(collected)
                staged = {
                    table.name: _stage(data, table, row_sets[table.name]) for table in _TABLES
                }
                _set_phase(control, run_id, "merging", counts=attempted)
                entity_counts = {
                    table.name: _merge_one(
                        data, table, staged[table.name], len(row_sets[table.name])
                    )
                    for table in _TABLES
                }
                for table in _TABLES:
                    _assert_no_scope_extras(
                        data, table, staged[table.name], len(row_sets[table.name])
                    )
                with data.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE ingestion_runs
                        SET status = 'succeeded', current_phase = 'completed',
                            phase_updated_at = CURRENT_TIMESTAMP, finished_at = CURRENT_TIMESTAMP,
                            entity_counts = %s
                        WHERE run_id = %s AND status = 'running'
                        """,
                        (_json(entity_counts), run_id),
                    )
                    if cur.rowcount != 1:
                        raise IngestionError(
                            "running manifest disappeared before atomic completion"
                        )
                data.commit()
            return IngestionResult(
                run_id=run_id,
                status="succeeded",
                entity_counts=entity_counts,
                source_counts=attempted,
            )
        except Exception as exc:
            error_type, message, fingerprint, failed_counts = _error_details(exc)
            _finish_failure(control, run_id, error_type, message, fingerprint, failed_counts)
            raise
    finally:
        try:
            # A failed control-statement must not mask the source/data exception while releasing
            # the session lock.  Rollback does not release a session-level advisory lock.
            control.rollback()
            with control.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_unlock("
                    "hashtext(current_database()), hashtext(current_schema()))"
                )
                cur.execute(
                    "SELECT pg_advisory_unlock_shared("
                    "hashtextextended(current_database() || ':' || current_schema() "
                    "|| ':ingestion_manifest_lifecycle', 0))"
                )
                # Defensive cleanup if an exception interrupted exclusive-to-shared downgrade.
                cur.execute(
                    "SELECT pg_advisory_unlock("
                    "hashtextextended(current_database() || ':' || current_schema() "
                    "|| ':ingestion_manifest_lifecycle', 0))"
                )
            control.commit()
        finally:
            control.close()
