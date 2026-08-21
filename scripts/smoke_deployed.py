"""Smoke-test a deployed Touchline instance.

    uv run python scripts/smoke_deployed.py --api https://... --frontend https://...

Runs against the *deployed* URLs, not a local process. CI does not run this - it has no
credentials and no deployment - so it is a release check, invoked by hand after a deploy and
recorded in the release notes.

WP0.6 introduced this script against the descriptive surface alone. WP3.4 extends the same
entry point because "the deployment works" now means more than the M0 facts:

- the M0 descriptive facts still hold (/health, /ready admission facts, /baseline, /shots);
- /ready reports the full four-field readiness state, not merely an HTTP 200;
- every response correlates through X-Request-ID, and a malformed inbound ID is replaced by a
  valid one rather than echoed;
- the CORS allow-list behaves exactly as configured;
- /model serves exactly the qualified release identity;
- after the golden fixture's recorded provenance matches what /model reports, /model/predict
  reproduces the frozen offline oracle's *public* outputs within the tolerance the fixture
  itself declares - internal oracle fields are never part of the comparison, and their
  appearance in a response is a failure;
- /model/shots stays publication-closed: HTTP 403, code publication_gate_closed, and no
  historical probabilities anywhere in the body;
- the deployed analyst page renders the qualified release, its scope counts, the reliability
  view, the limitations, the StatsBomb attribution, and the expected publication-gate state -
  and none of its error states.

It checks facts, not vibes. Every expected number is hard-coded against the pinned WC 2022
snapshot and the qualified exp-20260810-wp2_8-release packet; the golden prediction expectations
come from the checked-in fixture, never from the deployment being tested.

Exit code is 0 only if every check passes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# What the pinned WC 2022 snapshot must produce.
EXPECTED_TOTAL_SHOTS = 1494
EXPECTED_COHORT_SHOTS = 1430
EXPECTED_COHORT_GOALS = 152

# The one qualified serving release (WP2.8). Every model-aware endpoint must identify it.
EXPECTED_RELEASE_ID = "exp-20260810-wp2_8-release"

# Scope identities baked into the qualified release packet and asserted by the runtime loader.
EXPECTED_DEVELOPMENT_SHOTS = 2872
EXPECTED_DEVELOPMENT_MATCHES = 115
EXPECTED_CALIBRATION_SHOTS = 1430
EXPECTED_CALIBRATION_MATCHES = 64
EXPECTED_HOLDOUT_SHOTS = 1304
EXPECTED_HOLDOUT_MATCHES = 51
EXPECTED_HOLDOUT_GOALS = 98

# The qualified Euro 2024 holdout evidence, pinned from the WP2.7 packet that the serving
# bundle embeds. A deployment serving different numbers is serving something else entirely.
EXPECTED_HOLDOUT_METRICS_SHA256 = "3443b4a5e19fd87b1ee599502152a7dcfe1af3d8466c09ad7cbf2bb8cae2e674"
EXPECTED_HOLDOUT_PREVALENCE = 0.075153374233
EXPECTED_HOLDOUT_LOG_LOSS = 0.243112806225
EXPECTED_HOLDOUT_BRIER = 0.066029980705
EXPECTED_HOLDOUT_ROC_AUC = 0.744677970691
EXPECTED_HOLDOUT_PR_AUC = 0.223985679737
METRICS_FLOAT_TOLERANCE = 1e-9

# The public /model/predict contract: the seven provenance fields plus the one output field.
# Anything else in a response - base logits, selected vectors, internal column names - is the
# internal oracle leaking through the public boundary, and fails the smoke.
PUBLIC_PREDICT_KEYS = frozenset(
    {
        "model_version",
        "release_id",
        "serving_manifest_sha256",
        "release_manifest_sha256",
        "release_manifest_file_sha256",
        "artifact_sha256",
        "calibration_decision_sha256",
        "calibrated_probability",
    }
)

GOLDEN_FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent / "backend/tests/fixtures/wp3_1_golden_cases.json"
)

# An origin that is certainly not on the allow-list. `.invalid` is reserved by RFC 2606, so this
# can never collide with a real deployment.
DISALLOWED_ORIGIN = "https://smoke-test-disallowed.invalid"

TIMEOUT = 30


@dataclass
class Results:
    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        suffix = f" - {detail}" if detail else ""
        if ok:
            self.passed.append(name)
            print(f"  [PASS] {name}{suffix}")
        else:
            self.failed.append(name)
            print(f"  [FAIL] {name}{suffix}")


@dataclass(frozen=True)
class Response:
    status: int
    body: str
    headers: dict[str, str]

    def json(self) -> Any:
        try:
            return json.loads(self.body)
        except json.JSONDecodeError:
            return None


def _get(url: str, headers: dict[str, str] | None = None) -> Response:
    request = urllib.request.Request(
        url, headers={"User-Agent": "touchline-smoke/1.0", **(headers or {})}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read().decode("utf-8", errors="replace")
            return Response(
                response.status, body, {k.lower(): v for k, v in response.headers.items()}
            )
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return Response(exc.code, body, {k.lower(): v for k, v in exc.headers.items()})
    except urllib.error.URLError as exc:
        return Response(0, str(exc), {})


def _post_json(url: str, payload: dict[str, Any]) -> Response:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "touchline-smoke/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read().decode("utf-8", errors="replace")
            return Response(
                response.status, body, {k.lower(): v for k, v in response.headers.items()}
            )
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return Response(exc.code, body, {k.lower(): v for k, v in exc.headers.items()})
    except urllib.error.URLError as exc:
        return Response(0, str(exc), {})


def _visible_text(html: str) -> str:
    """Strip the comment markers React emits between adjacent text nodes.

    Server-rendered React writes `2872<!-- --> shots` for `{count} shots`, so a naive substring
    search for "2872 shots" fails against correct output. Removing the markers compares what a
    reader sees rather than how React framed it.
    """
    return re.sub(r"<!--.*?-->", "", html)


def _is_canonical_uuid(value: str) -> bool:
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        return False
    return str(parsed) == value


def _is_sha256_hex(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def load_golden_fixture(
    path: Path = GOLDEN_FIXTURE_PATH,
) -> tuple[dict[str, Any] | None, str | None]:
    """Load the checked-in golden oracle. Returns (fixture, error); exactly one is None."""
    try:
        fixture = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return None, f"{path}: {exc}"
    except json.JSONDecodeError as exc:
        return None, f"{path} is not valid JSON: {exc}"
    if not isinstance(fixture, dict):
        return None, f"{path} must contain a JSON object"
    if not isinstance(fixture.get("cases"), list) or not fixture["cases"]:
        return None, f"{path} carries no golden cases"
    tolerance = fixture.get("absolute_tolerance")
    if not isinstance(tolerance, (int, float)) or isinstance(tolerance, bool) or tolerance <= 0:
        return None, f"{path} does not declare a usable absolute_tolerance"
    return fixture, None


def ready_problems(body: Any) -> list[str]:
    """The full WP3.3 admission contract: three independent subsystems plus the release label."""
    problems: list[str] = []
    if not isinstance(body, dict):
        return ["response body is not a JSON object"]
    if body.get("status") != "ready":
        problems.append(f"status={body.get('status')!r}, expected 'ready'")
    if body.get("database") != "reachable":
        problems.append(f"database={body.get('database')!r}, expected 'reachable'")
    if body.get("database_schema") != "current":
        problems.append(f"database_schema={body.get('database_schema')!r}, expected 'current'")
    if body.get("model_runtime") != "ready":
        problems.append(f"model_runtime={body.get('model_runtime')!r}, expected 'ready'")
    if body.get("model_version") != EXPECTED_RELEASE_ID:
        problems.append(
            f"model_version={body.get('model_version')!r}, expected {EXPECTED_RELEASE_ID!r}"
        )
    return problems


def model_metadata_problems(body: Any) -> list[str]:
    """The qualified release identity: names, statuses, and scope membership counts."""
    problems: list[str] = []
    if not isinstance(body, dict):
        return ["response body is not a JSON object"]

    for field_name in ("model_version", "release_id"):
        if body.get(field_name) != EXPECTED_RELEASE_ID:
            problems.append(
                f"{field_name}={body.get(field_name)!r}, expected {EXPECTED_RELEASE_ID!r}"
            )
    expected_statuses = {
        "release_status": "m2_qualified",
        "qualification_serving_status": "not_served",
        "runtime_status": "ready",
        "candidate": "full_minus_presence",
        "estimator": "logistic_regression",
        "calibration": "platt_sigmoid",
        "adopted_variant": "calibrated",
        "output": "goal_conversion_probability",
    }
    for field_name, expected in expected_statuses.items():
        if body.get(field_name) != expected:
            problems.append(f"{field_name}={body.get(field_name)!r}, expected {expected!r}")
    for field_name in (
        "serving_manifest_sha256",
        "release_manifest_sha256",
        "release_manifest_file_sha256",
        "artifact_sha256",
        "calibration_decision_sha256",
    ):
        if not _is_sha256_hex(body.get(field_name)):
            problems.append(f"{field_name} is not a SHA-256 hex digest")

    scopes = body.get("scopes")
    if not isinstance(scopes, dict):
        problems.append("scopes block missing")
    else:
        expected_scopes = {
            "development": (EXPECTED_DEVELOPMENT_SHOTS, EXPECTED_DEVELOPMENT_MATCHES),
            "calibration": (EXPECTED_CALIBRATION_SHOTS, EXPECTED_CALIBRATION_MATCHES),
            "tournament_holdout": (EXPECTED_HOLDOUT_SHOTS, EXPECTED_HOLDOUT_MATCHES),
        }
        for scope_name, (shots, matches) in expected_scopes.items():
            scope = scopes.get(scope_name)
            if not isinstance(scope, dict):
                problems.append(f"scopes.{scope_name} missing")
                continue
            if scope.get("shots") != shots or scope.get("matches") != matches:
                problems.append(
                    f"scopes.{scope_name}=(shots={scope.get('shots')!r}, "
                    f"matches={scope.get('matches')!r}), expected (shots={shots!r}, "
                    f"matches={matches!r})"
                )
    return problems


def golden_tolerance(fixture: dict[str, Any]) -> float:
    """The prediction comparison tolerance is the fixture's own declaration, never a constant.

    The oracle and its tolerance travel together; hard-coding either half here would let the
    fixture be regenerated with a looser bound while the smoke kept passing.
    """
    return fixture["absolute_tolerance"]


def provenance_mismatches(fixture: dict[str, Any], metadata: dict[str, Any]) -> list[str]:
    """The golden oracle is only valid for the exact model and calibration decision it records."""
    problems: list[str] = []
    if metadata.get("artifact_sha256") != fixture.get("model_sha256"):
        problems.append(
            f"/model artifact_sha256={metadata.get('artifact_sha256')!r} does not match the "
            f"fixture model_sha256={fixture.get('model_sha256')!r}"
        )
    if metadata.get("calibration_decision_sha256") != fixture.get("calibration_decision_sha256"):
        problems.append(
            "/model calibration_decision_sha256="
            f"{metadata.get('calibration_decision_sha256')!r} does not match the fixture "
            f"calibration_decision_sha256={fixture.get('calibration_decision_sha256')!r}"
        )
    return problems


def predict_case_problems(case: dict[str, Any], body: Any, tolerance: float) -> list[str]:
    """Compare only the public prediction-contract outputs for one golden case.

    The fixture's internal oracle fields (base_logit, selected_vector, ...) are deliberately not
    part of the deployed surface. The key-set assertion is what keeps it that way: any extra
    field in the response is treated as an internal leak and fails, and the single public output
    is compared within the tolerance declared by the fixture itself.
    """
    name = case.get("name", "<unnamed>")
    problems: list[str] = []
    if not isinstance(body, dict):
        return [f"case {name}: response body is not a JSON object"]
    keys = set(body)
    missing = sorted(PUBLIC_PREDICT_KEYS - keys)
    unexpected = sorted(keys - PUBLIC_PREDICT_KEYS)
    if missing:
        problems.append(f"case {name}: public contract fields absent: {', '.join(missing)}")
    if unexpected:
        problems.append(
            f"case {name}: fields outside the public prediction contract: {', '.join(unexpected)}"
        )
    if body.get("release_id") != EXPECTED_RELEASE_ID:
        problems.append(f"case {name}: release_id={body.get('release_id')!r}")
    expected_probability = (case.get("expected") or {}).get("calibrated_probability")
    actual = body.get("calibrated_probability")
    if not isinstance(actual, (int, float)) or isinstance(actual, bool):
        problems.append(f"case {name}: calibrated_probability={actual!r} is not a number")
    elif not isinstance(expected_probability, (int, float)):
        problems.append(f"case {name}: fixture carries no numeric calibrated_probability")
    elif abs(float(actual) - float(expected_probability)) > tolerance:
        problems.append(
            f"case {name}: calibrated_probability={actual!r} differs from the golden oracle "
            f"{expected_probability!r} beyond the fixture tolerance {tolerance!r}"
        )
    return problems


def closed_model_shots_problems(status: int, body: Any) -> list[str]:
    """The publication gate is closed in production, and must answer exactly this way."""
    problems: list[str] = []
    if status != 403:
        problems.append(f"status={status}, expected 403")
    error = body.get("error") if isinstance(body, dict) else None
    error_code = error.get("code") if isinstance(error, dict) else None
    if error_code != "publication_gate_closed":
        problems.append(f"error.code={error_code!r}, expected 'publication_gate_closed'")
    if isinstance(body, dict) and "shots" in body:
        problems.append("a 'shots' collection was returned while the gate is closed")
    serialized = json.dumps(body) if isinstance(body, dict) else ""
    if "calibrated_probability" in serialized:
        problems.append("historical probabilities leaked into the closed-gate response body")
    return problems


def metrics_problems(body: Any, metadata: dict[str, Any]) -> list[str]:
    """Immutable evaluation evidence plus cross-endpoint provenance agreement."""
    problems: list[str] = []
    if not isinstance(body, dict):
        return ["response body is not a JSON object"]

    for field_name in ("model_version", "release_id"):
        if body.get(field_name) != EXPECTED_RELEASE_ID:
            problems.append(
                f"{field_name}={body.get(field_name)!r}, expected {EXPECTED_RELEASE_ID!r}"
            )
    for field_name in (
        "serving_manifest_sha256",
        "release_manifest_sha256",
        "release_manifest_file_sha256",
        "artifact_sha256",
        "calibration_decision_sha256",
    ):
        if body.get(field_name) != metadata.get(field_name):
            problems.append(f"{field_name} disagrees with /model provenance")

    evidence_source = body.get("evidence_source")
    if not isinstance(evidence_source, dict):
        problems.append("evidence_source block missing")
    else:
        if evidence_source.get("holdout_metrics_sha256") != EXPECTED_HOLDOUT_METRICS_SHA256:
            problems.append(
                f"evidence_source.holdout_metrics_sha256="
                f"{evidence_source.get('holdout_metrics_sha256')!r}, expected the qualified "
                "WP2.7 packet digest"
            )
        if evidence_source.get("evidence_status") != "qualified_m2_evidence":
            problems.append(
                f"evidence_source.evidence_status={evidence_source.get('evidence_status')!r}"
            )
        if evidence_source.get("recomputed_at_request_time") is not False:
            problems.append("evidence_source.recomputed_at_request_time is not false")

    adoption = body.get("calibration_adoption")
    if not isinstance(adoption, dict):
        problems.append("calibration_adoption block missing")
    else:
        if adoption.get("split") != "FIFA World Cup 2022":
            problems.append(f"calibration_adoption.split={adoption.get('split')!r}")
        if adoption.get("shots") != EXPECTED_CALIBRATION_SHOTS:
            problems.append(f"calibration_adoption.shots={adoption.get('shots')!r}")
        if adoption.get("matches") != EXPECTED_CALIBRATION_MATCHES:
            problems.append(f"calibration_adoption.matches={adoption.get('matches')!r}")
        if adoption.get("adopted_variant") != "calibrated":
            problems.append(
                f"calibration_adoption.adopted_variant={adoption.get('adopted_variant')!r}"
            )

    holdout = body.get("tournament_holdout")
    if not isinstance(holdout, dict):
        problems.append("tournament_holdout block missing")
    else:
        if holdout.get("split") != "UEFA Euro 2024":
            problems.append(f"tournament_holdout.split={holdout.get('split')!r}")
        if holdout.get("shots") != EXPECTED_HOLDOUT_SHOTS:
            problems.append(f"tournament_holdout.shots={holdout.get('shots')!r}")
        if holdout.get("matches") != EXPECTED_HOLDOUT_MATCHES:
            problems.append(f"tournament_holdout.matches={holdout.get('matches')!r}")
        if holdout.get("goals") != EXPECTED_HOLDOUT_GOALS:
            problems.append(f"tournament_holdout.goals={holdout.get('goals')!r}")
        if holdout.get("adopted_variant") != "calibrated":
            problems.append(
                f"tournament_holdout.adopted_variant={holdout.get('adopted_variant')!r}"
            )

        pinned_floats = {
            "observed_prevalence": (
                holdout.get("observed_prevalence"),
                EXPECTED_HOLDOUT_PREVALENCE,
            ),
            "proper_scoring.log_loss": (
                (holdout.get("proper_scoring") or {}).get("log_loss"),
                EXPECTED_HOLDOUT_LOG_LOSS,
            ),
            "proper_scoring.brier": (
                (holdout.get("proper_scoring") or {}).get("brier"),
                EXPECTED_HOLDOUT_BRIER,
            ),
            "discrimination.roc_auc": (
                (holdout.get("discrimination") or {}).get("roc_auc"),
                EXPECTED_HOLDOUT_ROC_AUC,
            ),
            "discrimination.pr_auc": (
                (holdout.get("discrimination") or {}).get("pr_auc"),
                EXPECTED_HOLDOUT_PR_AUC,
            ),
        }
        for field_name, (actual, expected) in pinned_floats.items():
            if not isinstance(actual, (int, float)) or isinstance(actual, bool):
                problems.append(f"tournament_holdout.{field_name}={actual!r} is not a number")
            elif abs(float(actual) - expected) > METRICS_FLOAT_TOLERANCE:
                problems.append(
                    f"tournament_holdout.{field_name}={actual!r} differs from the qualified "
                    f"packet value {expected!r}"
                )

        uncertainty = holdout.get("uncertainty")
        if not isinstance(uncertainty, dict):
            problems.append("tournament_holdout.uncertainty block missing")
        elif uncertainty.get("method") != "match_clustered_paired_bootstrap":
            problems.append(f"tournament_holdout.uncertainty.method={uncertainty.get('method')!r}")
    return problems


def request_id_echo_problems(sent: str, received: str | None) -> list[str]:
    """A canonical UUID sent inbound must come back unchanged."""
    if received is None:
        return ["no X-Request-ID header on the response"]
    if received != sent:
        return [f"sent {sent!r} but response carried {received!r}"]
    return []


def request_id_replacement_problems(sent: str, received: str | None) -> list[str]:
    """Malformed inbound IDs are replaced by a fresh canonical UUID, never echoed."""
    if received is None:
        return ["no X-Request-ID header on the response"]
    problems: list[str] = []
    if not _is_canonical_uuid(received):
        problems.append(f"replacement {received!r} is not a canonical UUID")
    if received == sent:
        problems.append("the malformed ID was echoed instead of replaced")
    return problems


REQUIRED_FRONTEND_TEXT = (
    "Shot quality, made inspectable.",
    EXPECTED_RELEASE_ID,
    f"{EXPECTED_DEVELOPMENT_SHOTS} shots",
    f"{EXPECTED_CALIBRATION_SHOTS} shots",
    f"{EXPECTED_HOLDOUT_SHOTS} shots",
    "Historical shot map is not publicly enabled",
    "publication_gate_closed",
    "What this view does not claim",
    "One-time tournament holdout",
    "Qualified evidence",
    "Data provided by",
)

FORBIDDEN_FRONTEND_TEXT = (
    "Model identities do not agree",
    "Model metadata unavailable",
    "Evaluation evidence unavailable",
    "could not be loaded",
)


def frontend_problems(html: str) -> list[str]:
    text = _visible_text(html)
    problems: list[str] = []
    for fragment in REQUIRED_FRONTEND_TEXT:
        if fragment not in text:
            problems.append(f"missing expected page text: {fragment!r}")
    for fragment in FORBIDDEN_FRONTEND_TEXT:
        if fragment in text:
            problems.append(f"error-state text present: {fragment!r}")
    return problems


def check_api(api: str, results: Results) -> None:
    print(f"\nAPI: {api}")

    response = _get(f"{api}/health")
    body = response.json()
    results.check(
        "/health returns ok",
        response.status == 200 and bool(body) and body.get("status") == "ok",
        f"status={response.status}",
    )

    response = _get(f"{api}/ready")
    body = response.json()
    problems = ready_problems(body)
    results.check(
        "/ready reports the full readiness state",
        response.status == 200 and not problems,
        "; ".join(problems) if problems else f"status={response.status}",
    )

    response = _get(f"{api}/baseline")
    body = response.json()
    if response.status != 200 or not body:
        results.check("/baseline returns the cohort rate", False, f"status={response.status}")
    else:
        results.check(
            "/baseline matches the pinned snapshot",
            body.get("shots") == EXPECTED_COHORT_SHOTS
            and body.get("goals") == EXPECTED_COHORT_GOALS,
            f"{body.get('goals')}/{body.get('shots')} "
            f"(expected {EXPECTED_COHORT_GOALS}/{EXPECTED_COHORT_SHOTS})",
        )
        results.check(
            "/baseline still says it is not a model",
            "not a model" in body.get("caveat", ""),
        )

    response = _get(f"{api}/shots?limit=1")
    body = response.json()
    if response.status != 200 or not body:
        results.check("/shots returns a page", False, f"status={response.status}")
    else:
        results.check(
            "/shots reports the full pinned snapshot",
            body.get("total") == EXPECTED_TOTAL_SHOTS,
            f"total={body.get('total')} (expected {EXPECTED_TOTAL_SHOTS})",
        )
        shot = (body.get("shots") or [{}])[0]
        results.check(
            "/shots returns recorded facts",
            all(shot.get(k) is not None for k in ("shot_id", "team", "outcome")),
        )
        results.check(
            "/shots carries no probability field",
            not any(k.lower() in {"xg", "statsbomb_xg", "probability", "prediction"} for k in shot),
        )


def check_model_surface(api: str, results: Results, fixture: dict[str, Any]) -> None:
    print("\nModel surface")

    metadata_response = _get(f"{api}/model")
    metadata = metadata_response.json()
    metadata_problems = (
        model_metadata_problems(metadata)
        if metadata_response.status == 200
        else [f"GET /model returned {metadata_response.status}"]
    )
    results.check(
        "/model serves the qualified release identity",
        not metadata_problems,
        "; ".join(metadata_problems),
    )
    if metadata_problems or not isinstance(metadata, dict):
        results.check("golden provenance matches the served model", False, "/model unusable")
        results.check("golden cases reproduce through /model/predict", False, "/model unusable")
        results.check("/model/metrics agrees with /model provenance", False, "/model unusable")
        results.check("/model/shots stays publication-closed", False, "/model unusable")
        return

    mismatches = provenance_mismatches(fixture, metadata)
    results.check(
        "golden provenance matches the served model", not mismatches, "; ".join(mismatches)
    )

    if mismatches:
        results.check(
            "golden cases reproduce through /model/predict",
            False,
            "provenance mismatch; refusing to score predictions against another model",
        )
    else:
        tolerance = golden_tolerance(fixture)
        failures: list[str] = []
        failed_cases: set[str] = set()
        for case in fixture["cases"]:
            response = _post_json(f"{api}/model/predict", case["request"])
            case_problems = (
                predict_case_problems(case, response.json(), tolerance)
                if response.status == 200
                else [f"HTTP {response.status}: {response.body[:120]}"]
            )
            if case_problems:
                failed_cases.add(str(case.get("name", "<unnamed>")))
                failures.extend(case_problems)
        total_cases = len(fixture["cases"])
        matched = total_cases - len(failed_cases)
        results.check(
            "golden cases reproduce through /model/predict",
            not failures,
            f"{matched}/{total_cases} cases within the fixture tolerance; "
            "public contract fields only"
            if failures
            else f"{total_cases}/{total_cases} cases within the fixture tolerance; "
            "public contract fields only",
        )

    metrics_response = _get(f"{api}/model/metrics")
    metrics = metrics_response.json()
    metrics_faults = (
        metrics_problems(metrics, metadata)
        if metrics_response.status == 200
        else [f"GET /model/metrics returned {metrics_response.status}"]
    )
    results.check(
        "/model/metrics agrees with /model provenance and the qualified packet",
        not metrics_faults,
        "; ".join(metrics_faults),
    )

    closed = _get(f"{api}/model/shots")
    closed_faults = closed_model_shots_problems(closed.status, closed.json())
    results.check(
        "/model/shots stays publication-closed", not closed_faults, "; ".join(closed_faults)
    )


def check_request_id(api: str, frontend: str, results: Results) -> None:
    print("\nRequest correlation")

    sent = str(uuid.uuid4())
    response = _get(f"{api}/health", {"X-Request-ID": sent})
    problems = (
        request_id_echo_problems(sent, response.headers.get("x-request-id"))
        if response.status == 200
        else [f"GET /health returned {response.status}"]
    )
    results.check(
        "a supplied X-Request-ID is propagated unchanged", not problems, "; ".join(problems)
    )

    malformed = "not-a-valid-request-id"
    response = _get(f"{api}/health", {"X-Request-ID": malformed})
    problems = (
        request_id_replacement_problems(malformed, response.headers.get("x-request-id"))
        if response.status == 200
        else [f"GET /health returned {response.status}"]
    )
    results.check("a malformed X-Request-ID is safely replaced", not problems, "; ".join(problems))

    response = _get(f"{api}/health")
    generated = response.headers.get("x-request-id")
    results.check(
        "an unsupplied request still receives a canonical X-Request-ID",
        response.status == 200 and generated is not None and _is_canonical_uuid(generated),
        f"x-request-id={generated!r}",
    )

    # CORSMiddleware emits Access-Control-Expose-Headers only on responses carrying an allowed
    # Origin, so the probe must look like the browser that is supposed to read the header.
    exposed = _get(f"{api}/ready", {"Origin": frontend}).headers.get(
        "access-control-expose-headers"
    )
    results.check(
        "X-Request-ID is an exposed CORS header",
        exposed is not None and "x-request-id" in exposed.lower(),
        f"access-control-expose-headers={exposed!r}",
    )


def check_cors(api: str, frontend: str, results: Results) -> None:
    """Verify the allow-list from the outside, with the origin the browser will actually send.

    This is the check that catches the most common deployment mistake: `TOUCHLINE_CORS_ORIGINS`
    left at its localhost default, or set to a preview URL rather than the production one.
    """
    print("\nCORS")

    allowed = _get(f"{api}/health", {"Origin": frontend})
    header = allowed.headers.get("access-control-allow-origin")
    results.check(
        "the deployed frontend origin is allowed",
        header == frontend,
        f"access-control-allow-origin={header!r}, expected {frontend!r}",
    )

    refused = _get(f"{api}/health", {"Origin": DISALLOWED_ORIGIN})
    refused_header = refused.headers.get("access-control-allow-origin")
    results.check(
        "an unknown origin is refused",
        refused_header is None,
        f"access-control-allow-origin={refused_header!r}, expected absent",
    )
    results.check(
        "the allow-list is not a wildcard",
        refused_header != "*",
        "a wildcard lets any page on the internet read this API from a visitor's browser",
    )


def check_frontend(frontend: str, results: Results) -> None:
    print(f"\nFrontend: {frontend}")

    response = _get(frontend)
    results.check("page responds", response.status == 200, f"status={response.status}")
    if response.status != 200:
        return

    problems = frontend_problems(response.body)
    results.check(
        "analyst view renders the qualified release without error states",
        not problems,
        "; ".join(problems),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", required=True, help="deployed API base URL, no trailing slash")
    parser.add_argument("--frontend", required=True, help="deployed frontend URL")
    args = parser.parse_args()

    api = args.api.rstrip("/")
    frontend = args.frontend.rstrip("/")

    results = Results()
    check_api(api, results)

    fixture, fixture_error = load_golden_fixture()
    results.check(
        "golden fixture is readable and declares a tolerance",
        fixture is not None,
        fixture_error or "",
    )
    if fixture is not None:
        check_model_surface(api, results, fixture)
    else:
        for name in (
            "golden provenance matches the served model",
            "golden cases reproduce through /model/predict",
        ):
            results.check(name, False, "golden fixture unavailable")

    check_request_id(api, frontend, results)
    check_cors(api, frontend, results)
    check_frontend(frontend, results)

    total = len(results.passed) + len(results.failed)
    print(f"\n{len(results.passed)}/{total} checks passed")
    if results.failed:
        print("\nFailed:")
        for name in results.failed:
            print(f"  - {name}")
        return 1
    print("Deployment smoke test passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
