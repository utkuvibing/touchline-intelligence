"""Whether the connected database actually has the schema this build's queries need.

This module exists because of a real production failure, and the failure is worth stating
plainly: the deployed API was rebuilt from a revision whose queries join `events`, while the
managed database was still at the unversioned M0 five-table schema. Every data endpoint raised
`UndefinedTable` and returned 503, and `/ready` reported `ready`/`reachable` throughout — because
readiness ran `SELECT 1`, and `SELECT 1` succeeds against a database with no tables at all.

A readiness probe that cannot distinguish "PostgreSQL answers" from "PostgreSQL holds the schema
this build queries" is not measuring readiness. It is measuring TCP.

The check is deliberately narrow. It asserts that the relations the public endpoints join are
present; it does not attempt to verify columns, constraints or row counts. Schema *correctness* is
owned by the ordered migrations and their tests, and duplicating that here would create a second
definition of the schema that could drift from the first. What is caught here is the specific,
observed, silent failure: a database that was never migrated to the revision being served.
"""

from __future__ import annotations

import psycopg

# Exactly the relations `/baseline` and `/shots` join. Kept as a literal tuple rather than derived
# from the SQL: a check that parsed the queries it is checking would fail in the same way they do.
REQUIRED_TABLES: tuple[str, ...] = ("matches", "teams", "players", "events", "shots")

# Returned to unauthenticated callers, so it is a fixed constant rather than driver text. It names
# the operator action instead of the driver symbol: `UndefinedTable` states that a table is absent
# but not which one, why, or what to do, and that opacity is what made the outage hard to read.
SCHEMA_NOT_MIGRATED_DETAIL = (
    "database schema is behind this build; the ordered migrations have not been applied to it"
)


def missing_required_tables(conn: psycopg.Connection) -> tuple[str, ...]:
    """Return the required relations absent from the connection's current schema, in fixed order.

    Scoped to `current_schema()` rather than to the literal name `public`, because integration
    tests run inside a dedicated per-test schema and a check hard-coded to `public` would report
    the production schema's state while the tests exercised another one.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = current_schema()
              AND table_name = ANY(%s)
            """,
            (list(REQUIRED_TABLES),),
        )
        present = {str(row[0]) for row in cur.fetchall()}
    return tuple(table for table in REQUIRED_TABLES if table not in present)
