"""Offline contracts for the WP3.4 deployed smoke script.

``scripts/smoke_deployed.py`` runs against a live deployment, so these tests exercise its pure
validation logic directly: the golden-fixture loader and tolerance, the provenance gate, the
public prediction-contract comparison, the closed publication-gate shape, the full readiness
state, request-ID correlation, the pinned metrics identity, and the analyst-page render checks.
The mutation harness breaks each of these behaviours once; a validator that stops rejecting a
broken deployment must fail here.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from pathlib import Path
from typing import Any, cast

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "smoke_deployed.py"
FIXTURE = ROOT / "backend" / "tests" / "fixtures" / "wp3_1_golden_cases.json"
_MODULE_NAME = "smoke_deployed_under_test"


def _load_script() -> Any:
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def smoke() -> Any:
    return _load_script()


@pytest.fixture(scope="module")
def fixture() -> dict[str, Any]:
    loaded: dict[str, Any] | None
    loaded, error = _load_script().load_golden_fixture(FIXTURE)
    assert loaded is not None, error
    return loaded


def _metadata(smoke: Any, fixture: dict[str, Any]) -> dict[str, Any]:
    """A /model body consistent with the fixture's recorded provenance."""
    assert smoke.EXPECTED_PROVENANCE["artifact_sha256"] == fixture["model_sha256"]
    assert (
        smoke.EXPECTED_PROVENANCE["calibration_decision_sha256"]
        == fixture["calibration_decision_sha256"]
    )
    return cast(dict[str, Any], json.loads(json.dumps(smoke.EXPECTED_MODEL_METADATA)))


@pytest.fixture(scope="module")
def metadata(smoke: Any, fixture: dict[str, Any]) -> dict[str, Any]:
    return _metadata(smoke, fixture)


def test_golden_fixture_loads_and_declares_its_tolerance(
    smoke: Any, fixture: dict[str, Any]
) -> None:
    assert fixture["cases"]
    assert smoke.golden_tolerance(fixture) == fixture["absolute_tolerance"]


def test_golden_tolerance_follows_the_fixture_not_a_constant(smoke: Any) -> None:
    loose = {"absolute_tolerance": 0.5}
    tight = {"absolute_tolerance": 1e-12}
    assert smoke.golden_tolerance(loose) == 0.5
    assert smoke.golden_tolerance(tight) == 1e-12


def test_golden_fixture_loader_rejects_unusable_inputs(smoke: Any, tmp_path: Path) -> None:
    missing, missing_error = smoke.load_golden_fixture(tmp_path / "absent.json")
    assert missing is None and missing_error

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not json", encoding="utf-8")
    parsed, parsed_error = smoke.load_golden_fixture(invalid)
    assert parsed is None and parsed_error

    empty_cases = tmp_path / "empty-cases.json"
    empty_cases.write_text(json.dumps({"absolute_tolerance": 1e-12, "cases": []}), encoding="utf-8")
    empty, empty_error = smoke.load_golden_fixture(empty_cases)
    assert empty is None and empty_error

    no_tolerance = tmp_path / "no-tolerance.json"
    no_tolerance.write_text(json.dumps({"cases": [{"name": "x"}]}), encoding="utf-8")
    untolerated, untolerated_error = smoke.load_golden_fixture(no_tolerance)
    assert untolerated is None and untolerated_error

    for index, tolerance in enumerate((float("nan"), float("inf"), float("-inf"), True, 0, -1)):
        bad = tmp_path / f"bad-tolerance-{index}.json"
        bad.write_text(
            json.dumps(
                {
                    "absolute_tolerance": tolerance,
                    "cases": [{"name": "x", "expected": {"calibrated_probability": 0.5}}],
                }
            ),
            encoding="utf-8",
        )
        loaded, error = smoke.load_golden_fixture(bad)
        assert loaded is None and error

    for index, probability in enumerate(
        (float("nan"), float("inf"), float("-inf"), True, -0.1, 1.1)
    ):
        bad = tmp_path / f"bad-expected-probability-{index}.json"
        bad.write_text(
            json.dumps(
                {
                    "absolute_tolerance": 1e-12,
                    "cases": [{"name": "x", "expected": {"calibrated_probability": probability}}],
                }
            ),
            encoding="utf-8",
        )
        loaded, error = smoke.load_golden_fixture(bad)
        assert loaded is None and error


