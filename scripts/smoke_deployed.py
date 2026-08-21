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

# The immutable public metrics packet below is kept as readable JSON; several rows exceed the
# Python line-length limit so the evidence remains directly comparable with the served payload.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

# What the pinned WC 2022 snapshot must produce.
EXPECTED_TOTAL_SHOTS = 1494
EXPECTED_COHORT_SHOTS = 1430
EXPECTED_COHORT_GOALS = 152
EXPECTED_API_ENVIRONMENT = "production"
EXPECTED_API_VERSION = "0.1.0"
EXPECTED_BASELINE_KEYS = frozenset(
    {"method", "conversion_rate", "shots", "goals", "cohort", "caveat"}
)
EXPECTED_BASELINE_COHORT = (
    "Shots in the public FIFA World Cup 2022 (competition 43, season 106) scope with a known shot "
    "type, period and outcome, excluding penalties and penalty-shootout kicks. Shots missing any "
    "of those three fields are excluded from both the numerator and the denominator rather than "
    "being counted as misses. No filtering by team, player or location."
)
EXPECTED_BASELINE_CAVEAT = (
    "This is a descriptive summary of the shots currently loaded, not a model and not a "
    "prediction. Nothing has been fitted, no split was used, and no performance claim is made. "
    "It is also NOT the baseline that models are compared against: that baseline is estimated "
    "from the training split alone and scored on validation and holdout rows under the same log "
    "loss, Brier score and calibration protocol as every candidate model. Using this full-cohort "
    "rate as a prediction on holdout rows would leak those rows' own outcomes into it."
)
SHOT_PAGE_KEYS = frozenset({"shots", "total", "limit", "offset"})
SHOT_KEYS = frozenset(
    {
        "shot_id",
        "match_id",
        "match_date",
        "competition_stage",
        "team",
        "opponent",
        "player",
        "period",
        "minute",
        "second",
        "location_x",
        "location_y",
        "outcome",
        "shot_type",
        "body_part",
        "technique",
    }
)

# The one qualified serving release (WP2.8). Every model-aware endpoint must identify it.
EXPECTED_RELEASE_ID = "exp-20260810-wp2_8-release"
EXPECTED_PROVENANCE = {
    "model_version": EXPECTED_RELEASE_ID,
    "release_id": EXPECTED_RELEASE_ID,
    "serving_manifest_sha256": "68cee3ab4f06c280421f848de36d59b3db39d8c3ea7ece7765a4ba29e3a7ae5c",
    "release_manifest_sha256": "bad64e5972938335e62b98d694f24961117e5f46034518f38b61209e2c3ca87d",
    "release_manifest_file_sha256": "5c2e4016291c6ebe99ba69b37884f38791b4b6b1440c81107ed2a44db95645d4",
    "artifact_sha256": "9aeac9468c00bd1b93c771e454e48ca29e2eb759cf71836182a782d674bfadca",
    "calibration_decision_sha256": "f5c9ccf665924069f755fbd669d4a9abada1e5791e957d3d436d42d500277e89",
}

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

EXPECTED_MODEL_METADATA = {
    **EXPECTED_PROVENANCE,
    "release_status": "m2_qualified",
    "qualification_serving_status": "not_served",
    "runtime_status": "ready",
    "candidate": "full_minus_presence",
    "estimator": "logistic_regression",
    "calibration": "platt_sigmoid",
    "adopted_variant": "calibrated",
    "output": "goal_conversion_probability",
    "scopes": {
        "development": {
            "competitions": ["FIFA World Cup 2018", "UEFA Euro 2020"],
            "shots": 2872,
            "matches": 115,
            "role": "model_development",
        },
        "calibration": {
            "competition": "FIFA World Cup 2022",
            "shots": 1430,
            "matches": 64,
            "role": "platt_calibration_and_adoption",
        },
        "tournament_holdout": {
            "competition": "UEFA Euro 2024",
            "shots": 1304,
            "matches": 51,
            "role": "one_time_final_evaluation",
        },
    },
    "input_contract": {
        "coordinates": {
            "system": "StatsBomb",
            "location_x": {"minimum": 0.0, "maximum": 120.0},
            "location_y": {"minimum": 0.0, "maximum": 80.0},
        },
        "categorical_policy": "exact_frozen_vocabulary_with_unseen_as_reference",
        "fields": {
            "body_part": {
                "reference": "Right Foot",
                "retained": ["Head", "Left Foot"],
                "rare_members": ["Other"],
            },
            "technique": {
                "reference": "Normal",
                "retained": ["Half Volley", "Volley"],
                "rare_members": ["Backheel", "Diving Header", "Lob", "Overhead Kick"],
            },
            "play_pattern": {
                "reference": "Regular Play",
                "retained": [
                    "From Corner",
                    "From Counter",
                    "From Free Kick",
                    "From Goal Kick",
                    "From Keeper",
                    "From Kick Off",
                    "From Throw In",
                ],
                "rare_members": ["Other"],
            },
        },
    },
}

