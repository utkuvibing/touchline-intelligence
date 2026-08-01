"""Read-only queries over the loaded shots.

Everything here returns **recorded facts**: where a shot was taken from and what happened to it.
There is no probability, no estimate and no derived quality measure anywhere in this module, and
there will not be one until M2 has a model that has actually been evaluated.

Read-only is enforced rather than asserted: each query runs in a `READ ONLY` transaction, so a
write reaching this path fails at the database instead of succeeding quietly.
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row

# A bounded page size. The whole World Cup is only ~1,500 shots, so this is not about protecting
# the database - it is about the API never having an unbounded response shape, which is the sort
# of thing that is easy to add now and awkward to retrofit once a client depends on it.
DEFAULT_LIMIT = 200
MAX_LIMIT = 1000

SHOTS_SQL = """
    SELECT
        s.event_id::text AS shot_id,
        e.match_id,
        m.match_date,
        m.competition_stage,
        shooting.team_name AS team,
        opponent.team_name AS opponent,
        p.player_name      AS player,
        e.period,
        e.minute,
        e.second,
        e.location_x,
        e.location_y,
        s.outcome_name   AS outcome,
        s.shot_type_name AS shot_type,
        s.body_part_name AS body_part,
        s.technique_name AS technique
    FROM shots AS s
    JOIN events  AS e        ON e.event_id = s.event_id
    JOIN matches AS m        ON m.match_id = e.match_id
    JOIN teams   AS shooting ON shooting.team_id = e.team_id
    JOIN teams   AS opponent
         ON opponent.team_id = CASE
                WHEN e.team_id = m.home_team_id THEN m.away_team_id
                ELSE m.home_team_id
            END
    -- LEFT JOIN: a shot can have no attributed player, and an INNER JOIN would drop it, quietly
    -- changing the shot count away from the source.
    LEFT JOIN players AS p   ON p.player_id = e.player_id
    -- The ::int cast is required, not cosmetic: with the parameter only ever compared to
    -- NULL and an integer column, PostgreSQL cannot infer its type and raises
    -- AmbiguousParameter. Naming the type makes the optional filter work.
    WHERE (%(match_id)s::int IS NULL OR e.match_id = %(match_id)s::int)
    ORDER BY m.match_date, e.match_id, e.period, e.minute, e.second, s.event_id
    LIMIT %(limit)s OFFSET %(offset)s
"""

COUNT_SQL = """
    SELECT count(*)
    FROM shots AS s
    JOIN events AS e ON e.event_id = s.event_id
    -- The ::int cast is required, not cosmetic: with the parameter only ever compared to
    -- NULL and an integer column, PostgreSQL cannot infer its type and raises
    -- AmbiguousParameter. Naming the type makes the optional filter work.
    WHERE (%(match_id)s::int IS NULL OR e.match_id = %(match_id)s::int)
"""


@dataclass(frozen=True, slots=True)
class ShotPage:
    """One page of shots, with the total it was drawn from.

    The total travels with the page so a caller can tell "these are all of them" from "these are
    the first two hundred" without a second request.
    """

    shots: list[dict[str, object]]
    total: int
    limit: int
    offset: int


def fetch_shots(
    conn: psycopg.Connection,
    *,
    match_id: int | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> ShotPage:
    """Fetch a bounded page of shots, oldest match first.

    `limit` is clamped rather than rejected: a caller asking for more than the maximum gets the
    maximum, which is friendlier than an error and cannot be used to force an unbounded response.
    """
    limit = max(1, min(limit, MAX_LIMIT))
    offset = max(0, offset)
    params = {"match_id": match_id, "limit": limit, "offset": offset}

    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute(COUNT_SQL, {"match_id": match_id})
            row = cur.fetchone()
            total = int(row[0]) if row else 0
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(SHOTS_SQL, params)
            shots = cur.fetchall()

    return ShotPage(shots=shots, total=total, limit=limit, offset=offset)