def test_ready_problems_accepts_the_full_admission_state(smoke: Any) -> None:
    body = {
        "status": "ready",
        "database": "reachable",
        "database_schema": "current",
        "model_runtime": "ready",
        "model_version": smoke.EXPECTED_RELEASE_ID,
    }
    assert smoke.ready_problems(body) == []


@pytest.mark.parametrize(
    ("field_name", "wrong_value"),
    [
        ("status", "degraded"),
        ("database", "unreachable"),
        ("database_schema", "behind"),
        ("model_runtime", "not_ready"),
        ("model_version", "some-other-release"),
    ],
)
def test_ready_problems_rejects_each_degraded_field(
    smoke: Any, field_name: str, wrong_value: str
) -> None:
    body = {
        "status": "ready",
        "database": "reachable",
        "database_schema": "current",
        "model_runtime": "ready",
        "model_version": smoke.EXPECTED_RELEASE_ID,
        field_name: wrong_value,
    }
    problems = smoke.ready_problems(body)
    assert len(problems) == 1
    assert field_name in problems[0]


def test_model_metadata_problems_accepts_the_qualified_release(
    smoke: Any, metadata: dict[str, Any]
) -> None:
    assert smoke.model_metadata_problems(metadata) == []


def test_model_metadata_problems_rejects_identity_drift(
    smoke: Any, metadata: dict[str, Any]
) -> None:
    drifted = {**metadata, "candidate": "gradient_boosting"}
    problems = smoke.model_metadata_problems(drifted)
    assert any("candidate" in problem for problem in problems)

    drifted_scopes = {
        **metadata,
        "scopes": {
            **metadata["scopes"],
            "tournament_holdout": {"shots": 999, "matches": 10},
        },
    }
    scope_problems = smoke.model_metadata_problems(drifted_scopes)
    assert any("tournament_holdout" in problem for problem in scope_problems)

    undigested = {**metadata, "artifact_sha256": "not-a-digest"}
    assert any(
        "artifact_sha256" in problem for problem in smoke.model_metadata_problems(undigested)
    )

    boolean_count = json.loads(json.dumps(metadata))
    boolean_count["scopes"]["development"]["shots"] = True
    assert smoke.model_metadata_problems(boolean_count)

    unexpected = {**metadata, "provider_xg": 0.4}
    assert any(
        "unexpected fields" in problem for problem in smoke.model_metadata_problems(unexpected)
    )

    non_finite_bound = json.loads(json.dumps(metadata))
    non_finite_bound["input_contract"]["coordinates"]["location_x"]["maximum"] = float("nan")
    assert smoke.model_metadata_problems(non_finite_bound)


def test_provenance_gate_passes_on_matching_identities(
    smoke: Any, fixture: dict[str, Any], metadata: dict[str, Any]
) -> None:
    assert smoke.provenance_mismatches(fixture, metadata) == []


def test_provenance_gate_fails_when_the_served_model_differs(
    smoke: Any, fixture: dict[str, Any], metadata: dict[str, Any]
) -> None:
    other_model = {**metadata, "artifact_sha256": "d" * 64}
    problems = smoke.provenance_mismatches(fixture, other_model)
    assert len(problems) == 1
    assert "model_sha256" in problems[0]


def test_provenance_gate_fails_when_the_calibration_decision_differs(
    smoke: Any, fixture: dict[str, Any], metadata: dict[str, Any]
) -> None:
    other_decision = {**metadata, "calibration_decision_sha256": "e" * 64}
    problems = smoke.provenance_mismatches(fixture, other_decision)
    assert len(problems) == 1
    assert "calibration_decision_sha256" in problems[0]


def _predict_response(smoke: Any, case: dict[str, Any], probability: float) -> dict[str, Any]:
    return {
        **smoke.EXPECTED_PROVENANCE,
        "calibrated_probability": probability,
    }


def test_predict_case_matches_the_public_contract_only(smoke: Any, fixture: dict[str, Any]) -> None:
    case = fixture["cases"][0]
    expected_probability = case["expected"]["calibrated_probability"]
    response = _predict_response(smoke, case, expected_probability)
    tolerance = smoke.golden_tolerance(fixture)
    assert (
        smoke.predict_case_problems(case, response, tolerance, smoke.EXPECTED_MODEL_METADATA) == []
    )


