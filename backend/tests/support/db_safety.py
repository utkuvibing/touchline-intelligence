"""The single safety boundary between the test suite and a database it may destroy.

Database-backed tests here are not gentle. They ``DROP SCHEMA ... CASCADE``, apply production
migrations, seed fixtures, reset tables and run real ingestion. Every one of them reads its target
from ``TOUCHLINE_DB_URL``, which is the same variable a developer legitimately points at Neon to
reproduce a bug or read a report. Nothing about typing ``uv run pytest`` afterwards announces that
the run is about to rewrite a deployed database.

``touchline.config.require_local_write_target`` already protects ``poe ingest``, but it cannot
protect this: pytest never goes through the ingest CLI, and the guard there accepts a deliberate
per-target override. Tests get no such door. The rule is simply that a database-mutating test runs
against a local PostgreSQL or it does not run.

The classification itself is deliberately shared with production rather than reimplemented, so the
two cannot drift into disagreeing about what "local" means. What is *not* shared:

- **No override.** ``TOUCHLINE_ALLOW_REMOTE_WRITES`` is never consulted. A variable left exported
  from an earlier deliberate ingest must not silently arm a whole pytest run.
- **A missing or unparseable target is refused**, where production has already validated settings.

Read-only work is untouched: the WP2.2 full-cohort evidence tests take
``TOUCHLINE_FULL_COHORT_DB_URL`` and open ``READ ONLY`` transactions, quality/reporting runs and
deployed smoke checks are expected to run against a deployment, and the connectivity smoke test only
issues ``SELECT 1``.
"""

from __future__ import annotations

from typing import Any

import psycopg
from pydantic import PostgresDsn, TypeAdapter, ValidationError

from touchline.config import is_local_write_target, write_target

_DSN = TypeAdapter(PostgresDsn)

_LOCAL_HINT = (
    "Database-mutating tests run against a local PostgreSQL only. Start the Docker Compose "
    "database (infra/docker-compose.yml) and set TOUCHLINE_DB_URL to it, for example "
    "postgresql://touchline:localdev@localhost:5433/touchline. There is no override: a test run "
    "that can drop schemas must not be able to reach a deployed database at all."
)


class UnsafeTestDatabaseError(RuntimeError):
    """Raised when a database-mutating test is aimed at anything but a local PostgreSQL."""


def require_local_test_database(db_url: str | None) -> str:
    """Return ``db_url`` if it names a local PostgreSQL, else refuse.

    Fails closed on every uncertainty — absent, blank, unparseable, hostless, or a host this
    project has never classified as local. An unrecognised target is not a target to be given the
    benefit of the doubt; it is the case the guard exists for.

    The refusal names only a sanitized ``host[:port]/database``. Usernames, passwords and query
    parameters — where managed providers put credentials and endpoint tokens — are never read and
    never printed, and the underlying parse error is suppressed rather than chained, because
    pydantic includes the offending input value in its own message.
    """
    if db_url is None or not db_url.strip():
        raise UnsafeTestDatabaseError(
            f"Refusing to open a database-mutating test connection: no target is configured.\n"
            f"{_LOCAL_HINT}"
        )

    try:
        parsed = _DSN.validate_python(db_url.strip())
    except ValidationError:
        raise UnsafeTestDatabaseError(
            f"Refusing to open a database-mutating test connection: the configured target is not "
            f"a parseable PostgreSQL DSN.\n{_LOCAL_HINT}"
        ) from None

    if not is_local_write_target(parsed):
        raise UnsafeTestDatabaseError(
            f"Refusing to open a database-mutating test connection to the non-local database "
            f"{write_target(parsed)}.\n{_LOCAL_HINT}"
        )

    return db_url


def connect_local(db_url: str | None, **kwargs: Any) -> psycopg.Connection[Any]:
    """Validate the target, then connect.

    The order is the whole point: an unsafe target raises before ``psycopg.connect`` is reached, so
    a refused run never opens a session against the database it was about to damage.
    """
    return psycopg.connect(require_local_test_database(db_url), **kwargs)
