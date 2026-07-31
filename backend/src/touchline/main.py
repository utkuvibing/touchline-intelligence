"""FastAPI application entry point.

M0 WP0.1 scope: prove the application starts, reads typed configuration, and can reach PostgreSQL.
No football data, no model, no claims. Those arrive in WP0.3 onward.
"""

from __future__ import annotations

from typing import Literal

import psycopg
from fastapi import FastAPI
from pydantic import BaseModel

from touchline.config import Settings, get_settings

app = FastAPI(
    title="Touchline Intelligence Platform",
    version="0.1.0",
    summary="Football research and decision-support on StatsBomb Open Data.",
)


class Health(BaseModel):
    """Liveness response. Answers 'is the process up', not 'can it serve traffic'."""

    status: Literal["ok"]
    environment: str
    version: str


class Readiness(BaseModel):
    """Readiness response. Answers 'can this instance serve traffic', which here means
    'is PostgreSQL reachable'."""

    status: Literal["ready", "degraded"]
    database: Literal["reachable", "unreachable"]
    detail: str | None = None


def _check_database(settings: Settings) -> tuple[bool, str | None]:
    """Open a connection and run the cheapest possible statement.

    Returns ``(reachable, detail)``. The detail is the exception class name only — connection
    strings and driver messages can carry host and credential fragments, which must not leak into
    an unauthenticated endpoint.
    """
    try:
        with (
            psycopg.connect(settings.db_url_str, connect_timeout=3) as conn,
            conn.cursor() as cur,
        ):
            cur.execute("SELECT 1")
            cur.fetchone()
    except Exception as exc:
        # Any failure at all means "not reachable" - a readiness probe that only catches
        # OperationalError would report ready during an auth or DNS failure.
        return False, type(exc).__name__
    return True, None


@app.get("/health", response_model=Health, tags=["ops"])
def health() -> Health:
    """Liveness probe. Never touches the database, so a database outage does not cause the
    platform to restart a perfectly healthy process."""
    settings = get_settings()
    return Health(status="ok", environment=settings.environment, version=app.version)


@app.get("/ready", response_model=Readiness, tags=["ops"])
def ready() -> Readiness:
    """Readiness probe. Touches the database, because an instance that cannot query is not
    ready to serve even though it is alive."""
    settings = get_settings()
    reachable, detail = _check_database(settings)
    return Readiness(
        status="ready" if reachable else "degraded",
        database="reachable" if reachable else "unreachable",
        detail=detail,
    )