EXPECTED_METRICS_CONTENT = json.loads(
    r"""
{
  "evidence_source": {"evidence_status": "qualified_m2_evidence", "holdout_metrics_sha256": "3443b4a5e19fd87b1ee599502152a7dcfe1af3d8466c09ad7cbf2bb8cae2e674", "recomputed_at_request_time": false},
  "calibration_adoption": {
    "adopted_variant": "calibrated",
    "calibrated": {"brier": 0.08204252640613116, "log_loss": 0.2839359330006713, "max_supported_calibration_deviation": 0.004302015683183724},
    "matches": 64,
    "raw": {"brier": 0.08321574985457875, "log_loss": 0.2874904814912322, "max_supported_calibration_deviation": 0.012247769393666633},
    "raw_anchor_reliability": [
      {"bin": 0, "calibrated_mean_prediction": 0.07953484232285857, "count": 1324, "lower": 0.0, "observed_rate": 0.08383685800604229, "positive_count": 111, "raw_mean_prediction": 0.07158908861237566, "upper": 0.2},
      {"bin": 1, "calibrated_mean_prediction": 0.370930124495372, "count": 84, "lower": 0.2, "observed_rate": 0.32142857142857145, "positive_count": 27, "raw_mean_prediction": 0.2707363079266444, "upper": 0.4},
      {"bin": 2, "calibrated_mean_prediction": 0.6688679303179884, "count": 18, "lower": 0.4, "observed_rate": 0.6666666666666666, "positive_count": 12, "raw_mean_prediction": 0.4986862919388754, "upper": 0.6},
      {"bin": 3, "calibrated_mean_prediction": 0.8480942340530411, "count": 3, "lower": 0.6, "observed_rate": 0.3333333333333333, "positive_count": 1, "raw_mean_prediction": 0.6886531740738474, "upper": 0.8},
      {"bin": 4, "calibrated_mean_prediction": 0.9538328590062717, "count": 1, "lower": 0.8, "observed_rate": 1.0, "positive_count": 1, "raw_mean_prediction": 0.862365274994754, "upper": 1.0}
    ],
    "role": "calibration", "shots": 1430, "split": "FIFA World Cup 2022", "supported_raw_anchor_bins": 1
  },
  "tournament_holdout": {
    "adopted_variant": "calibrated",
    "discrimination": {"pr_auc": 0.223985679737, "roc_auc": 0.744677970691},
    "goals": 98, "matches": 51, "observed_prevalence": 0.075153374233,
    "proper_scoring": {"brier": 0.066029980705, "log_loss": 0.243112806225},
    "raw_comparator": {
      "calibrated_minus_raw": {"brier": 0.00132258148, "brier_interval": {"lower": -1.3107008e-05, "upper": 0.002806020149}, "log_loss": 0.003805297954, "log_loss_interval": {"lower": 9.5442006e-05, "upper": 0.007815706219}},
      "discrimination": {"pr_auc": 0.223985679737, "roc_auc": 0.744677970691},
      "proper_scoring": {"brier": 0.064707399225, "log_loss": 0.239307508271}
    },
    "reliability": [
      {"bin": 0, "count": 1151, "lower": 0.0, "mean_prediction": 0.069758641267, "observed_rate": 0.054735013032, "positive_count": 63, "upper": 0.2},
      {"bin": 1, "count": 123, "lower": 0.2, "mean_prediction": 0.268785359657, "observed_rate": 0.19512195122, "positive_count": 24, "upper": 0.4},
      {"bin": 2, "count": 25, "lower": 0.4, "mean_prediction": 0.493646033883, "observed_rate": 0.32, "positive_count": 8, "upper": 0.6},
      {"bin": 3, "count": 4, "lower": 0.6, "mean_prediction": 0.723563254555, "observed_rate": 0.75, "positive_count": 3, "upper": 0.8},
      {"bin": 4, "count": 1, "lower": 0.8, "mean_prediction": 0.904238036674, "observed_rate": 0.0, "positive_count": 0, "upper": 1.0}
    ],
    "role": "one_time_tournament_holdout", "shots": 1304, "split": "UEFA Euro 2024",
    "uncertainty": {"brier": {"lower": 0.055641037736, "upper": 0.075907318637}, "confidence_level": 0.95, "log_loss": {"lower": 0.210598611086, "upper": 0.273303673707}, "method": "match_clustered_paired_bootstrap", "repetitions": 2000, "seed": 0}
  }
}
"""
)

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


