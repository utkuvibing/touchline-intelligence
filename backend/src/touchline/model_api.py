"""FastAPI transport for the validated model runtime.

This module owns HTTP schemas, routing, filters and domain-error translation inputs. It does not
encode features, load artifacts, call estimators, or apply calibration arithmetic.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Annotated, Literal

import psycopg
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr

from touchline import model_shots, schema_state
from touchline.config import get_settings
from touchline.model_shots import HistoricalFilters
from touchline.serving import (
    HistoricalPredictionInput,
    ModelRuntime,
    PredictionInput,
)

router = APIRouter(prefix="/model", tags=["model"])
Number = StrictFloat | StrictInt


class RuntimeNotReadyError(RuntimeError):
    pass


class PublicationGateClosedError(RuntimeError):
    pass


class ModelDataUnavailableError(RuntimeError):
    pass


class ProvenanceResponse(BaseModel):
    model_version: str
    release_id: str
    serving_manifest_sha256: str
    release_manifest_sha256: str
    release_manifest_file_sha256: str
    artifact_sha256: str
    calibration_decision_sha256: str


class DevelopmentScope(BaseModel):
    competitions: list[str]
    shots: int
    matches: int
    role: Literal["model_development"]


class CalibrationScope(BaseModel):
    competition: Literal["FIFA World Cup 2022"]
    shots: int
    matches: int
    role: Literal["platt_calibration_and_adoption"]


class HoldoutScope(BaseModel):
    competition: Literal["UEFA Euro 2024"]
    shots: int
    matches: int
    role: Literal["one_time_final_evaluation"]


class ModelScopes(BaseModel):
    development: DevelopmentScope
    calibration: CalibrationScope
    tournament_holdout: HoldoutScope


class CoordinateBounds(BaseModel):
    minimum: float
    maximum: float


class CoordinateContract(BaseModel):
    system: Literal["StatsBomb"]
    location_x: CoordinateBounds
    location_y: CoordinateBounds


class CategoryContract(BaseModel):
    reference: str
    retained: list[str]
    rare_members: list[str]


class CategoryFields(BaseModel):
    body_part: CategoryContract
    technique: CategoryContract
    play_pattern: CategoryContract


class InputContract(BaseModel):
    coordinates: CoordinateContract
    categorical_policy: Literal["exact_frozen_vocabulary_with_unseen_as_reference"]
    fields: CategoryFields


class ModelMetadataResponse(ProvenanceResponse):
    release_status: Literal["m2_qualified"]
    qualification_serving_status: Literal["not_served"]
    runtime_status: Literal["ready"]
    candidate: Literal["full_minus_presence"]
    estimator: Literal["logistic_regression"]
    calibration: Literal["platt_sigmoid"]
    adopted_variant: Literal["calibrated"]
    output: Literal["goal_conversion_probability"]
    scopes: ModelScopes
    input_contract: InputContract


class PredictionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location_x: Number
    location_y: Number
    body_part: StrictStr
    technique: StrictStr
    play_pattern: StrictStr


class PredictionResponse(ProvenanceResponse):
    calibrated_probability: float = Field(ge=0.0, le=1.0)


class Interval(BaseModel):
    lower: float
    upper: float


class ReliabilityRow(BaseModel):
    bin: int
    lower: float
    upper: float
    count: int
    positive_count: int
    observed_rate: float | None


class CalibrationReliabilityRow(ReliabilityRow):
    raw_mean_prediction: float | None
    calibrated_mean_prediction: float | None


class HoldoutReliabilityRow(ReliabilityRow):
    mean_prediction: float | None


class ProperScoring(BaseModel):
    log_loss: float
    brier: float


class Discrimination(BaseModel):
    roc_auc: float
    pr_auc: float


class CalibrationScores(BaseModel):
    log_loss: float
    brier: float
    max_supported_calibration_deviation: float


class CalibrationAdoption(BaseModel):
    split: Literal["FIFA World Cup 2022"]
    role: Literal["calibration"]
    shots: int
    matches: int
    adopted_variant: Literal["calibrated"]
    supported_raw_anchor_bins: int
    raw: CalibrationScores
    calibrated: CalibrationScores
    raw_anchor_reliability: list[CalibrationReliabilityRow]


class EvidenceSource(BaseModel):
    holdout_metrics_sha256: str
    evidence_status: Literal["qualified_m2_evidence"]
    recomputed_at_request_time: Literal[False]


class Uncertainty(BaseModel):
    method: Literal["match_clustered_paired_bootstrap"]
    confidence_level: float
    repetitions: int
    seed: int
    log_loss: Interval
    brier: Interval


class EffectComparison(BaseModel):
    log_loss: float
    brier: float
    log_loss_interval: Interval
    brier_interval: Interval


class RawComparator(BaseModel):
    proper_scoring: ProperScoring
    discrimination: Discrimination
    calibrated_minus_raw: EffectComparison


class TournamentHoldout(BaseModel):
    split: Literal["UEFA Euro 2024"]
    role: Literal["one_time_tournament_holdout"]
    shots: int
    matches: int
    goals: int
    observed_prevalence: float
    adopted_variant: Literal["calibrated"]
    proper_scoring: ProperScoring
    discrimination: Discrimination
    uncertainty: Uncertainty
    reliability: list[HoldoutReliabilityRow]
    raw_comparator: RawComparator


class ModelMetricsResponse(ProvenanceResponse):
    evidence_source: EvidenceSource
    calibration_adoption: CalibrationAdoption
    tournament_holdout: TournamentHoldout


class HistoricalShotResponse(BaseModel):
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
    calibrated_probability: float = Field(ge=0.0, le=1.0)


class HistoricalShotsResponse(ProvenanceResponse):
    cohort: Literal["FIFA World Cup 2022 eligible non-penalty shots"]
    split_role: Literal["calibration_data_historical_predictions"]
    historical_prediction_caveat: str
    shots: list[HistoricalShotResponse]
    total: int
    limit: int
    offset: int


HISTORICAL_CAVEAT = (
    "These are historical calibrated estimates over the FIFA World Cup 2022 calibration data. "
    "WC2022 labels were used to fit and adopt the Platt transform; these rows are not an untouched "
    "final holdout. UEFA Euro 2024 remains the one-time tournament holdout. Recorded outcomes are "
    "response facts only and never model inputs."
)


def get_runtime(request: Request) -> ModelRuntime:
    runtime = getattr(request.app.state, "model_runtime", None)
    if not isinstance(runtime, ModelRuntime):
        raise RuntimeNotReadyError("initialized model runtime is unavailable")
    return runtime


HISTORICAL_QUERY_PARAMETERS = frozenset(
    {
        "match_id",
        "team",
        "player",
        "outcome",
        "body_part",
        "technique",
        "play_pattern",
        "limit",
        "offset",
    }
)


def _validate_query_parameters(request: Request) -> None:
    for key in request.query_params:
        if key not in HISTORICAL_QUERY_PARAMETERS:
            raise model_shots.HistoricalFilterError(key, f"unsupported query parameter: {key}")
        if len(request.query_params.getlist(key)) > 1:
            raise model_shots.HistoricalFilterError(key, f"{key} may be supplied only once")


@router.get("", response_model=ModelMetadataResponse)
def model_metadata(request: Request) -> ModelMetadataResponse:
    return ModelMetadataResponse.model_validate(get_runtime(request).metadata())


@router.get("/metrics", response_model=ModelMetricsResponse)
def model_metrics(request: Request) -> ModelMetricsResponse:
    runtime = get_runtime(request)
    return ModelMetricsResponse.model_validate({**runtime.provenance(), **runtime.metrics()})


@router.post("/predict", response_model=PredictionResponse)
def model_predict(payload: PredictionRequest, request: Request) -> PredictionResponse:
    runtime = get_runtime(request)
    probability = runtime.predict(
        PredictionInput(
            location_x=float(payload.location_x),
            location_y=float(payload.location_y),
            body_part=str(payload.body_part),
            technique=str(payload.technique),
            play_pattern=str(payload.play_pattern),
        )
    )
    return PredictionResponse.model_validate(
        {**runtime.provenance(), "calibrated_probability": probability}
    )


@router.get("/shots", response_model=HistoricalShotsResponse)
def historical_model_shots(
    request: Request,
    match_id: Annotated[int | None, Query(gt=0)] = None,
    team: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    player: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    outcome: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    body_part: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    technique: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    play_pattern: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=model_shots.MAX_LIMIT)] = model_shots.DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> HistoricalShotsResponse:
    _validate_query_parameters(request)
    settings = get_settings()
    if not settings.historical_model_shots_enabled:
        raise PublicationGateClosedError("public historical model shots are not enabled")
    filters = HistoricalFilters(
        match_id=match_id,
        team=team,
        player=player,
        outcome=outcome,
        body_part=body_part,
        technique=technique,
        play_pattern=play_pattern,
        limit=limit,
        offset=offset,
    )
    runtime = get_runtime(request)
    try:
        with psycopg.connect(settings.db_url_str, connect_timeout=5) as connection:
            page = model_shots.fetch_historical_shots(connection, filters)
    except psycopg.errors.UndefinedTable as exc:
        raise ModelDataUnavailableError(schema_state.SCHEMA_NOT_MIGRATED_DETAIL) from exc
    except psycopg.Error as exc:
        raise ModelDataUnavailableError(type(exc).__name__) from exc
    inference_rows = [
        HistoricalPredictionInput(
            shot_id=shot.shot_id,
            match_id=shot.match_id,
            location_x=shot.location_x,
            location_y=shot.location_y,
            body_part=shot.body_part,
            technique=shot.technique,
            play_pattern=shot.play_pattern,
        )
        for shot in page.shots
    ]
    probabilities = runtime.predict_historical(inference_rows)
    rows = [
        HistoricalShotResponse.model_validate(
            {**asdict(shot), "match_date": shot.match_date, "calibrated_probability": probability}
        )
        for shot, probability in zip(page.shots, probabilities, strict=True)
    ]
    return HistoricalShotsResponse.model_validate(
        {
            **runtime.provenance(),
            "cohort": "FIFA World Cup 2022 eligible non-penalty shots",
            "split_role": "calibration_data_historical_predictions",
            "historical_prediction_caveat": HISTORICAL_CAVEAT,
            "shots": rows,
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }
    )