def test_predict_case_tolerates_only_the_declared_deviation(
    smoke: Any, fixture: dict[str, Any]
) -> None:
    case = fixture["cases"][0]
    expected_probability = float(case["expected"]["calibrated_probability"])
    tolerance = float(smoke.golden_tolerance(fixture))
    near = _predict_response(smoke, case, expected_probability + (tolerance / 2))
    far = _predict_response(smoke, case, expected_probability + (tolerance * 10))
    assert smoke.predict_case_problems(case, near, tolerance, smoke.EXPECTED_MODEL_METADATA) == []
    problems = smoke.predict_case_problems(case, far, tolerance, smoke.EXPECTED_MODEL_METADATA)
    assert len(problems) == 1
    assert "beyond the fixture tolerance" in problems[0]


def test_predict_case_rejects_internal_oracle_leakage(smoke: Any, fixture: dict[str, Any]) -> None:
    case = fixture["cases"][0]
    expected_probability = case["expected"]["calibrated_probability"]
    leaking = _predict_response(smoke, case, expected_probability)
    leaking["base_logit"] = case["expected"]["base_logit"]
    problems = smoke.predict_case_problems(
        case, leaking, smoke.golden_tolerance(fixture), smoke.EXPECTED_MODEL_METADATA
    )
    assert len(problems) == 1
    assert "outside the public prediction contract" in problems[0]
    assert "base_logit" in problems[0]


def test_predict_case_rejects_a_missing_public_field(smoke: Any, fixture: dict[str, Any]) -> None:
    case = fixture["cases"][0]
    response = _predict_response(smoke, case, case["expected"]["calibrated_probability"])
    del response["serving_manifest_sha256"]
    problems = smoke.predict_case_problems(
        case, response, smoke.golden_tolerance(fixture), smoke.EXPECTED_MODEL_METADATA
    )
    assert any("public contract fields absent" in problem for problem in problems)


def test_predict_case_rejects_a_foreign_release(smoke: Any, fixture: dict[str, Any]) -> None:
    case = fixture["cases"][0]
    response = _predict_response(smoke, case, case["expected"]["calibrated_probability"])
    response["release_id"] = "exp-19700101-someone-elses-model"
    problems = smoke.predict_case_problems(
        case, response, smoke.golden_tolerance(fixture), smoke.EXPECTED_MODEL_METADATA
    )
    assert any("release_id" in problem for problem in problems)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), True, -0.1, 1.1])
def test_predict_case_rejects_non_finite_or_unbounded_probabilities(
    smoke: Any, fixture: dict[str, Any], bad: Any
) -> None:
    case = fixture["cases"][0]
    response = _predict_response(smoke, case, bad)
    assert smoke.predict_case_problems(
        case, response, smoke.golden_tolerance(fixture), smoke.EXPECTED_MODEL_METADATA
    )


def test_predict_case_requires_exact_model_provenance(
    smoke: Any, fixture: dict[str, Any], metadata: dict[str, Any]
) -> None:
    case = fixture["cases"][0]
    response = {**metadata, "calibrated_probability": case["expected"]["calibrated_probability"]}
    for field in (
        "serving_manifest_sha256",
        "release_manifest_sha256",
        "release_manifest_file_sha256",
        "artifact_sha256",
        "calibration_decision_sha256",
    ):
        drifted = {**response, field: "9" * 64}
        assert any(
            field in problem
            for problem in smoke.predict_case_problems(
                case, drifted, smoke.golden_tolerance(fixture), metadata
            )
        )


def _closed_gate_body() -> dict[str, Any]:
    return {
        "error": {
            "code": "publication_gate_closed",
            "message": "public historical model shots are not enabled",
            "details": [],
        }
    }


def test_closed_model_shots_exactly_matches_the_closed_contract(smoke: Any) -> None:
    assert smoke.closed_model_shots_problems(403, _closed_gate_body()) == []


def test_closed_model_shots_flags_a_non_403_status_alone(smoke: Any) -> None:
    problems = smoke.closed_model_shots_problems(200, _closed_gate_body())
    assert problems == ["status=200, expected 403"]


def test_closed_model_shots_flags_the_wrong_code_alone(smoke: Any) -> None:
    wrong_code = {"error": {"code": "not_found", "message": "nope", "details": []}}
    problems = smoke.closed_model_shots_problems(403, wrong_code)
    assert len(problems) == 1
    assert "closed-gate error envelope" in problems[0]


def test_closed_model_shots_flags_leaked_probabilities_alone(smoke: Any) -> None:
    leaking_message = {
        "error": {
            "code": "publication_gate_closed",
            "message": "historical calibrated_probability values are not public",
            "details": [],
        }
    }
    problems = smoke.closed_model_shots_problems(403, leaking_message)
    assert any("closed-gate error envelope" in problem for problem in problems)