def _request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
) -> Response:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"User-Agent": "touchline-smoke/1.0", **(headers or {})},
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
    return _request(
        url,
        method="POST",
        payload=payload,
        headers={
            "Content-Type": "application/json",
        },
    )


def _get(url: str, headers: dict[str, str] | None = None) -> Response:
    return _request(url, headers=headers)


class _VisibleTextParser(HTMLParser):
    _NON_VISIBLE = frozenset({"head", "script", "style", "template", "noscript"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._hidden: list[bool] = []
        self.fragments: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name.lower(): (value or "") for name, value in attrs}
        style = re.sub(r"\s+", "", values.get("style", "").lower())
        hidden = (
            (self._hidden[-1] if self._hidden else False)
            or tag.lower() in self._NON_VISIBLE
            or "hidden" in values
            or values.get("aria-hidden", "").lower() == "true"
            or "display:none" in style
            or "visibility:hidden" in style
        )
        self._hidden.append(hidden)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self._hidden.pop()

    def handle_endtag(self, tag: str) -> None:
        del tag
        if self._hidden:
            self._hidden.pop()

    def handle_data(self, data: str) -> None:
        if not (self._hidden and self._hidden[-1]):
            self.fragments.append(data)


def _visible_text(html: str) -> str:
    """Extract rendered text, excluding metadata, executable content, and hidden subtrees."""
    parser = _VisibleTextParser()
    parser.feed(html)
    parser.close()
    return " ".join(" ".join(parser.fragments).split())


def _is_canonical_uuid(value: str) -> bool:
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        return False
    return str(parsed) == value


def _is_sha256_hex(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _is_finite_real(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _is_strict_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _operational_leaks(value: Any, path: str = "$") -> list[str]:
    """Find configuration/credential-shaped diagnostics in public operational payloads."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            words = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(key))
            tokens = re.findall(r"[a-z0-9]+", words.lower())
            normalized = "".join(tokens)
            if any(
                marker in normalized
                for marker in (
                    "password",
                    "secret",
                    "token",
                    "credential",
                    "dsn",
                    "databaseurl",
                    "migrationurl",
                    "connectionstring",
                    "databaseuri",
                    "connectionuri",
                    "postgreshost",
                )
            ) or any(token in {"url", "uri"} for token in tokens):
                found.append(f"{path}.{key}")
            found.extend(_operational_leaks(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_operational_leaks(child, f"{path}[{index}]"))
    elif isinstance(value, str):
        lowered = value.lower()
        libpq_parts = re.findall(
            r"(?:^|\s)(?:host|hostaddr|port|dbname|user|password|sslmode)\s*=\s*\S+", lowered
        )
        contains_libpq_password = re.search(r"(?:^|\s)password\s*=\s*\S+", lowered) is not None
        if (
            "://" in value
            or "traceback" in lowered
            or "postgresql" in lowered
            or contains_libpq_password
            or len(libpq_parts) >= 2
        ):
            found.append(path)
    return found


def health_problems(body: Any) -> list[str]:
    expected = {
        "status": "ok",
        "environment": EXPECTED_API_ENVIRONMENT,
        "version": EXPECTED_API_VERSION,
    }
    problems = (
        [] if body == expected else [f"body={body!r}, expected exact health envelope {expected!r}"]
    )
    leaked = _operational_leaks(body)
    if leaked:
        problems.append(f"operational configuration leaked at: {', '.join(leaked)}")
    return problems


def baseline_problems(body: Any) -> list[str]:
    if not isinstance(body, dict):
        return ["response body is not a JSON object"]
    problems: list[str] = []
    if set(body) != EXPECTED_BASELINE_KEYS:
        problems.append("baseline key set differs from the public contract")
    expected_values = {
        "method": "descriptive-prevalence",
        "shots": EXPECTED_COHORT_SHOTS,
        "goals": EXPECTED_COHORT_GOALS,
        "cohort": EXPECTED_BASELINE_COHORT,
        "caveat": EXPECTED_BASELINE_CAVEAT,
    }
    for field_name, expected in expected_values.items():
        actual = body.get(field_name)
        if field_name in {"shots", "goals"} and not _is_strict_int(actual):
            problems.append(f"{field_name}={actual!r} is not an integer count")
        elif actual != expected:
            problems.append(f"{field_name}={actual!r}, expected {expected!r}")
    rate = body.get("conversion_rate")
    expected_rate = EXPECTED_COHORT_GOALS / EXPECTED_COHORT_SHOTS
    if not _is_finite_real(rate) or not 0 <= float(rate) <= 1:
        problems.append(f"conversion_rate={rate!r} is not a finite probability")
    elif float(rate) != expected_rate:
        problems.append(f"conversion_rate={rate!r}, expected exact quotient {expected_rate!r}")
    return problems


def _nullable(value: Any, predicate: Any) -> bool:
    return value is None or bool(predicate(value))


def shot_page_problems(body: Any) -> list[str]:
    if not isinstance(body, dict):
        return ["response body is not a JSON object"]
    problems: list[str] = []
    if set(body) != SHOT_PAGE_KEYS:
        problems.append("shot-page key set differs from the public contract")
    for field_name, expected in (("total", EXPECTED_TOTAL_SHOTS), ("limit", 1), ("offset", 0)):
        actual = body.get(field_name)
        if not _is_strict_int(actual) or actual != expected:
            problems.append(f"{field_name}={actual!r}, expected integer {expected}")
    rows = body.get("shots")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        return [*problems, "shots must contain exactly one object"]
    shot = rows[0]
    if set(shot) != SHOT_KEYS:
        problems.append("shot key set differs from the public Shot contract")
    required_strings = ("shot_id", "team", "opponent")
    for field_name in required_strings:
        if not isinstance(shot.get(field_name), str):
            problems.append(f"shot.{field_name} is not a string")
    if not _is_strict_int(shot.get("match_id")):
        problems.append("shot.match_id is not an integer")
    for field_name in (
        "competition_stage",
        "player",
        "outcome",
        "shot_type",
        "body_part",
        "technique",
    ):
        if not _nullable(shot.get(field_name), lambda value: isinstance(value, str)):
            problems.append(f"shot.{field_name} is neither string nor null")
    for field_name in ("period", "minute", "second"):
        if not _nullable(shot.get(field_name), _is_strict_int):
            problems.append(f"shot.{field_name} is neither integer nor null")
    for field_name in ("location_x", "location_y"):
        if not _nullable(shot.get(field_name), _is_finite_real):
            problems.append(f"shot.{field_name} is neither finite number nor null")
    match_date = shot.get("match_date")
    if match_date is not None:
        try:
            parsed_date = date.fromisoformat(match_date) if isinstance(match_date, str) else None
        except ValueError:
            parsed_date = None
        if parsed_date is None or parsed_date.isoformat() != match_date:
            problems.append("shot.match_date is neither canonical ISO date nor null")
    leaked = _probability_like_fields(rows)
    if leaked:
        problems.append(f"probability or model-score fields leaked: {', '.join(leaked)}")
    return problems


def _exact_contract_problems(
    actual: Any,
    expected: Any,
    *,
    path: str = "$",
    float_tolerance: float = 0.0,
) -> list[str]:
    """Compare a public JSON contract recursively with strict numeric semantics."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path}={actual!r} is not an object"]
        problems: list[str] = []
        missing = sorted(set(expected) - set(actual))
        unexpected = sorted(set(actual) - set(expected))
        if missing:
            problems.append(f"{path} is missing fields: {', '.join(missing)}")
        if unexpected:
            problems.append(f"{path} has unexpected fields: {', '.join(unexpected)}")
        for key in expected.keys() & actual.keys():
            problems.extend(
                _exact_contract_problems(
                    actual[key],
                    expected[key],
                    path=f"{path}.{key}",
                    float_tolerance=float_tolerance,
                )
            )
        return problems
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return [f"{path}={actual!r} is not a list"]
        problems = []
        if len(actual) != len(expected):
            problems.append(f"{path} has {len(actual)} rows, expected {len(expected)}")
        for index, (actual_item, expected_item) in enumerate(zip(actual, expected, strict=False)):
            problems.extend(
                _exact_contract_problems(
                    actual_item,
                    expected_item,
                    path=f"{path}[{index}]",
                    float_tolerance=float_tolerance,
                )
            )
        return problems
    if isinstance(expected, bool):
        return [] if actual is expected else [f"{path}={actual!r}, expected {expected!r}"]
    if isinstance(expected, int):
        if not _is_strict_int(actual) or actual != expected:
            return [f"{path}={actual!r}, expected integer {expected!r}"]
        return []
    if isinstance(expected, float):
        if not _is_finite_real(actual):
            return [f"{path}={actual!r} is not a finite real number"]
        if abs(float(actual) - expected) > float_tolerance:
            return [f"{path}={actual!r}, expected {expected!r}"]
        return []
    return [] if actual == expected else [f"{path}={actual!r}, expected {expected!r}"]


def _probability_like_fields(value: Any, path: str = "$") -> list[str]:
    """Find conservative model-score field names recursively without inspecting fact values."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            words = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(key))
            tokens = re.findall(r"[a-z0-9]+", words.lower())
            normalized = "".join(tokens)
            markers = (
                "xg",
                "expectedgoal",
                "goalprobabil",
                "goalchance",
                "modelscore",
                "modelrating",
                "modelestimate",
                "modeloutput",
                "shotquality",
                "probabil",
                "predict",
                "likelihood",
                "estimate",
                "confidence",
                "rating",
                "score",
                "chancequality",
            )
            if (
                "xg" in tokens
                or "prob" in tokens
                or any(marker in normalized for marker in markers)
            ):
                found.append(f"{path}.{key}")
            found.extend(_probability_like_fields(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_probability_like_fields(child, f"{path}[{index}]"))
    return found


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
    if not _is_finite_real(tolerance) or float(tolerance) <= 0:
        return None, f"{path} does not declare a usable absolute_tolerance"
    for index, case in enumerate(fixture["cases"]):
        if not isinstance(case, dict):
            return None, f"{path} case {index} is not an object"
        expected_probability = (case.get("expected") or {}).get("calibrated_probability")
        if not _is_finite_real(expected_probability) or not 0 <= float(expected_probability) <= 1:
            return None, f"{path} case {index} has no finite bounded calibrated_probability"
    return fixture, None


def ready_problems(body: Any) -> list[str]:
    """The full WP3.3 admission contract: three independent subsystems plus the release label."""
    problems: list[str] = []
    if not isinstance(body, dict):
        return ["response body is not a JSON object"]
    expected_keys = {
        "status",
        "database",
        "database_schema",
        "model_runtime",
        "model_version",
        "detail",
    }
    if set(body) != expected_keys:
        problems.append("readiness key set differs from the public contract")
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
    if body.get("detail") is not None:
        problems.append("detail must be null while ready; operational detail must not leak")
    leaked = _operational_leaks(body)
    if leaked:
        problems.append(f"operational configuration leaked at: {', '.join(leaked)}")
    return problems


def model_metadata_problems(body: Any) -> list[str]:
    """The qualified release identity: names, statuses, and scope membership counts."""
    if not isinstance(body, dict):
        return ["response body is not a JSON object"]
    return _exact_contract_problems(body, EXPECTED_MODEL_METADATA)


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


def predict_case_problems(
    case: dict[str, Any], body: Any, tolerance: float, metadata: dict[str, Any]
) -> list[str]:
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
    for identity in ("model_version", "release_id"):
        if body.get(identity) != EXPECTED_RELEASE_ID:
            problems.append(f"case {name}: {identity}={body.get(identity)!r}")
    for field_name in (
        "serving_manifest_sha256",
        "release_manifest_sha256",
        "release_manifest_file_sha256",
        "artifact_sha256",
        "calibration_decision_sha256",
    ):
        if body.get(field_name) != metadata.get(field_name):
            problems.append(f"case {name}: {field_name} disagrees with /model provenance")
    expected_probability = (case.get("expected") or {}).get("calibrated_probability")
    actual = body.get("calibrated_probability")
    if not _is_finite_real(tolerance) or float(tolerance) <= 0:
        problems.append(f"case {name}: tolerance={tolerance!r} is not finite and positive")
    if not _is_finite_real(actual) or not 0 <= float(actual) <= 1:
        problems.append(
            f"case {name}: calibrated_probability={actual!r} is not a finite probability"
        )
    elif not _is_finite_real(expected_probability) or not 0 <= float(expected_probability) <= 1:
        problems.append(f"case {name}: fixture carries no finite bounded calibrated_probability")
    elif (
        _is_finite_real(tolerance)
        and float(tolerance) > 0
        and abs(float(actual) - float(expected_probability)) > float(tolerance)
    ):
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
    expected = {
        "error": {
            "code": "publication_gate_closed",
            "message": "public historical model shots are not enabled",
            "details": [],
        }
    }
    if body != expected:
        problems.append(f"body does not exactly match the closed-gate error envelope: {body!r}")
    leaked = _probability_like_fields(body)
    if leaked:
        locations = ", ".join(leaked)
        problems.append(
            f"probability or prediction fields leaked into the closed-gate response: {locations}"
        )
    return problems


def metrics_problems(body: Any, metadata: dict[str, Any]) -> list[str]:
    """Immutable evaluation evidence plus cross-endpoint provenance agreement."""
    if not isinstance(body, dict):
        return ["response body is not a JSON object"]
    expected_body = {**EXPECTED_PROVENANCE, **EXPECTED_METRICS_CONTENT}
    problems = _exact_contract_problems(
        body, expected_body, float_tolerance=METRICS_FLOAT_TOLERANCE
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
    "Data provided by StatsBomb",
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
    problems = health_problems(body)
    results.check(
        "/health returns its exact liveness envelope",
        response.status == 200 and not problems,
        "; ".join(problems) or f"status={response.status}",
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
    problems = baseline_problems(body)
    if response.status != 200 or problems:
        results.check("/baseline returns the cohort rate", False, f"status={response.status}")
    else:
        results.check("/baseline exactly matches the pinned descriptive contract", True)

    response = _get(f"{api}/shots?limit=1")
    body = response.json()
    problems = shot_page_problems(body)
    results.check(
        "/shots exactly matches the bounded recorded-facts contract",
        response.status == 200 and not problems,
        "; ".join(problems) or f"status={response.status}",
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
                predict_case_problems(case, response.json(), tolerance, metadata)
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
        _header_tokens(exposed) == {"x-request-id"},
        f"access-control-expose-headers={exposed!r}",
    )

    for path, expected_status in (("/model/shots", 403), ("/__wp34_missing", 404)):
        sent = str(uuid.uuid4())
        response = _get(f"{api}{path}", {"X-Request-ID": sent, "Origin": frontend})
        problems = simple_cors_problems(response, frontend, sent, expected_status=expected_status)
        results.check(
            f"{path} error response preserves browser-readable X-Request-ID",
            not problems,
            "; ".join(problems),
        )


def _header_tokens(value: str | None) -> set[str]:
    return {item.strip().lower() for item in (value or "").split(",") if item.strip()}


def simple_cors_problems(
    response: Response,
    origin: str,
    request_id: str,
    *,
    allowed: bool = True,
    expected_status: int = 200,
) -> list[str]:
    """Pin the exact CORS headers relevant to browser access on a simple response."""
    problems: list[str] = []
    if response.status != expected_status:
        problems.append(f"status={response.status}, expected {expected_status}")
    allow_origin = response.headers.get("access-control-allow-origin")
    if allowed and allow_origin != origin:
        problems.append("allowed origin not echoed exactly")
    if not allowed and allow_origin is not None:
        problems.append("disallowed origin received an allow-origin grant")
    if allow_origin == "*":
        problems.append("wildcard origin weakens the allow-list")
    exposed = _header_tokens(response.headers.get("access-control-expose-headers"))
    if allowed and exposed != {"x-request-id"}:
        problems.append("exposed-header token set differs from the simple-response contract")
    if not allowed and exposed != {"x-request-id"}:
        problems.append("exposed-header token set differs from the simple-response contract")
    expected_vary = {"origin"} if allowed else set()
    if _header_tokens(response.headers.get("vary")) != expected_vary:
        problems.append("Vary token set differs from the simple-response contract")
    if "access-control-allow-credentials" in response.headers:
        problems.append("credentials were enabled despite the no-credentials contract")
    problems.extend(request_id_echo_problems(request_id, response.headers.get("x-request-id")))
    return problems


def preflight_problems(
    response: Response, origin: str, request_id: str, *, allowed: bool = True
) -> list[str]:
    problems: list[str] = []
    expected_status = 200 if allowed else 400
    if response.status != expected_status:
        problems.append(f"status={response.status}, expected {expected_status}")
    allow_origin = response.headers.get("access-control-allow-origin")
    if allowed is True and allow_origin != origin:
        problems.append("allowed origin not echoed exactly")
    if not allowed and allow_origin is not None:
        problems.append("disallowed origin received an allow-origin grant")
    if allow_origin == "*":
        problems.append("wildcard origin weakens the allow-list")
    if _header_tokens(response.headers.get("access-control-allow-methods")) != {
        "get",
        "post",
        "options",
    }:
        problems.append("allowed-method token set differs from GET, POST, OPTIONS")
    if _header_tokens(response.headers.get("access-control-allow-headers")) != {
        "content-type",
        "x-request-id",
    }:
        problems.append("allowed-header token set differs from Content-Type, X-Request-ID")
    if _header_tokens(response.headers.get("vary")) != {"origin"}:
        problems.append("Vary token set differs from Origin")
    if "access-control-allow-credentials" in response.headers:
        problems.append("credentials were enabled despite the no-credentials contract")
    if response.headers.get("access-control-max-age") != "600":
        problems.append("preflight max-age differs from the middleware contract")
    expected_body = "OK" if allowed else "Disallowed CORS origin"
    if response.body != expected_body:
        problems.append(f"preflight body={response.body!r}, expected {expected_body!r}")
    problems.extend(request_id_echo_problems(request_id, response.headers.get("x-request-id")))
    return problems


def check_cors(api: str, frontend: str, results: Results) -> None:
    """Verify the allow-list from the outside, with the origin the browser will actually send.

    This is the check that catches the most common deployment mistake: `TOUCHLINE_CORS_ORIGINS`
    left at its localhost default, or set to a preview URL rather than the production one.
    """
    print("\nCORS")

    allowed_request_id = str(uuid.uuid4())
    allowed = _get(f"{api}/health", {"Origin": frontend, "X-Request-ID": allowed_request_id})
    allowed_problems = simple_cors_problems(allowed, frontend, allowed_request_id)
    results.check(
        "the deployed frontend origin is allowed",
        not allowed_problems,
        "; ".join(allowed_problems),
    )

    refused_request_id = str(uuid.uuid4())
    refused = _get(
        f"{api}/health", {"Origin": DISALLOWED_ORIGIN, "X-Request-ID": refused_request_id}
    )
    refused_problems = simple_cors_problems(
        refused, DISALLOWED_ORIGIN, refused_request_id, allowed=False
    )
    results.check(
        "an unknown origin is refused",
        not refused_problems,
        "; ".join(refused_problems),
    )
    request_id = str(uuid.uuid4())
    preflight_headers = {
        "Origin": frontend,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "Content-Type, X-Request-ID",
        "X-Request-ID": request_id,
    }
    preflight = _request(f"{api}/model/predict", method="OPTIONS", headers=preflight_headers)
    problems = preflight_problems(preflight, frontend, request_id)
    results.check(
        "allowed POST prediction preflight preserves the WP3.3 CORS contract",
        not problems,
        "; ".join(problems),
    )
    refused_preflight = _request(
        f"{api}/model/predict",
        method="OPTIONS",
        headers={**preflight_headers, "Origin": DISALLOWED_ORIGIN},
    )
    refused_problems = preflight_problems(
        refused_preflight, DISALLOWED_ORIGIN, request_id, allowed=False
    )
    results.check(
        "disallowed prediction preflight preserves the rejection contract",
        not refused_problems,
        "; ".join(refused_problems),
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
