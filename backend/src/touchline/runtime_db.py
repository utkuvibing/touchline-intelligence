"""Bounded runtime database access and coalesced readiness probes.

The API owns one pool for its lifetime.  Readiness is deliberately separate from
normal request access: a short cache prevents probe storms and the condition
variable makes an expired probe true single-flight, including cached failures.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Condition, Lock
from time import monotonic
from typing import Literal

from psycopg_pool import ConnectionPool

from touchline import schema_state
from touchline.config import Settings

DatabaseDetail = Literal["database_unavailable", "schema_not_current", "probe_failed"]


@dataclass(frozen=True, slots=True)
class DatabaseState:
    """The independent database facts consumed by the public readiness contract."""

    reachable: bool
    schema_current: bool
    detail: DatabaseDetail | None


def create_pool(settings: Settings) -> ConnectionPool:
    """Create, but do not eagerly borrow, the bounded application-lifetime pool."""
    pool = ConnectionPool(
        conninfo=settings.db_url_str,
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        timeout=settings.db_pool_timeout_seconds,
        kwargs={"connect_timeout": 5},
        open=False,
    )
    # Do not make process startup depend on a transient database outage.  /ready is the
    # authoritative database check and will report the failure instead.
    pool.open(wait=False)
    return pool


def check_database(pool: ConnectionPool) -> DatabaseState:
    """Prove the database and the relations used by this application are available."""
    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            missing = schema_state.missing_required_tables(conn)
    except Exception:
        # Driver messages may contain endpoint or credential fragments.  The public probe only
        # receives a fixed category, never an exception name/string or infrastructure inventory.
        return DatabaseState(reachable=False, schema_current=False, detail="database_unavailable")
    if missing:
        return DatabaseState(
            reachable=True,
            schema_current=False,
            detail="schema_not_current",
        )
    return DatabaseState(reachable=True, schema_current=True, detail=None)


class ReadinessProbe:
    """A monotonic TTL cache with true single-flight cache-miss coalescing."""

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl_seconds = ttl_seconds
        self._condition = Condition(Lock())
        self._value: DatabaseState | None = None
        self._expires_at = 0.0
        self._in_flight = False

    def check(self, operation: Callable[[], DatabaseState]) -> DatabaseState:
        """Return a cached value or run exactly one concurrent expired-cache operation."""
        with self._condition:
            now = monotonic()
            if self._value is not None and now < self._expires_at:
                return self._value
            while self._in_flight:
                self._condition.wait()
                # The caller that just completed stored a result, including failure.  Its result
                # is deliberately shared even with a zero TTL so concurrent requests stay one run.
                if self._value is not None:
                    return self._value
            self._in_flight = True
        value = DatabaseState(reachable=False, schema_current=False, detail="probe_failed")
        try:
            value = operation()
        except Exception:
            # The operation is expected to convert errors, but never leave waiters blocked if a
            # future implementation violates that boundary.
            pass
        finally:
            with self._condition:
                self._value = value
                self._expires_at = monotonic() + self._ttl_seconds
                self._in_flight = False
                self._condition.notify_all()
        return value