def test_closed_model_shots_rejects_an_open_response(smoke: Any) -> None:
    open_body = {
        "shots": [
            {"shot_id": "goal-1", "calibrated_probability": 0.42},
        ],
        "total": 1,
        "limit": 1,
        "offset": 0,
    }
    problems = smoke.closed_model_shots_problems(200, open_body)
    assert any("status=200" in problem for problem in problems)
    assert any("leaked" in problem for problem in problems)
    assert any("closed-gate error envelope" in problem for problem in problems)


def test_closed_model_shots_rejects_the_wrong_code(smoke: Any) -> None:
    wrong_code = {"error": {"code": "not_found", "message": "nope", "details": []}}
    problems = smoke.closed_model_shots_problems(403, wrong_code)
    assert any("closed-gate error envelope" in problem for problem in problems)


@pytest.mark.parametrize(
    "body",
    [
        {**_closed_gate_body(), "extra": "field"},
        {"error": {**_closed_gate_body()["error"], "extra": "field"}},
        {"error": {**_closed_gate_body()["error"], "message": "wrong"}},
        {"error": {**_closed_gate_body()["error"], "details": [{"field": "x"}]}},
        {"error": _closed_gate_body()["error"], "nested": {"model_prediction": 0.2}},
        {"error": _closed_gate_body()["error"], "statsbomb_xg": 0.2},
    ],
)
def test_closed_model_shots_rejects_any_envelope_drift_or_score_leak(
    smoke: Any, body: dict[str, Any]
) -> None:
    assert smoke.closed_model_shots_problems(403, body)


def _metrics_body(smoke: Any) -> dict[str, Any]:
    return {
        **smoke.EXPECTED_PROVENANCE,
        **json.loads(json.dumps(smoke.EXPECTED_METRICS_CONTENT)),
    }


def test_metrics_problems_accept_the_qualified_packet(smoke: Any, metadata: dict[str, Any]) -> None:
    body = _metrics_body(smoke)
    assert smoke.metrics_problems(body, metadata) == []


def test_metrics_problems_reject_packet_drift(smoke: Any, metadata: dict[str, Any]) -> None:
    base = _metrics_body(smoke)

    def with_holdout(**changes: Any) -> dict[str, Any]:
        body: dict[str, Any] = json.loads(json.dumps(base))
        body["tournament_holdout"].update(changes)
        return body

    assert smoke.metrics_problems(with_holdout(goals=97), metadata) != []
    drifted_prevalence = with_holdout(observed_prevalence=smoke.EXPECTED_HOLDOUT_PREVALENCE + 1e-6)
    prevalence_problems = smoke.metrics_problems(drifted_prevalence, metadata)
    assert any("observed_prevalence" in problem for problem in prevalence_problems)

    within_tolerance = with_holdout(
        observed_prevalence=smoke.EXPECTED_HOLDOUT_PREVALENCE + smoke.METRICS_FLOAT_TOLERANCE / 2
    )
    assert smoke.metrics_problems(within_tolerance, metadata) == []

    foreign_digest = json.loads(json.dumps(base))
    foreign_digest["evidence_source"]["holdout_metrics_sha256"] = "f" * 64
    digest_problems = smoke.metrics_problems(foreign_digest, metadata)
    assert any("holdout_metrics_sha256" in problem for problem in digest_problems)

    disagreeing_provenance = json.loads(json.dumps(base))
    disagreeing_provenance["artifact_sha256"] = "9" * 64
    assert any(
        "disagrees with /model provenance" in problem
        for problem in smoke.metrics_problems(disagreeing_provenance, metadata)
    )

    for bad in (float("nan"), float("inf"), float("-inf"), True):
        assert smoke.metrics_problems(with_holdout(observed_prevalence=bad), metadata)

    for path in (
        ("calibration_adoption", "calibrated", "log_loss"),
        ("calibration_adoption", "raw_anchor_reliability", 0, "raw_mean_prediction"),
        ("tournament_holdout", "uncertainty", "confidence_level"),
        ("tournament_holdout", "reliability", 0, "mean_prediction"),
        ("tournament_holdout", "raw_comparator", "proper_scoring", "brier"),
    ):
        broken = json.loads(json.dumps(base))
        cursor: Any = broken
        for part in path[:-1]:
            cursor = cursor[part]
        cursor[path[-1]] = float("nan")
        assert smoke.metrics_problems(broken, metadata)

    unexpected = {**base, "provider_xg": 0.3}
    assert any(
        "unexpected fields" in problem for problem in smoke.metrics_problems(unexpected, metadata)
    )

    malformed_nested = json.loads(json.dumps(base))
    malformed_nested["tournament_holdout"]["proper_scoring"] = []
    assert smoke.metrics_problems(malformed_nested, metadata)


