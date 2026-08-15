"""FastAPI application entry point.

M0 scope: prove the application starts, reads typed configuration, reaches PostgreSQL, and serves
the descriptive conversion prevalence computed from the loaded data.

**No model is served here and no performance claim is made.** `/baseline` reports one full-cohort
summary; `/shots` returns recorded facts with no prediction. See `touchline.baseline` for why that
is the right thing to publish first.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Literal

import psycopg
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from touchline import baseline, model_shots, schema_state, shots
from touchline.config import Settings, get_settings
from touchline.model_api import (
    ModelDataUnavailableError,
    PublicationGateClosedError,
    RuntimeNotReadyError,
)
from touchline.model_api import (
    router as model_router,
)
from touchline.serving import ModelRuntime, ServingInputError


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Load and verify the one qualified release before this worker accepts traffic."""
    application.state.model_runtime = ModelRuntime.load()
    yield
    del application.state.model_runtime


app = FastAPI(
    title="Touchline Intelligence Platform",
    version="0.1.0",
    summary="Football research and decision-support on StatsBomb Open Data.",
    lifespan=lifespan,
)

# Restricted to named origins, never `*`. The deployed frontend is one known origin, so allowing
# any page on the internet to read this API from a visitor's browser would buy nothing.
# Read-only API, so no credentials and only the verbs actually used.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class Health(BaseModel):
    """Liveness response. Answers 'is the process up', not 'can it serve traffic'."""

    status: Literal["ok"]
    environment: str
    version: str


class ErrorDetail(BaseModel):
    field: str | None
    code: str
    message: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail]


class ErrorResponse(BaseModel):
    error: ErrorBody


def _error(*, status_code: int, code: str, message: str, field: str | None = None) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message,
            details=[] if field is None else [ErrorDetail(field=field, code=code, message=message)],
        )
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump())


@app.exception_handler(RequestValidationError)
def request_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    query_error = any(error.get("loc", [None])[0] == "query" for error in exc.errors())
    code = "invalid_filter" if query_error else "request_validation_error"
    details = [
        ErrorDetail(
            field=".".join(str(item) for item in error.get("loc", [])[1:]) or None,
            code=code,
            message=str(error.get("msg", "request validation failed")),
        )
        for error in exc.errors()
    ]
    payload = ErrorResponse(
        error=ErrorBody(code=code, message="Request validation failed.", details=details)
    )
    return JSONResponse(status_code=422, content=payload.model_dump())


@app.exception_handler(ServingInputError)
def serving_input_error(request: Request, exc: ServingInputError) -> JSONResponse:
    del request
    return _error(status_code=422, code=exc.code, message=str(exc), field=exc.field)


@app.exception_handler(model_shots.HistoricalFilterError)
def historical_filter_error(
    request: Request, exc: model_shots.HistoricalFilterError
) -> JSONResponse:
    del request
    return _error(status_code=422, code="invalid_filter", message=str(exc), field=exc.field)


@app.exception_handler(PublicationGateClosedError)
def publication_gate_error(request: Request, exc: PublicationGateClosedError) -> JSONResponse:
    del request
    return _error(status_code=403, code="publication_gate_closed", message=str(exc))


@app.exception_handler(RuntimeNotReadyError)
def runtime_not_ready_error(request: Request, exc: RuntimeNotReadyError) -> JSONResponse:
    del request
    return _error(status_code=503, code="runtime_not_ready", message=str(exc))


@app.exception_handler(ModelDataUnavailableError)
def model_data_unavailable_error(request: Request, exc: ModelDataUnavailableError) -> JSONResponse:
    del request
    return _error(status_code=503, code="data_unavailable", message=str(exc))


app.include_router(model_router)


class Readiness(BaseModel):
    """Readiness response. Answers 'can this instance serve traffic'.

    That question has two independent failure modes, and collapsing them loses the one that is
    hardest to notice. `database` reports whether PostgreSQL answered at all; `database_schema`
    reports whether the relations this build queries are present in it. A database can be
    perfectly reachable and still be unable to serve a single request, which is exactly the state
    this deployment was in while reporting itself ready.

    The field is `database_schema` rather than `schema` because a Pydantic model may not carry a
    field named `schema` — it shadows an attribute on `BaseModel` and raises at class definition.
    """

    status: Literal["ready", "degraded"]
    database: Literal["reachable", "unreachable"]
    database_schema: Literal["current", "behind", "unknown"] = "unknown"
    model_runtime: Literal["ready", "not_ready"]
    model_version: str | None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class DatabaseState:
    """What a readiness probe learned, kept as three separate facts rather than one boolean."""

    reachable: bool
    schema_current: bool
    detail: str | None


def _check_database(settings: Settings) -> DatabaseState:
    """Open a connection, prove PostgreSQL answers, then prove it holds the expected relations.

    The connection detail is the exception class name only — connection strings and driver
    messages can carry host and credential fragments, which must not leak into an unauthenticated
    endpoint. The schema detail is a fixed constant plus relation names, which carry neither; the
    schema is defined by the ordered migrations and naming the absent tables is what makes the probe
    actionable instead of merely red.
    """
    try:
        with psycopg.connect(settings.db_url_str, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            missing = schema_state.missing_required_tables(conn)
    except Exception as exc:
        # Any failure at all means "not reachable" - a readiness probe that only catches
        # OperationalError would report ready during an auth or DNS failure.
        return DatabaseState(reachable=False, schema_current=False, detail=type(exc).__name__)

    if missing:
        return DatabaseState(
            reachable=True,
            schema_current=False,
            detail=f"{schema_state.SCHEMA_NOT_MIGRATED_DETAIL}; absent: {', '.join(missing)}",
        )
    return DatabaseState(reachable=True, schema_current=True, detail=None)


@app.get("/health", response_model=Health, tags=["ops"])
def health() -> Health:
    """Liveness probe. Never touches the database, so a database outage does not cause the
    platform to restart a perfectly healthy process."""
    settings = get_settings()
    return Health(status="ok", environment=settings.environment, version=app.version)


@app.get("/ready", response_model=Readiness, tags=["ops"])
def ready(request: Request, response: Response) -> Readiness:
    """Readiness probe. Touches the database, because an instance that cannot query is not
    ready to serve even though it is alive."""
    settings = get_settings()
    state = _check_database(settings)
    runtime = getattr(request.app.state, "model_runtime", None)
    if isinstance(runtime, ModelRuntime):
        model_ready = True
        model_version = runtime.provenance()["model_version"]
    else:
        model_ready = False
        model_version = None
    is_ready = state.reachable and state.schema_current and model_ready
    if not is_ready:
        response.status_code = 503
    detail = state.detail
    if state.reachable and state.schema_current and not model_ready:
        detail = "model_runtime_not_ready"
    return Readiness(
        # Ready requires all three: database, queried schema and the startup-validated model.
        status="ready" if is_ready else "degraded",
        database="reachable" if state.reachable else "unreachable",
        database_schema=(
            "unknown" if not state.reachable else "current" if state.schema_current else "behind"
        ),
        model_runtime="ready" if model_ready else "not_ready",
        model_version=model_version,
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
    except psycopg.errors.UndefinedTable as exc:
        raise HTTPException(
            status_code=503, detail=schema_state.SCHEMA_NOT_MIGRATED_DETAIL
        ) from exc
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
    except psycopg.errors.UndefinedTable as exc:
        raise HTTPException(
            status_code=503, detail=schema_state.SCHEMA_NOT_MIGRATED_DETAIL
        ) from exc
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
