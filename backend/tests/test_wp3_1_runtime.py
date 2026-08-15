"""Golden M2-to-M3 parity and public-input contracts for ``ModelRuntime``."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from touchline.serving import ModelRuntime, PredictionInput, ServingInputError

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "backend/model-release/exp-20260810-wp2_8-release"
GOLDEN = ROOT / "backend/tests/fixtures/wp3_1_golden_cases.json"


@pytest.fixture(scope="module")
def runtime() -> ModelRuntime:
    return ModelRuntime.load(BUNDLE)


def _request(payload: dict[str, Any]) -> PredictionInput:
    return PredictionInput(
        location_x=payload["location_x"],
        location_y=payload["location_y"],
        body_part=payload["body_part"],
        technique=payload["technique"],
        play_pattern=payload["play_pattern"],
    )


def test_runtime_matches_the_independent_qualified_wp2_oracle(runtime: ModelRuntime) -> None:
    oracle = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert oracle["oracle"] == "qualified_wp2_preprocessing_and_inference_path"
    assert oracle["model_sha256"] == runtime.provenance()["artifact_sha256"]
    assert (
        oracle["calibration_decision_sha256"] == runtime.provenance()["calibration_decision_sha256"]
    )

    tolerance = float(oracle["absolute_tolerance"])
    for case in oracle["cases"]:
        actual = runtime.predict(_request(case["request"]))
        assert actual == pytest.approx(
            case["expected"]["calibrated_probability"], abs=tolerance, rel=0.0
        ), case["name"]


def test_literal_rare_uses_the_same_reference_encoding_as_other_unseen_values(
    runtime: ModelRuntime,
) -> None:
    oracle = json.loads(GOLDEN.read_text(encoding="utf-8"))
    probabilities = {
        case["name"]: runtime.predict(_request(case["request"])) for case in oracle["cases"]
    }
    assert probabilities["literal_rare_is_external_unseen"] == pytest.approx(
        probabilities["unseen_levels"], abs=1e-15, rel=0.0
    )


@pytest.mark.parametrize(
    ("x", "y"),
    [(-0.1, 40.0), (120.1, 40.0), (100.0, -0.1), (100.0, 80.1)],
)
def test_coordinates_outside_the_public_statsbomb_bounds_are_rejected(
    runtime: ModelRuntime, x: float, y: float
) -> None:
    with pytest.raises(ServingInputError, match="inside"):
        runtime.predict(PredictionInput(x, y, "Right Foot", "Normal", "Regular Play"))


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_non_finite_coordinates_are_rejected(runtime: ModelRuntime, value: float) -> None:
    with pytest.raises(ServingInputError, match="finite"):
        runtime.predict(PredictionInput(value, 40.0, "Right Foot", "Normal", "Regular Play"))


@pytest.mark.parametrize("y", [36.0, 44.0])
def test_exact_goalposts_are_rejected(runtime: ModelRuntime, y: float) -> None:
    with pytest.raises(ServingInputError, match="goalpost"):
        runtime.predict(PredictionInput(120.0, y, "Right Foot", "Normal", "Regular Play"))


def test_blank_category_is_rejected_without_normalization(runtime: ModelRuntime) -> None:
    with pytest.raises(ServingInputError, match="non-empty"):
        runtime.predict(PredictionInput(100.0, 40.0, " ", "Normal", "Regular Play"))


def test_metrics_use_euro2024_reliability_not_the_legacy_wc2022_field(
    runtime: ModelRuntime,
) -> None:
    metrics = runtime.metrics()
    holdout = metrics["tournament_holdout"]
    calibration = metrics["calibration_adoption"]
    assert isinstance(holdout, dict)
    assert isinstance(calibration, dict)
    assert sum(row["count"] for row in holdout["reliability"]) == 1304
    assert sum(row["count"] for row in calibration["raw_anchor_reliability"]) == 1430