def test_request_id_echo_contract(smoke: Any) -> None:
    sent = str(uuid.uuid4())
    assert smoke.request_id_echo_problems(sent, sent) == []
    other = str(uuid.uuid4())
    problems = smoke.request_id_echo_problems(sent, other)
    assert problems
    assert smoke.request_id_echo_problems(sent, None)


def test_request_id_replacement_contract(smoke: Any) -> None:
    malformed = "not-a-valid-request-id"
    fresh = str(uuid.uuid4())
    assert smoke.request_id_replacement_problems(malformed, fresh) == []

    echoed = smoke.request_id_replacement_problems(malformed, malformed)
    assert any("echoed" in problem for problem in echoed)

    non_uuid = smoke.request_id_replacement_problems(malformed, "0" * 31 + "g")
    assert any("canonical UUID" in problem for problem in non_uuid)


def test_frontend_problems_accept_the_expected_render(smoke: Any) -> None:
    fragments = list(smoke.REQUIRED_FRONTEND_TEXT)
    html = (
        "<p>" + "<!-- -->".join(fragments[:3]) + "</p><p>" + "</p><p>".join(fragments[3:]) + "</p>"
    )
    assert smoke.frontend_problems(html) == []


def test_frontend_problems_require_every_anchor(smoke: Any) -> None:
    html = "<p>Shot quality, made inspectable.</p>"
    problems = smoke.frontend_problems(html)
    assert len(problems) == len(smoke.REQUIRED_FRONTEND_TEXT) - 1
    assert all("missing expected page text" in problem for problem in problems)


def test_frontend_problems_forbid_error_states(smoke: Any) -> None:
    html = "<p>" + "</p><p>".join(smoke.REQUIRED_FRONTEND_TEXT) + "</p>"
    broken = html + "<p>Model identities do not agree</p>"
    problems = smoke.frontend_problems(broken)
    assert len(problems) == 1
    assert "error-state text present" in problems[0]


def test_frontend_requires_the_statsbomb_attribution_anchor(smoke: Any) -> None:
    assert "Data provided by StatsBomb" in smoke.REQUIRED_FRONTEND_TEXT

    without_attribution = [
        fragment
        for fragment in smoke.REQUIRED_FRONTEND_TEXT
        if fragment != "Data provided by StatsBomb"
    ]
    html = "<p>" + "</p><p>".join(without_attribution) + "</p>"
    problems = smoke.frontend_problems(html)
    assert len(problems) == 1
    assert "StatsBomb" in problems[0]

    generic_only = html + "<p>Data provided by</p>"
    assert smoke.frontend_problems(generic_only)


def test_recursive_probability_field_detection_preserves_facts_and_rejects_scores(
    smoke: Any,
) -> None:
    facts = {"shots": [{"shot_id": "x", "outcome": "Goal", "team": "A"}]}
    assert smoke._probability_like_fields(facts) == []
    for key in ("calibrated_probability", "goal_probabilities", "statsbomb_xg", "model_prediction"):
        assert smoke._probability_like_fields({"shots": [{"nested": {key: 0.2}}]})


def test_preflight_validator_requires_exact_origin_method_headers_and_request_id(
    smoke: Any,
) -> None:
    origin = "https://touchline.example"
    request_id = str(uuid.uuid4())
    headers = {
        "access-control-allow-origin": origin,
        "access-control-allow-methods": "POST",
        "access-control-allow-headers": "Content-Type, X-Request-ID",
        "x-request-id": request_id,
    }
    assert smoke.preflight_problems(smoke.Response(200, "OK", headers), origin, request_id) == []
    for field in (
        "access-control-allow-origin",
        "access-control-allow-methods",
        "access-control-allow-headers",
        "x-request-id",
    ):
        broken = {**headers}
        del broken[field]
        assert smoke.preflight_problems(smoke.Response(200, "OK", broken), origin, request_id)


def test_uuid_and_digest_helpers(smoke: Any) -> None:
    assert smoke._is_canonical_uuid(str(uuid.uuid4()))
    assert not smoke._is_canonical_uuid("UPPERCASE-NOT-CANONICAL")
    assert not smoke._is_canonical_uuid("hello")
    assert smoke._is_sha256_hex("a" * 64)
    assert not smoke._is_sha256_hex("a" * 63)
    assert not smoke._is_sha256_hex(None)
