"""WP3.1 HTTP contracts over the startup-validated singleton runtime."""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

from touchline.main import app
from touchline.serving import ModelRuntime, ServingBundleError

UNREACHABLE_DSN = "postgresql://nobody:nothing@127.0.0.1:1/nonexistent"
PROVENANCE_FIELDS = {
    "model_version",
    "release_id",
    "serving_manifest_sha256",
    "release_manifest_sha256",
    "release_manifest_file_sha256",
    "artifact_sha256",
    "calibration_decision_sha256",
}


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOUCHLINE_DB_URL", UNREACHABLE_DSN)
    monkeypatch.delenv("TOUCHLINE_HISTORICAL_MODEL_SHOTS_ENABLED", raising=False)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as instance:
        yield instance


def test_model_metadata_exposes_release_and_serving_bundle_provenance(
    client: TestClient,
) -> None:
    response = client.get("/model")
    assert response.status_code == 200
    body = response.json()
    assert body.keys() >= PROVENANCE_FIELDS
    assert body["release_status"] == "m2_qualified"
    assert body["qualification_serving_status"] == "not_served"
    assert body["runtime_status"] == "ready"
    assert body["serving_state"] == "serving"
    assert body["historical_publication_state"] == "closed"
    assert body["scopes"]["calibration"]["competition"] == "FIFA World Cup 2022"
    assert body["scopes"]["tournament_holdout"]["competition"] == "UEFA Euro 2024"


def test_metrics_are_curated_qualified_evidence_with_distinct_split_semantics(
    client: TestClient,
) -> None:
    response = client.get("/model/metrics")
    assert response.status_code == 200
    body = response.json()
    assert body.keys() >= PROVENANCE_FIELDS
    assert body["evidence_source"]["recomputed_at_request_time"] is False
    assert body["calibration_adoption"]["split"] == "FIFA World Cup 2022"
    assert body["calibration_adoption"]["shots"] == 1430
    assert body["tournament_holdout"]["split"] == "UEFA Euro 2024"
    assert body["tournament_holdout"]["shots"] == 1304
    assert sum(row["count"] for row in body["tournament_holdout"]["reliability"]) == 1304


def test_predict_returns_only_calibrated_probability_and_provenance(client: TestClient) -> None:
    response = client.post(
        "/model/predict",
        json={
            "location_x": 112.0,
            "location_y": 40.0,
            "body_part": "Right Foot",
            "technique": "Normal",
            "play_pattern": "Regular Play",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["calibrated_probability"] == pytest.approx(0.3912322351084872, abs=1e-12)
    assert set(body) == PROVENANCE_FIELDS | {"calibrated_probability"}
    assert not {"raw_probability", "base_probability", "base_logit", "features"} & body.keys()


def test_predict_rejects_extra_or_post_shot_fields_with_structured_error(
    client: TestClient,
) -> None:
    response = client.post(
        "/model/predict",
        json={
            "location_x": 112.0,
            "location_y": 40.0,
            "body_part": "Right Foot",
            "technique": "Normal",
            "play_pattern": "Regular Play",
            "outcome": "Goal",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_validation_error"


def test_predict_goalpost_error_is_structured_and_not_a_503(client: TestClient) -> None:
    response = client.post(
        "/model/predict",
        json={
            "location_x": 120.0,
            "location_y": 36.0,
            "body_part": "Right Foot",
            "technique": "Normal",
            "play_pattern": "Regular Play",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "input_compatibility_error"


def test_historical_predictions_are_publication_gated_closed_by_default(
    client: TestClient,
) -> None:
    response = client.get("/model/shots")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "publication_gate_closed"


def test_repeated_historical_filter_is_a_structured_query_error(client: TestClient) -> None:
    response = client.get("/model/shots?team=A&team=B")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_filter"


@pytest.mark.parametrize("parameter", ["sort", "fields", "arbitrary"])
def test_unknown_historical_filter_is_rejected_by_the_exact_allowlist(
    client: TestClient, parameter: str
) -> None:
    response = client.get("/model/shots", params={parameter: "value"})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "invalid_filter"
    assert body["error"]["details"][0]["field"] == parameter


def test_legacy_shots_keeps_fastapi_validation_shape(client: TestClient) -> None:
    response = client.get("/shots", params={"limit": 0})
    assert response.status_code == 422
    assert "detail" in response.json()
    assert "error" not in response.json()


def test_model_requests_reuse_startup_runtime_without_reloading_artifact(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected_reload(cls: type[ModelRuntime]) -> ModelRuntime:
        del cls
        raise AssertionError("model-aware requests must not reload the serving bundle")

    monkeypatch.setattr(ModelRuntime, "load", classmethod(unexpected_reload))
    assert client.get("/model").status_code == 200
    assert client.get("/model/metrics").status_code == 200
    assert (
        client.post(
            "/model/predict",
            json={
                "location_x": 112.0,
                "location_y": 40.0,
                "body_part": "Right Foot",
                "technique": "Normal",
                "play_pattern": "Regular Play",
            },
        ).status_code
        == 200
    )


def test_metrics_endpoint_never_connects_to_database(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected_connect(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("qualified metrics must not be recomputed from PostgreSQL")

    monkeypatch.setattr(psycopg, "connect", unexpected_connect)
    assert client.get("/model/metrics").status_code == 200


def test_deterministic_bundle_corruption_aborts_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_startup(cls: type[ModelRuntime]) -> ModelRuntime:
        del cls
        raise ServingBundleError("serving_bundle_hash_mismatch", "deliberate test corruption")

    monkeypatch.setattr(ModelRuntime, "load", classmethod(fail_startup))
    with (
        pytest.raises(ServingBundleError, match="serving_bundle_hash_mismatch"),
        TestClient(app),
    ):
        pass
