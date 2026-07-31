"""FastAPI application entry point.

M0 scope: prove the application starts, reads typed configuration, reaches PostgreSQL, and serves
the constant base-rate baseline computed from the loaded data.

**No model is served here and no performance claim is made.** The baseline is one number returned
for every shot; see `touchline.baseline` for why that is the right thing to publish first.
"""

from __future__ import annotations

from typing import Literal

import psycopg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from touchline import baseline
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


class BaselineResponse(BaseModel):
    """The constant base-rate baseline.

    Every field except `base_rate` exists to stop the number being read as more than it is. A bare
    probability looks like a model output; the counts, the cohort text and the caveat are what make
    it legible as "the average of the data currently loaded".
    """

    method: Literal["constant-base-rate"] = "constant-base-rate"
    base_rate: float = Field(
        description="Goals divided by shots over the cohort. Returned for every shot, unchanged."
    )
    shots: int = Field(description="Cohort denominator.")
    goals: int = Field(description="Cohort numerator.")
    cohort: str = Field(description="Exactly which shots the rate was computed over.")
    caveat: str


BASELINE_CAVEAT = (
    "This is not a model. It is the observed conversion rate of the loaded shots, returned "
    "unchanged for every shot regardless of location, player or context. Nothing here has been "
    "fitted or evaluated, and no split was used. It exists as the number a real shot-quality "
    "model must beat."
)


@app.get("/baseline", response_model=BaselineResponse, tags=["baseline"])
def shot_conversion_baseline() -> BaselineResponse:
    """Return the cohort conversion rate, computed live from the database.

    A connection is opened per request. That is fine at this scale and deliberately un-pooled;
    connection management is M3 hardening, and adding it now would be infrastructure without a
    measured need.
    """
    settings = get_settings()
    try:
        with psycopg.connect(settings.db_url_str, connect_timeout=5) as conn:
            rate = baseline.compute_base_rate(conn)
    except baseline.NoDataError as exc:
        # 503 rather than 404: the resource is meaningful, this instance just has nothing loaded
        # yet. A 404 would suggest the endpoint does not exist.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail=type(exc).__name__) from exc

    return BaselineResponse(
        base_rate=rate.value,
        shots=rate.shots,
        goals=rate.goals,
        cohort=baseline.COHORT_DESCRIPTION,
        caveat=BASELINE_CAVEAT,
    )
