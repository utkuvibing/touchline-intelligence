"""Bounded read-only WC2022 historical rows for model inference.

The query owns source/cohort/filter semantics only. Frozen feature construction and probability
inference remain exclusively in ``ModelRuntime``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import psycopg
from psycopg.rows import dict_row

from touchline.public_scope import PUBLIC_SCOPE_PARAMS, PUBLIC_SCOPE_PREDICATE

DEFAULT_LIMIT = 200
MAX_LIMIT = 1000


class HistoricalFilterError(ValueError):
    def __init__(self, field: str, message: str) -> None:
        self.field = field
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class HistoricalFilters:
    match_id: int | None = None
    team: str | None = None
    player: str | None = None
    outcome: str | None = None
    body_part: str | None = None
    technique: str | None = None
    play_pattern: str | None = None
    limit: int = DEFAULT_LIMIT
    offset: int = 0

    def __post_init__(self) -> None:
        if self.match_id is not None and self.match_id <= 0:
            raise HistoricalFilterError("match_id", "match_id must be positive")
        for field, maximum in (
            ("team", 200),
            ("player", 200),
            ("outcome", 100),
            ("body_part", 100),
            ("technique", 100),
            ("play_pattern", 100),
        ):
            value = getattr(self, field)
            if value is not None and (not value or not value.strip() or len(value) > maximum):
                raise HistoricalFilterError(
                    field,
                    f"{field} must be an exact non-blank string of at most {maximum} characters",
                )
        if not 1 <= self.limit <= MAX_LIMIT:
            raise HistoricalFilterError("limit", f"limit must be inside [1, {MAX_LIMIT}]")
        if self.offset < 0:
            raise HistoricalFilterError("offset", "offset must be non-negative")


@dataclass(frozen=True, slots=True)
class HistoricalShot:
    shot_id: str
    match_id: int
    match_date: date | None
    competition_stage: str | None
    team: str
    opponent: str
    player: str
    period: int
    minute: int | None
    second: int | None
    location_x: float
    location_y: float
    outcome: str
    shot_type: str
    body_part: str
    technique: str
    play_pattern: str


@dataclass(frozen=True, slots=True)
class HistoricalShotPage:
    shots: tuple[HistoricalShot, ...]
    total: int
    limit: int
    offset: int


BASE_FROM = f"""
    FROM shots AS s
    JOIN events AS e ON e.event_id = s.event_id
    JOIN matches AS m ON m.match_id = e.match_id
    JOIN teams AS shooting ON shooting.team_id = e.team_id
    JOIN teams AS opponent
      ON opponent.team_id = CASE
           WHEN e.team_id = m.home_team_id THEN m.away_team_id
           ELSE m.home_team_id
         END
    JOIN players AS p ON p.player_id = e.player_id
    WHERE {PUBLIC_SCOPE_PREDICATE}
      AND e.player_id IS NOT NULL
      AND e.period IS NOT NULL
      AND e.location_x IS NOT NULL
      AND e.location_y IS NOT NULL
      AND s.outcome_name IS NOT NULL
      AND s.body_part_name IS NOT NULL
      AND s.technique_name IS NOT NULL
      AND s.shot_type_name IS NOT NULL
      AND s.shot_type_name <> 'Penalty'
      AND e.period <> 5
"""

SELECT_COLUMNS = """
    SELECT
        s.event_id::text AS shot_id,
        e.match_id,
        m.match_date,
        m.competition_stage,
        shooting.team_name AS team,
        opponent.team_name AS opponent,
        p.player_name AS player,
        e.period,
        e.minute,
        e.second,
        e.location_x,
        e.location_y,
        s.outcome_name AS outcome,
        s.shot_type_name AS shot_type,
        s.body_part_name AS body_part,
        s.technique_name AS technique,
        COALESCE(e.play_pattern_name, 'None') AS play_pattern
"""

ORDER_AND_PAGE = """
    ORDER BY
        m.match_date ASC NULLS LAST,
        e.match_id ASC,
        e.period ASC,
        e.minute ASC NULLS LAST,
        e.second ASC NULLS LAST,
        e.event_index ASC,
        s.event_id ASC
    LIMIT %(limit)s OFFSET %(offset)s
"""


def _filter_sql(filters: HistoricalFilters) -> tuple[str, dict[str, object]]:
    clauses: list[str] = []
    params: dict[str, object] = {
        **PUBLIC_SCOPE_PARAMS,
        "limit": filters.limit,
        "offset": filters.offset,
    }
    fields = {
        "match_id": "e.match_id",
        "team": "shooting.team_name",
        "player": "p.player_name",
        "outcome": "s.outcome_name",
        "body_part": "s.body_part_name",
        "technique": "s.technique_name",
        "play_pattern": "COALESCE(e.play_pattern_name, 'None')",
    }
    for name, column in fields.items():
        value = getattr(filters, name)
        if value is not None:
            clauses.append(f"      AND {column} = %({name})s")
            params[name] = value
    return "\n".join(clauses), params


def fetch_historical_shots(
    conn: psycopg.Connection, filters: HistoricalFilters
) -> HistoricalShotPage:
    """Return one deterministic page and filtered total in one read-only transaction."""
    filter_sql, params = _filter_sql(filters)
    with conn.transaction():
        with conn.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute(f"SELECT count(*) {BASE_FROM}\n{filter_sql}", params)
            count_row = cursor.fetchone()
            total = int(count_row[0]) if count_row else 0
        with conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(f"{SELECT_COLUMNS}{BASE_FROM}\n{filter_sql}{ORDER_AND_PAGE}", params)
            rows = cursor.fetchall()
    return HistoricalShotPage(
        shots=tuple(HistoricalShot(**row) for row in rows),
        total=total,
        limit=filters.limit,
        offset=filters.offset,
    )
