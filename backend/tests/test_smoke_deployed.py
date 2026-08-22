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
from fastapi.testclient import TestClient

from touchline.main import app

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
        "detail": None,
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
        "detail": None,
        field_name: wrong_value,
    }
    problems = smoke.ready_problems(body)
    assert len(problems) == 1
    assert field_name in problems[0]


def test_ready_problems_rejects_operational_detail_while_ready(smoke: Any) -> None:
    body = {
        "status": "ready",
        "database": "reachable",
        "database_schema": "current",
        "model_runtime": "ready",
        "model_version": smoke.EXPECTED_RELEASE_ID,
        "detail": "unexpected healthy detail",
    }
    assert any("detail" in problem for problem in smoke.ready_problems(body))


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
        "access-control-allow-methods": "GET, POST, OPTIONS",
        "access-control-allow-headers": "Content-Type, X-Request-ID",
        "access-control-max-age": "600",
        "vary": "Origin",
        "x-request-id": request_id,
    }
    assert smoke.preflight_problems(smoke.Response(200, "OK", headers), origin, request_id) == []
    for field in (
        "access-control-allow-origin",
        "access-control-allow-methods",
        "access-control-allow-headers",
        "access-control-max-age",
        "vary",
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


def test_health_requires_the_exact_public_envelope(smoke: Any) -> None:
    valid = {"status": "ok", "environment": "production", "version": "0.1.0"}
    assert smoke.health_problems(valid) == []
    for broken in ({**valid, "extra": "secret"}, {**valid, "environment": True}):
        assert smoke.health_problems(broken)


def test_operational_leakage_guard_is_recursive(smoke: Any) -> None:
    assert smoke._operational_leaks({"nested": {"password": "secret"}})
    assert smoke._operational_leaks({"detail": "postgresql://user:secret@example/db"})
    assert smoke._operational_leaks({"detail": "Traceback: driver failure"})
    assert smoke._operational_leaks({"status": "ready", "database": "reachable"}) == []


@pytest.mark.parametrize(
    "payload",
    [
        {"url": "redacted"},
        {"callbackUri": "redacted"},
        {"database_uri": "redacted"},
        {"connection_uri": "redacted"},
        {"postgres_host": "db.internal"},
        {"detail": "password=not-for-public-output"},
        {"detail": "host=db.internal user=touchline dbname=touchline"},
    ],
)
def test_operational_leakage_guard_catches_connection_vocabulary(
    smoke: Any, payload: dict[str, Any]
) -> None:
    assert smoke._operational_leaks(payload)


def test_operational_leakage_guard_allows_public_readiness_values(smoke: Any) -> None:
    assert (
        smoke._operational_leaks(
            {
                "status": "ready",
                "database": "reachable",
                "database_schema": "current",
                "model_runtime": "ready",
                "model_version": smoke.EXPECTED_RELEASE_ID,
                "detail": None,
            }
        )
        == []
    )


def _baseline_body(smoke: Any) -> dict[str, Any]:
    return {
        "method": "descriptive-prevalence",
        "conversion_rate": smoke.EXPECTED_COHORT_GOALS / smoke.EXPECTED_COHORT_SHOTS,
        "shots": smoke.EXPECTED_COHORT_SHOTS,
        "goals": smoke.EXPECTED_COHORT_GOALS,
        "cohort": smoke.EXPECTED_BASELINE_COHORT,
        "caveat": smoke.EXPECTED_BASELINE_CAVEAT,
    }


def test_baseline_requires_exact_keys_values_types_and_quotient(smoke: Any) -> None:
    valid = _baseline_body(smoke)
    assert smoke.baseline_problems(valid) == []
    for broken in (
        {**valid, "extra": 1},
        {**valid, "shots": True},
        {**valid, "conversion_rate": float("nan")},
        {**valid, "conversion_rate": valid["conversion_rate"] + 1e-12},
        {**valid, "cohort": "close enough"},
        {**valid, "caveat": "not a model"},
    ):
        assert smoke.baseline_problems(broken)


def _shot_page(smoke: Any) -> dict[str, Any]:
    shot = {
        "shot_id": "shot-1",
        "match_id": 1,
        "match_date": "2022-11-20",
        "competition_stage": "Group Stage",
        "team": "A",
        "opponent": "B",
        "player": None,
        "period": 1,
        "minute": 3,
        "second": 4,
        "location_x": 100.0,
        "location_y": 40.0,
        "outcome": "Saved",
        "shot_type": "Open Play",
        "body_part": None,
        "technique": None,
    }
    return {"shots": [shot], "total": smoke.EXPECTED_TOTAL_SHOTS, "limit": 1, "offset": 0}


def test_shots_requires_exact_page_and_shot_contract(smoke: Any) -> None:
    valid = _shot_page(smoke)
    assert smoke.shot_page_problems(valid) == []
    mutations = [{**valid, "total": True}, {**valid, "limit": 2}, {**valid, "offset": 1}]
    for field, value in (
        ("match_id", True),
        ("location_x", float("inf")),
        ("match_date", "20/11/2022"),
    ):
        body = json.loads(json.dumps(valid))
        body["shots"][0][field] = value
        mutations.append(body)
    extra = json.loads(json.dumps(valid))
    extra["shots"][0]["expected_goals"] = 0.3
    mutations.append(extra)
    benign_extra = json.loads(json.dumps(valid))
    benign_extra["shots"][0]["new_fact"] = "unexpected"
    mutations.append(benign_extra)
    for broken in mutations:
        assert smoke.shot_page_problems(broken)


def test_score_name_detection_catches_variants_without_flagging_shot_facts(smoke: Any) -> None:
    legitimate = {key: None for key in smoke.SHOT_KEYS}
    assert smoke._probability_like_fields(legitimate) == []
    for field in (
        "expectedGoals",
        "goal_chance",
        "modelScore",
        "model_output",
        "shot-quality",
        "scoringLikelihood",
        "estimated_probability",
        "confidence",
        "quality_rating",
        "chance score",
        "x_g",
        "prob",
        "goal_prob",
        "shotProb",
        "chance_quality",
        "Chance-Quality",
    ):
        assert smoke._probability_like_fields({field: 0.2})


def test_visible_text_excludes_nonrendered_sources_and_joins_react_fragments(smoke: Any) -> None:
    html = """
      <head><title>Qualified evidence</title></head>
      <script>Data provided by StatsBomb</script><style>.x{}</style>
      <template>publication_gate_closed</template><noscript>One-time tournament holdout</noscript>
      <!-- What this view does not claim -->
      <div hidden>Historical shot map is not publicly enabled</div>
      <div aria-hidden="true">Shot quality, made inspectable.</div>
      <div style="display: none">secret</div><div style="visibility:hidden">secret2</div>
      <p>2872<!-- --> shots</p><p>Data provided by <strong>StatsBomb</strong></p>
    """
    text = smoke._visible_text(html)
    assert "2872 shots" in text
    assert "Data provided by StatsBomb" in text
    for hidden in ("Qualified evidence", "publication_gate_closed", "secret", "made inspectable"):
        assert hidden not in text


def test_visible_text_survives_nextjs_head_void_elements(smoke: Any) -> None:
    html = """
      <html><head><meta charset="utf-8"><link rel="stylesheet" href="app.css"></head>
      <body>VISIBLE BODY ANCHOR</body></html>
    """
    assert smoke._visible_text(html) == "VISIBLE BODY ANCHOR"


def test_visible_text_survives_void_elements_in_head_and_body(smoke: Any) -> None:
    html = """
      <head><base href="/"><meta><link><source><track></head>
      <body>before<br>after<img alt="attribute text"><input hidden value="hidden value">
      after input<hr>wbr<wbr></body>
    """
    text = smoke._visible_text(html)
    assert "before after" in text
    assert "after input" in text
    assert "wbr" in text
    assert "attribute text" not in text
    assert "hidden value" not in text


def test_visible_text_restores_visibility_after_nested_hidden_sibling(smoke: Any) -> None:
    html = """
      <main><section hidden><div><span>HIDDEN</span></div></section>
      <section><p>VISIBLE SIBLING</p></section></main>
    """
    assert smoke._visible_text(html) == "VISIBLE SIBLING"


def test_realistic_nextjs_analyst_html_satisfies_frontend_contract(smoke: Any) -> None:
    anchors = "</p><p>".join(smoke.REQUIRED_FRONTEND_TEXT)
    html = f"""
      <!doctype html><html><head><meta charset="utf-8">
      <meta name="viewport" content="width=device-width">
      <link rel="preload" href="app.css"><script>window.__next_f=[]</script></head>
      <body><div id="__next"><main><h1>{smoke.REQUIRED_FRONTEND_TEXT[0]}</h1>
      <p>{anchors}</p><p>{smoke.EXPECTED_DEVELOPMENT_SHOTS}<!-- --> shots</p>
      </main></div><script>Model metadata unavailable</script></body></html>
    """
    assert smoke.frontend_problems(html) == []


def test_react_stream_promoted_hidden_analyst_segment_is_visible(smoke: Any) -> None:
    anchors = "</p><p>".join(smoke.REQUIRED_FRONTEND_TEXT)
    html = f"""
      <html><head><meta><link></head><body>
      <!--$?--><template id="B:1"></template><div>Loading model evidence...</div><!--/$-->
      <div hidden id="S:1"><main><h1>Shot quality, made inspectable.</h1>
      <p>{anchors}</p></main></div>
      <script>$RC=function(b,c){{/* React replacement implementation */}};$RC("B:1","S:1")</script>
      </body></html>
    """
    assert smoke.frontend_problems(html) == []
    assert "Loading model evidence" in smoke._visible_text(html)


def test_arbitrary_hidden_stream_segment_stays_hidden_without_promotion(smoke: Any) -> None:
    html = """
      <template id="B:1"></template><div hidden id="S:1">SECRET ANCHOR</div>
      <script>const harmless = "S:1";</script><p>VISIBLE</p>
    """
    text = smoke._visible_text(html)
    assert "SECRET ANCHOR" not in text
    assert text == "VISIBLE"


@pytest.mark.parametrize(
    "instruction",
    [
        '$RC("B:1","S:2")',
        '$RC("B:2","S:1")',
        '$RC("B:1","S:1")',
    ],
)
def test_missing_or_mismatched_react_promotion_does_not_unhide(
    smoke: Any, instruction: str
) -> None:
    boundary = "" if instruction == '$RC("B:1","S:1")' else '<template id="B:1"></template>'
    html = (
        f'{boundary}<div hidden id="S:1">HIDDEN</div><script>{instruction}</script><p>VISIBLE</p>'
    )
    assert smoke._visible_text(html) == "VISIBLE"


def test_react_promotion_rejects_existing_but_mismatched_boundary_and_segment(smoke: Any) -> None:
    html = """
      <template id="B:1"></template><div hidden id="S:2">HIDDEN</div>
      <script>$RC("B:1","S:2")</script><p>VISIBLE</p>
    """
    assert smoke._visible_text(html) == "VISIBLE"


def test_react_flight_script_anchor_text_never_counts_as_visible(smoke: Any) -> None:
    html = """
      <template id="B:1"></template><div hidden id="S:1">ACTUAL SEGMENT</div>
      <script>
        self.__next_f.push([1,"Shot quality, made inspectable. Data provided by StatsBomb"]);
        $RC("B:1","S:1")
      </script>
    """
    text = smoke._visible_text(html)
    assert text == "ACTUAL SEGMENT"
    assert "StatsBomb" not in text


def test_react_two_stage_stream_insertion_reaches_promoted_outer_segment(smoke: Any) -> None:
    anchors = "</p><p>".join(smoke.REQUIRED_FRONTEND_TEXT)
    html = f"""
      <!--$?--><template id="B:0"></template><div>Loading...</div><!--/$-->
      <div hidden id="S:0"><template id="P:1"></template></div>
      <div hidden id="S:1"><main><h1>Shot quality, made inspectable.</h1>
      <p>{anchors}</p></main></div>
      <script>$RS("S:1","P:1")</script><script>$RC("B:0","S:0")</script>
    """
    assert smoke.frontend_problems(html) == []


@pytest.mark.parametrize(
    "instructions",
    [
        '$RC("B:0","S:0")',
        '$RS("S:1","P:1")',
        '$RS("S:1","P:2");$RC("B:0","S:0")',
        '$RS("S:2","P:1");$RC("B:0","S:0")',
    ],
)
def test_react_two_stage_stream_rejects_orphan_or_mismatched_links(
    smoke: Any, instructions: str
) -> None:
    html = f"""
      <template id="B:0"></template>
      <div hidden id="S:0"><template id="P:1"></template></div>
      <div hidden id="S:1">INNER CONTENT</div><script>{instructions}</script><p>VISIBLE</p>
    """
    text = smoke._visible_text(html)
    assert "INNER CONTENT" not in text
    assert "VISIBLE" in text


def test_react_two_stage_script_payload_anchors_stay_nonvisible(smoke: Any) -> None:
    html = """
      <template id="B:0"></template>
      <div hidden id="S:0"><template id="P:1"></template></div>
      <div hidden id="S:1">ACTUAL</div>
      <script>const payload="Data provided by StatsBomb";$RS("S:1","P:1");$RC("B:0","S:0")</script>
    """
    assert smoke._visible_text(html) == "ACTUAL"


@pytest.mark.parametrize(
    "fake_call",
    [
        '// $RC("B:1","S:1")',
        '/* $RC("B:1","S:1") */',
        'const x = \'$RC("B:1","S:1")\';',
        "const x = \"$RC('B:1','S:1')\";",
        'const x = `$RC("B:1","S:1")`;',
    ],
)
def test_inert_javascript_rc_calls_do_not_promote_hidden_segments(
    smoke: Any, fake_call: str
) -> None:
    html = f"""
      <template id="B:1"></template><div hidden id="S:1">HIDDEN</div>
      <script>{fake_call}</script><p>VISIBLE</p>
    """
    assert smoke._visible_text(html) == "VISIBLE"


def test_mixed_fake_and_real_rc_calls_promote_only_via_executable_call(smoke: Any) -> None:
    html = """
      <template id="B:1"></template><div hidden id="S:1">PROMOTED</div>
      <script>/* $RC("B:9","S:9") */;const fake=`$RC("B:8","S:8")`;$RC("B:1","S:1")</script>
    """
    assert smoke._visible_text(html) == "PROMOTED"


@pytest.mark.parametrize(
    "fake_rs",
    [
        '// $RS("S:1","P:1")',
        '/* $RS("S:1","P:1") */',
        'const x = \'$RS("S:1","P:1")\';',
        'const x = `$RS("S:1","P:1")`;',
    ],
)
def test_inert_javascript_rs_calls_do_not_insert_hidden_segments(smoke: Any, fake_rs: str) -> None:
    html = f"""
      <template id="B:0"></template>
      <div hidden id="S:0"><template id="P:1"></template></div>
      <div hidden id="S:1">HIDDEN INNER</div>
      <script>{fake_rs};$RC("B:0","S:0")</script><p>VISIBLE</p>
    """
    text = smoke._visible_text(html)
    assert "HIDDEN INNER" not in text
    assert "VISIBLE" in text


@pytest.mark.parametrize(
    "regex_literal",
    [
        'const re=/$RC("B:1","S:1")/;',
        r'const re=/[/$]$RC\("B:1","S:1"\)\/tail/gi;',
    ],
)
def test_javascript_regex_literal_rc_text_does_not_promote_hidden_segments(
    smoke: Any, regex_literal: str
) -> None:
    html = f"""
      <template id="B:1"></template><div hidden id="S:1">HIDDEN</div>
      <script>{regex_literal}</script><p>VISIBLE</p>
    """
    assert smoke._visible_text(html) == "VISIBLE"


@pytest.mark.parametrize(
    "regex_literal",
    [
        'const re=/$RS("S:1","P:1")/;',
        r'const re=/[/$]$RS\("S:1","P:1"\)\/tail/u;',
    ],
)
def test_javascript_regex_literal_rs_text_does_not_insert_hidden_segments(
    smoke: Any, regex_literal: str
) -> None:
    html = f"""
      <template id="B:0"></template>
      <div hidden id="S:0"><template id="P:1"></template></div>
      <div hidden id="S:1">HIDDEN INNER</div>
      <script>{regex_literal};$RC("B:0","S:0")</script><p>VISIBLE</p>
    """
    text = smoke._visible_text(html)
    assert "HIDDEN INNER" not in text
    assert "VISIBLE" in text


@pytest.mark.parametrize("keyword", ["return", "throw", "yield"])
def test_javascript_keyword_prefixed_regex_rc_text_does_not_promote_hidden_segments(
    smoke: Any, keyword: str
) -> None:
    html = f"""
      <template id="B:1"></template><div hidden id="S:1">HIDDEN</div>
      <script>function f(){{{keyword} /$RC("B:1","S:1")/}}</script><p>VISIBLE</p>
    """
    assert smoke._visible_text(html) == "VISIBLE"


@pytest.mark.parametrize("keyword", ["return", "throw", "yield"])
def test_javascript_keyword_prefixed_regex_rs_text_does_not_insert_hidden_segments(
    smoke: Any, keyword: str
) -> None:
    html = f"""
      <template id="B:0"></template>
      <div hidden id="S:0"><template id="P:1"></template></div>
      <div hidden id="S:1">HIDDEN INNER</div>
      <script>function f(){{{keyword} /$RS("S:1","P:1")/}};$RC("B:0","S:0")</script>
      <p>VISIBLE</p>
    """
    text = smoke._visible_text(html)
    assert "HIDDEN INNER" not in text
    assert "VISIBLE" in text


def test_division_does_not_hide_a_following_executable_react_call(smoke: Any) -> None:
    html = """
      <template id="B:1"></template><div hidden id="S:1">DIRECT</div>
      <script>const ratio=10 / $RC("B:1","S:1")</script>
    """
    assert smoke._visible_text(html) == "DIRECT"


def test_executable_rc_literal_call_remains_supported(smoke: Any) -> None:
    html = """
      <template id="B:1"></template><div hidden id="S:1">DIRECT</div>
      <script>$RC ( 'B:1' , "S:1" )</script>
    """
    assert smoke._visible_text(html) == "DIRECT"


def test_executable_rs_then_rc_literal_calls_remain_supported(smoke: Any) -> None:
    html = """
      <template id="B:0"></template>
      <div hidden id="S:0"><template id="P:1"></template></div>
      <div hidden id="S:1">INSERTED</div>
      <script>$RS("S:1",'P:1');$RC('B:0',"S:0")</script>
    """
    assert smoke._visible_text(html) == "INSERTED"


def test_main_returns_nonzero_when_any_gate_fails(
    smoke: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        sys, "argv", ["smoke_deployed.py", "--api", "https://api", "--frontend", "https://frontend"]
    )
    monkeypatch.setattr(
        smoke, "check_api", lambda api, results: results.check("failed gate", False)
    )
    monkeypatch.setattr(smoke, "load_golden_fixture", lambda: ({"cases": []}, None))
    monkeypatch.setattr(smoke, "check_model_surface", lambda api, results, fixture: None)
    monkeypatch.setattr(smoke, "check_request_id", lambda api, frontend, results: None)
    monkeypatch.setattr(smoke, "check_cors", lambda api, frontend, results: None)
    monkeypatch.setattr(smoke, "check_frontend", lambda frontend, results: None)
    assert smoke.main() == 1


def test_main_returns_zero_when_every_gate_passes(
    smoke: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        sys, "argv", ["smoke_deployed.py", "--api", "https://api", "--frontend", "https://frontend"]
    )
    monkeypatch.setattr(
        smoke, "check_api", lambda api, results: results.check("passing gate", True)
    )
    monkeypatch.setattr(smoke, "load_golden_fixture", lambda: ({"cases": []}, None))
    monkeypatch.setattr(smoke, "check_model_surface", lambda api, results, fixture: None)
    monkeypatch.setattr(smoke, "check_request_id", lambda api, frontend, results: None)
    monkeypatch.setattr(smoke, "check_cors", lambda api, frontend, results: None)
    monkeypatch.setattr(smoke, "check_frontend", lambda frontend, results: None)
    assert smoke.main() == 0


def test_disallowed_preflight_requires_exact_rejection_headers(smoke: Any) -> None:
    request_id = str(uuid.uuid4())
    headers = {
        "access-control-allow-methods": "GET, POST, OPTIONS",
        "access-control-allow-headers": "Content-Type, X-Request-ID",
        "access-control-max-age": "600",
        "vary": "Origin",
        "x-request-id": request_id,
    }
    response = smoke.Response(400, "Disallowed CORS origin", headers)
    assert (
        smoke.preflight_problems(response, "https://bad.invalid", request_id, allowed=False) == []
    )
    assert smoke.preflight_problems(
        smoke.Response(200, "OK", headers), "https://bad.invalid", request_id, allowed=False
    )
    credentialed = {**headers, "access-control-allow-credentials": "true"}
    assert smoke.preflight_problems(
        smoke.Response(400, "", credentialed), "https://bad.invalid", request_id, allowed=False
    )
    granted = {**headers, "access-control-allow-origin": "https://bad.invalid"}
    assert smoke.preflight_problems(
        smoke.Response(400, "", granted), "https://bad.invalid", request_id, allowed=False
    )


def test_simple_cors_requires_exact_tokens_and_no_credentials(smoke: Any) -> None:
    origin = "https://touchline-intelligence.vercel.app"
    request_id = str(uuid.uuid4())
    headers = {
        "access-control-allow-origin": origin,
        "access-control-expose-headers": "X-Request-ID",
        "vary": "Origin",
        "x-request-id": request_id,
    }
    assert smoke.simple_cors_problems(smoke.Response(200, "", headers), origin, request_id) == []
    for broken in (
        {**headers, "access-control-expose-headers": "not-x-request-id"},
        {**headers, "access-control-expose-headers": "X-Request-ID, Authorization"},
        {**headers, "access-control-allow-credentials": "true"},
    ):
        assert smoke.simple_cors_problems(smoke.Response(200, "", broken), origin, request_id)
    disallowed_headers = {
        "access-control-expose-headers": "X-Request-ID",
        "x-request-id": request_id,
    }
    assert (
        smoke.simple_cors_problems(
            smoke.Response(200, "", disallowed_headers), origin, request_id, allowed=False
        )
        == []
    )
    assert smoke.simple_cors_problems(
        smoke.Response(200, "", {"x-request-id": request_id}),
        origin,
        request_id,
        allowed=False,
    )


def test_simple_cors_matches_actual_allowed_and_disallowed_starlette_shapes() -> None:
    request_id = "00000000-0000-4000-8000-000000000019"
    with TestClient(app) as client:
        allowed = client.get(
            "/health", headers={"Origin": "http://localhost:3000", "X-Request-ID": request_id}
        )
        disallowed = client.get(
            "/health", headers={"Origin": "https://bad.invalid", "X-Request-ID": request_id}
        )
    smoke = _load_script()
    assert (
        smoke.simple_cors_problems(
            smoke.Response(allowed.status_code, allowed.text, dict(allowed.headers)),
            "http://localhost:3000",
            request_id,
        )
        == []
    )
    assert (
        smoke.simple_cors_problems(
            smoke.Response(disallowed.status_code, disallowed.text, dict(disallowed.headers)),
            "https://bad.invalid",
            request_id,
            allowed=False,
        )
        == []
    )


def test_error_simple_cors_requires_allow_origin_and_exact_status(smoke: Any) -> None:
    origin = "https://touchline-intelligence.vercel.app"
    request_id = str(uuid.uuid4())
    headers = {
        "access-control-allow-origin": origin,
        "access-control-expose-headers": "X-Request-ID",
        "vary": "Origin",
        "x-request-id": request_id,
    }
    assert (
        smoke.simple_cors_problems(
            smoke.Response(403, "", headers), origin, request_id, expected_status=403
        )
        == []
    )
    without_origin = {
        key: value for key, value in headers.items() if key != "access-control-allow-origin"
    }
    assert smoke.simple_cors_problems(
        smoke.Response(403, "", without_origin), origin, request_id, expected_status=403
    )
