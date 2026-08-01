"""FastAPI application entry point.

M0 scope: prove the application starts, reads typed configuration, reaches PostgreSQL, and serves
the constant base-rate baseline computed from the loaded data.

**No model is served here and no performance claim is made.** The baseline is one number returned
for every shot; see `touchline.baseline` for why that is the right thing to publish first.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

import psycopg
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from touchline import baseline, shots
from touchline.config import Settings, get_settings

app = FastAPI(
    title="Touchline Intelligence Platform",
    version="0.1.0",
    summary="Football research and decision-support on StatsBomb Open Data.",
)

# Restricted to named origins, never `*`. The deployed frontend is one known origin, so allowing
# any page on the internet to read this API from a visitor's browser would buy nothing.
# Read-only API, so no credentials and only the verbs actually used.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
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
    """The descriptive conversion rate of the loaded cohort.

    Every field except `conversion_rate` exists to stop the number being read as more than it is.
    A bare probability looks like a model output; the counts, the cohort text and the caveat are
    what make it legible as a summary of the data currently loaded.
    """

    method: Literal["descriptive-prevalence"] = "descriptive-prevalence"
    conversion_rate: float = Field(
        description="Goals divided by shots over the cohort. A description, not a prediction."
    )
    shots: int = Field(description="Cohort denominator: shots with a known outcome.")
    goals: int = Field(description="Cohort numerator.")
    cohort: str = Field(description="Exactly which shots the rate was computed over.")
    caveat: str


BASELINE_CAVEAT = (
    "This is a descriptive summary of the shots currently loaded, not a model and not a "
    "prediction. Nothing has been fitted, no split was used, and no performance claim is made. "
    "It is also NOT the baseline that models are compared against: that baseline is estimated "
    "from the training split alone and scored on validation and holdout rows under the same log "
    "loss, Brier score and calibration protocol as every candidate model. Using this full-cohort "
    "rate as a prediction on holdout rows would leak those rows' own outcomes into it."
)


@app.get("/baseline", response_model=BaselineResponse, tags=["baseline"])
def shot_conversion_rate() -> BaselineResponse:
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
        conversion_rate=rate.value,
        shots=rate.shots,
        goals=rate.goals,
        cohort=baseline.COHORT_DESCRIPTION,
        caveat=BASELINE_CAVEAT,
    )


class Shot(BaseModel):
    """One recorded shot.

    Every field is a fact from the source: where it was taken and what happened. There is no
    probability, rating or estimate here, and none will be added until M2 has an evaluated model.
    """

    shot_id: str
    match_id: int
    match_date: date | None
    competition_stage: str | None
    team: str
    opponent: str
    player: str | None = Field(description="Null where the source attributes no player.")
    period: int | None
    minute: int | None
    second: int | None
    location_x: float | None = Field(
        description="StatsBomb pitch coordinate, 0-120 along the attacking direction."
    )
    location_y: float | None = Field(description="StatsBomb pitch coordinate, 0-80 across.")
    outcome: str | None
    shot_type: str | None
    body_part: str | None
    technique: str | None


class ShotPage(BaseModel):
    """A bounded page of shots, with the total it was drawn from."""

    shots: list[Shot]
    total: int
    limit: int
    offset: int


@app.get("/shots", response_model=ShotPage, tags=["shots"])
def list_shots(
    match_id: Annotated[int | None, Query(description="Restrict to one match.")] = None,
    limit: Annotated[int, Query(ge=1, le=shots.MAX_LIMIT)] = shots.DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ShotPage:
    """Return recorded shots: locations, outcomes and context.

    Read-only, and enforced as such - the query runs in a READ ONLY transaction rather than merely
    being documented as safe.
    """
    settings = get_settings()
    try:
        with psycopg.connect(settings.db_url_str, connect_timeout=5) as conn:
            page = shots.fetch_shots(conn, match_id=match_id, limit=limit, offset=offset)
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail=type(exc).__name__) from exc

    return ShotPage(
        # model_validate rather than Shot(**row): the row is an untyped mapping from the driver,
        # and validating it is what turns "whatever the query returned" into the declared contract.
        shots=[Shot.model_validate(row) for row in page.shots],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )
