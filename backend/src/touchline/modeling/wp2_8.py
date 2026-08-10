"""WP2.8 reproducible, calibrated-model release contract.

The release runner is deliberately a publication boundary, not another modelling phase.  It
verifies the immutable WP2.4 and WP2.7 machine evidence, runs the old WP2.4 command in an isolated
historical checkout when invoked for real, and publishes one content-hashed packet atomically.

The database reproduction is not called by the test suite.  Tests exercise the pure guards and the
publication transaction with controlled fixtures; :func:`run_historical_reproduction` is the
separate acceptance/evidence operation.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from numbers import Real
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, cast

from touchline.modeling.calibration import (
    BaseModelPins,
    exact_json_bytes,
    exact_payload_sha256,
    freeze_base_model,
    load_calibration_decision,
    verify_calibration_decision,
)
from touchline.modeling.experiment import ROOT, git, require_clean_tracked_tree, sha256_bytes

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_OUTPUT_DIR",
    "REQUIRED_WP27_BASE_COMMIT",
    "ComparisonResult",
    "DevelopmentOnlyError",
    "EnvironmentFingerprintError",
    "PathContractError",
    "ReleaseConfig",
    "ReleaseContractError",
    "ReleasePublicationError",
    "ReproductionMismatchError",
    "ReproductionResult",
    "WP24Evidence",
    "WP27Evidence",
    "assert_development_anchors",
    "assert_development_only_match_ids",
    "assert_development_only_rows",
    "build_historical_reproduction_environment",
    "collect_environment_fingerprint",
    "compare_reproduction",
    "load_release_config",
    "parse_historical_environment_fingerprint",
    "publish_release_packet",
    "run_historical_reproduction",
    "run_release",
    "validate_repo_relative_path",
    "verify_environment_fingerprint",
    "verify_release_manifest",
    "verify_wp24_evidence",
    "verify_wp27_base",
    "verify_wp27_measured_chain",
]

REQUIRED_WP27_BASE_COMMIT = "f48a1032f88afab968562c3ba3600618a2ed580a"
DEFAULT_CONFIG_PATH = ROOT / "experiments/run-configs/wp2_8-release.json"
DEFAULT_OUTPUT_DIR = ROOT / "experiments/shot_quality/exp-20260810-wp2_8-release"

# Filled from the registered config after it is added.  Keeping this pin in code makes the CLI
# reject a locally edited config even when the JSON happens to retain the same semantic values.
REGISTERED_CONFIG_SHA256 = "09df31924f4b95fdb5ad4072c842e8c633ffc38aefc80e68a3f79f5f7368dd7c"

_DIGEST_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_ABSOLUTE_TOKEN_RE = re.compile(r"(?:^|[\s\"'=])(?:[A-Za-z]:[\\/]|\\\\|/[A-Za-z0-9_.~-]|~[\\/])")
_TRAVERSAL_TOKEN_RE = re.compile(r"(?:^|[\\/])\.\.(?:$|[\\/])")
_PRESENTATION_SUFFIXES = frozenset({".md", ".svg", ".png", ".html", ".txt"})
_HISTORICAL_OVERRIDE_ENV_VARS = (
    "TOUCHLINE_TRAIN_SCHEMA",
    "TOUCHLINE_ASSIGNMENTS_CSV",
    "TOUCHLINE_COHORT_SQL",
    "TOUCHLINE_CODE_COMMIT",
)


class ReleaseContractError(ValueError):
    """A registered release input or output violates the WP2.8 contract."""


class PathContractError(ReleaseContractError):
    """A persisted path is not canonical repository-relative POSIX syntax."""


class EnvironmentFingerprintError(ReleaseContractError):
    """The exact-reproduction environment registration is malformed or does not match."""


class DevelopmentOnlyError(ReleaseContractError):
    """A reproduction input is outside the registered development population."""


class ReproductionMismatchError(ReleaseContractError):
    """The historical reproduction does not meet the registered comparison contract."""


class ReleasePublicationError(ReleaseContractError):
    """The release packet could not be published atomically."""


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise ReleaseContractError(f"{label} must be a hexadecimal SHA-256 digest")
    return value.lower()


def validate_repo_relative_path(value: object, label: str = "path") -> str:
    """Validate one persisted path and return its canonical POSIX spelling.

    ``pathlib.Path`` follows the host platform, which is precisely what a portable release record
    must not do.  Both POSIX and Windows grammars are checked explicitly so a Windows checkout
    rejects Linux absolute paths and a Linux checkout rejects drive/UNC paths.
    """
    if not isinstance(value, str) or not value:
        raise PathContractError(f"{label} must be a non-empty repository-relative path")
    if value.startswith("~"):
        raise PathContractError(f"{label} must not use a home-directory path: {value!r}")
    if "\\" in value:
        raise PathContractError(f"{label} must use POSIX separators: {value!r}")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if posix.is_absolute() or windows.is_absolute() or windows.drive or windows.root:
        raise PathContractError(f"{label} must be repository-relative: {value!r}")
    if _TRAVERSAL_TOKEN_RE.search(value) or any(part in {".", ".."} for part in posix.parts):
        raise PathContractError(f"{label} must not contain traversal segments: {value!r}")
    if posix.as_posix() != value or value.endswith("/"):
        raise PathContractError(f"{label} is not canonical POSIX path syntax: {value!r}")
    return value


def _repo_path(root: Path, value: object, label: str) -> Path:
    relative = validate_repo_relative_path(value, label)
    return root.joinpath(*relative.split("/"))


def _repo_record_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise PathContractError(f"path is outside the repository root: {path}") from exc


def _scan_persisted_strings(value: object, label: str = "record") -> None:
    """Reject obvious machine-local path tokens anywhere in serialized contract material."""
    if isinstance(value, str):
        if _ABSOLUTE_TOKEN_RE.search(value) or _TRAVERSAL_TOKEN_RE.search(value):
            raise PathContractError(f"{label} contains a machine-local or traversal path")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _scan_persisted_strings(item, f"{label}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _scan_persisted_strings(item, f"{label}[{index}]")


def _json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseContractError(f"cannot read {label}: {path}") from exc
    if not isinstance(payload, dict):
        raise ReleaseContractError(f"{label} must be a JSON object: {path}")
    return cast(dict[str, Any], payload)


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    _scan_persisted_strings(payload, path.name)
    path.write_bytes(exact_json_bytes(payload))


@dataclass(frozen=True)
class ReleaseConfig:
    path: Path
    payload: Mapping[str, Any]
    sha256: str

    def section(self, name: str) -> Mapping[str, Any]:
        value = self.payload.get(name)
        if not isinstance(value, Mapping):
            raise ReleaseContractError(f"WP2.8 config section {name!r} is missing")
        return cast(Mapping[str, Any], value)

    def path_value(self, section: str, key: str, root: Path = ROOT) -> Path:
        return _repo_path(root, self.section(section).get(key), f"{section}.{key}")


def _validate_config(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != 1 or payload.get("work_package") != "WP2.8":
        raise ReleaseContractError("WP2.8 release config schema/work package is unsupported")
    if payload.get("release_status") != "m2_qualified":
        raise ReleaseContractError("WP2.8 release status must be m2_qualified")
    if payload.get("serving_status") != "not_served":
        raise ReleaseContractError("WP2.8 serving status must be not_served")
    if payload.get("base_commit") != REQUIRED_WP27_BASE_COMMIT:
        raise ReleaseContractError("WP2.8 config does not pin the merged WP2.7 origin/main commit")

    for key in ("output_dir",):
        validate_repo_relative_path(payload.get(key), key)
    wp24 = payload.get("wp24")
    wp27 = payload.get("wp27")
    reproduction = payload.get("reproduction")
    if (
        not isinstance(wp24, Mapping)
        or not isinstance(wp27, Mapping)
        or not isinstance(reproduction, Mapping)
    ):
        raise ReleaseContractError("WP2.8 config lacks wp24, wp27, or reproduction registration")

    for key in (
        "config_path",
        "resolved_config_path",
        "metrics_path",
        "artifact_manifest_path",
        "model_path",
        "assignments_path",
    ):
        validate_repo_relative_path(wp24.get(key), f"wp24.{key}")
    for key in (
        "calibration_config_path",
        "holdout_config_path",
        "decision_path",
        "audit_path",
        "metrics_path",
        "record_path",
    ):
        validate_repo_relative_path(wp27.get(key), f"wp27.{key}")
    presentation_paths = wp27.get("presentation_paths")
    if not isinstance(presentation_paths, list):
        raise ReleaseContractError("wp27.presentation_paths must be a list")
    for index, path in enumerate(presentation_paths):
        validate_repo_relative_path(path, f"wp27.presentation_paths[{index}]")
    for section_name, section, keys in (
        (
            "wp24",
            wp24,
            (
                "config_sha256",
                "resolved_config_sha256",
                "metrics_sha256",
                "artifact_manifest_sha256",
                "model_sha256",
                "assignments_sha256",
            ),
        ),
        (
            "wp27",
            wp27,
            (
                "calibration_config_sha256",
                "holdout_config_sha256",
                "decision_sha256",
                "decision_file_sha256",
                "audit_sha256",
                "metrics_sha256",
                "record_sha256",
            ),
        ),
    ):
        for key in keys:
            _digest(section.get(key), f"{section_name}.{key}")

    expected = wp24.get("expected_fold_sizes")
    if not isinstance(expected, Mapping) or set(expected) != {"0", "1", "2", "3", "4"}:
        raise ReleaseContractError("wp24.expected_fold_sizes must register all five folds")
    if wp24.get("expected_shots") != 2872 or wp24.get("expected_matches") != 115:
        raise ReleaseContractError("WP2.8 must retain the registered WP2.4 development anchors")
    if reproduction.get("scope") != "development_only":
        raise ReleaseContractError("historical reproduction scope must be development_only")
    if reproduction.get("new_holdout_access") is not False:
        raise ReleaseContractError("WP2.8 reproduction must record no new holdout access")
    if reproduction.get("forbidden_tournaments") != ["WC2022", "Euro2024"]:
        raise ReleaseContractError("WP2.8 must forbid both calibration and holdout tournaments")
    fingerprint = reproduction.get("exact_environment_fingerprint")
    if not isinstance(fingerprint, Mapping):
        raise ReleaseContractError("exact reproduction environment fingerprint is missing")
    for key in (
        "os",
        "architecture",
        "python_implementation",
        "python_version",
        "uv_version",
        "uv_lock_sha256",
        "reproduction_commit",
        "config_sha256",
    ):
        if not isinstance(fingerprint.get(key), str) or not fingerprint.get(key):
            raise ReleaseContractError(f"exact environment fingerprint lacks {key}")
    _digest(
        fingerprint["uv_lock_sha256"], "reproduction.exact_environment_fingerprint.uv_lock_sha256"
    )
    _digest(
        fingerprint["config_sha256"], "reproduction.exact_environment_fingerprint.config_sha256"
    )
    tolerance = reproduction.get("numeric_tolerance")
    if (
        type(tolerance) not in (int, float)
        or not math.isfinite(float(cast(Real, tolerance)))
        or float(cast(Real, tolerance)) <= 0
    ):
        raise ReleaseContractError(
            "reproduction.numeric_tolerance must be a positive finite number"
        )

    _scan_persisted_strings(payload)


def load_release_config(
    path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    enforce_registered: bool = True,
) -> ReleaseConfig:
    source = Path(path).resolve()
    try:
        raw = source.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseContractError(f"cannot read WP2.8 release config {source}") from exc
    if not isinstance(payload, dict):
        raise ReleaseContractError("WP2.8 release config must be a JSON object")
    digest = sha256_bytes(raw)
    if enforce_registered and (
        source != DEFAULT_CONFIG_PATH.resolve() or digest != REGISTERED_CONFIG_SHA256
    ):
        raise ReleaseContractError(
            "real WP2.8 execution requires the byte-pinned registered config"
        )
    _validate_config(cast(Mapping[str, Any], payload))
    return ReleaseConfig(source, cast(Mapping[str, Any], payload), digest)


def verify_wp27_base(
    *,
    current_head: str,
    origin_main: str,
    required_base: str = REQUIRED_WP27_BASE_COMMIT,
    current_is_descendant: bool = True,
) -> None:
    """Reject a stale WP2.6 base while allowing the WP2.8 implementation commits themselves."""
    if required_base != REQUIRED_WP27_BASE_COMMIT:
        raise ReleaseContractError("the WP2.8 required base constant was changed")
    if origin_main != required_base:
        raise ReleaseContractError(
            f"origin/main is {origin_main}, expected merged WP2.7 {required_base}"
        )
    if not current_is_descendant:
        raise ReleaseContractError(
            f"current HEAD {current_head} does not descend from merged WP2.7 {required_base}"
        )


def _verify_current_base(root: Path) -> None:
    current = git(root, "rev-parse", "HEAD")
    origin = git(root, "rev-parse", "origin/main")
    ancestor = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", REQUIRED_WP27_BASE_COMMIT, current],
        capture_output=True,
        check=False,
    )
    verify_wp27_base(
        current_head=current,
        origin_main=origin,
        current_is_descendant=ancestor.returncode == 0,
    )


def _verify_file_hash(path: Path, expected: object, label: str) -> str:
    digest = _digest(expected, label)
    if not path.is_file():
        raise ReleaseContractError(f"{label} file is missing: {path}")
    actual = sha256_bytes(path.read_bytes())
    if actual != digest:
        raise ReleaseContractError(f"{label} hash mismatch: {actual} != {digest}")
    return actual


@dataclass(frozen=True)
class WP24Evidence:
    config: Mapping[str, Any]
    metrics: Mapping[str, Any]
    artifact_manifest: Mapping[str, Any]
    config_path: str
    config_sha256: str
    resolved_config_path: str
    resolved_config_sha256: str
    metrics_path: str
    metrics_sha256: str
    artifact_manifest_path: str
    artifact_manifest_sha256: str
    model_path: str
    model_sha256: str


def verify_wp24_evidence(config: ReleaseConfig, *, root: Path = ROOT) -> WP24Evidence:
    registration = config.section("wp24")
    config_path = _repo_path(root, registration["config_path"], "wp24.config_path")
    resolved_config_path = _repo_path(
        root, registration["resolved_config_path"], "wp24.resolved_config_path"
    )
    metrics_path = _repo_path(root, registration["metrics_path"], "wp24.metrics_path")
    manifest_path = _repo_path(
        root, registration["artifact_manifest_path"], "wp24.artifact_manifest_path"
    )
    model_path = _repo_path(root, registration["model_path"], "wp24.model_path")

    config_sha = _verify_file_hash(config_path, registration["config_sha256"], "WP2.4 config")
    resolved_config_sha = _verify_file_hash(
        resolved_config_path,
        registration["resolved_config_sha256"],
        "WP2.4 resolved config",
    )
    metrics_sha = _verify_file_hash(metrics_path, registration["metrics_sha256"], "WP2.4 metrics")
    artifact_manifest_sha = _verify_file_hash(
        manifest_path, registration["artifact_manifest_sha256"], "WP2.4 artifact manifest"
    )
    model_sha = _verify_file_hash(model_path, registration["model_sha256"], "WP2.4 model")
    source_config = _json_object(config_path, "WP2.4 config")
    resolved_config = _json_object(resolved_config_path, "WP2.4 resolved config")
    metrics = _json_object(metrics_path, "WP2.4 metrics")
    manifest = _json_object(manifest_path, "WP2.4 artifact manifest")
    for payload, label in (
        (source_config, "WP2.4 config"),
        (resolved_config, "WP2.4 resolved config"),
        (metrics, "WP2.4 metrics"),
        (manifest, "WP2.4 artifact manifest"),
    ):
        _scan_persisted_strings(payload, label)
    if source_config.get("experiment_id") != registration.get("experiment_id"):
        raise ReleaseContractError("WP2.4 config experiment identity does not match registration")
    if resolved_config.get("experiment_id") != registration.get("experiment_id"):
        raise ReleaseContractError(
            "WP2.4 resolved config experiment identity does not match registration"
        )
    if metrics.get("shipped_candidate") != "full_minus_presence":
        raise ReleaseContractError("WP2.4 release input is not full_minus_presence")
    if metrics.get("shipped_feature_set") != "geometry+categoricals":
        raise ReleaseContractError("WP2.4 release input has the wrong feature set")
    if metrics.get("n_rows") != registration.get("expected_shots") or metrics.get(
        "n_matches"
    ) != registration.get("expected_matches"):
        raise ReleaseContractError("WP2.4 measured development anchors do not match registration")
    if manifest.get("model_pickle_path") != registration.get("model_path"):
        raise ReleaseContractError("WP2.4 artifact manifest model path is not registered")
    if manifest.get("model_pickle_sha256") != model_sha:
        raise ReleaseContractError(
            "WP2.4 artifact manifest model digest is not measured model digest"
        )
    if manifest.get("input_config_path") != registration.get("config_path"):
        raise ReleaseContractError("WP2.4 artifact manifest config path is not registered")
    if manifest.get("input_config_sha256") != registration.get("config_sha256"):
        raise ReleaseContractError("WP2.4 artifact manifest config digest is not registered")
    return WP24Evidence(
        config=resolved_config,
        metrics=metrics,
        artifact_manifest=manifest,
        config_path=str(registration["config_path"]),
        config_sha256=config_sha,
        resolved_config_path=str(registration["resolved_config_path"]),
        resolved_config_sha256=resolved_config_sha,
        metrics_path=str(registration["metrics_path"]),
        metrics_sha256=metrics_sha,
        artifact_manifest_path=str(registration["artifact_manifest_path"]),
        artifact_manifest_sha256=artifact_manifest_sha,
        model_path=str(registration["model_path"]),
        model_sha256=model_sha,
    )


def _is_presentation_path(relative_path: str) -> bool:
    return PurePosixPath(relative_path).suffix.lower() in _PRESENTATION_SUFFIXES


def _verify_evidence_hash_map(
    root: Path,
    evidence: Mapping[str, Any],
    *,
    label: str,
) -> dict[str, str]:
    if not isinstance(evidence, Mapping) or not evidence:
        raise ReleaseContractError(f"{label} has no evidence hash map")
    verified: dict[str, str] = {}
    for relative, expected in evidence.items():
        path_name = validate_repo_relative_path(relative, f"{label} path")
        digest = _digest(expected, f"{label} hash")
        # Editorial reports, model cards, and plots are references, not release-integrity inputs.
        if _is_presentation_path(path_name):
            verified[path_name] = digest
            continue
        path = _repo_path(root, path_name, f"{label} path")
        _verify_file_hash(path, digest, f"{label} {path_name}")
        verified[path_name] = digest
    return verified


@dataclass(frozen=True)
class WP27Evidence:
    decision: Mapping[str, Any]
    audit: Mapping[str, Any]
    metrics: Mapping[str, Any]
    record: Mapping[str, Any]
    decision_path: str
    audit_path: str
    metrics_path: str
    record_path: str
    decision_file_sha256: str
    audit_file_sha256: str
    metrics_file_sha256: str
    record_file_sha256: str
    decision_sha256: str
    holdout_membership_sha256: str
    execution_provenance_sha256: str
    measured_evidence_sha256: Mapping[str, str]


def verify_wp27_measured_chain(config: ReleaseConfig, *, root: Path = ROOT) -> WP27Evidence:
    """Verify WP2.7 machine evidence while deliberately ignoring presentation-file digests."""
    registration = config.section("wp27")
    decision_path = _repo_path(root, registration["decision_path"], "wp27.decision_path")
    audit_path = _repo_path(root, registration["audit_path"], "wp27.audit_path")
    metrics_path = _repo_path(root, registration["metrics_path"], "wp27.metrics_path")
    record_path = _repo_path(root, registration["record_path"], "wp27.record_path")
    decision_file_sha = _verify_file_hash(
        decision_path, registration["decision_file_sha256"], "WP2.7 decision"
    )
    audit_file_sha = _verify_file_hash(audit_path, registration["audit_sha256"], "WP2.7 audit")
    metrics_file_sha = _verify_file_hash(
        metrics_path, registration["metrics_sha256"], "WP2.7 metrics"
    )
    record_file_sha = _verify_file_hash(record_path, registration["record_sha256"], "WP2.7 record")

    decision_envelope = _json_object(decision_path, "WP2.7 calibration decision")
    audit = _json_object(audit_path, "WP2.7 holdout audit")
    metrics = _json_object(metrics_path, "WP2.7 holdout metrics")
    record = _json_object(record_path, "WP2.7 experiment record")
    for payload, label in (
        (decision_envelope, "WP2.7 decision"),
        (audit, "WP2.7 audit"),
        (metrics, "WP2.7 metrics"),
        (record, "WP2.7 record"),
    ):
        _scan_persisted_strings(payload, label)
    decision = load_calibration_decision(decision_path)
    decision_sha = decision.decision_sha256
    if decision_sha != registration["decision_sha256"]:
        raise ReleaseContractError("WP2.7 calibration decision digest is not registered")
    if decision_file_sha != sha256_bytes(decision_path.read_bytes()):
        raise ReleaseContractError("WP2.7 decision file digest changed during verification")

    calibration_config_path = _repo_path(
        root, registration["calibration_config_path"], "wp27.calibration_config_path"
    )
    holdout_config_path = _repo_path(
        root, registration["holdout_config_path"], "wp27.holdout_config_path"
    )
    _verify_file_hash(
        calibration_config_path,
        registration["calibration_config_sha256"],
        "WP2.7 calibration config",
    )
    _verify_file_hash(
        holdout_config_path,
        registration["holdout_config_sha256"],
        "WP2.7 holdout config",
    )
    calibration_config = _json_object(calibration_config_path, "WP2.7 calibration config")
    holdout_config = _json_object(holdout_config_path, "WP2.7 holdout config")
    if decision.payload.get("calibration_config_path") != registration["calibration_config_path"]:
        raise ReleaseContractError(
            "WP2.7 decision does not reference the registered calibration config"
        )
    if (
        decision.payload.get("calibration_config_sha256")
        != registration["calibration_config_sha256"]
    ):
        raise ReleaseContractError("WP2.7 decision calibration-config digest is not registered")
    if holdout_config.get("required_calibration_decision") != registration["decision_path"]:
        raise ReleaseContractError(
            "WP2.7 holdout config does not reference the registered decision"
        )
    if holdout_config.get("calibration_config_path") != registration["calibration_config_path"]:
        raise ReleaseContractError(
            "WP2.7 holdout config does not reference the registered calibration config"
        )
    frozen_pins = calibration_config.get("frozen_base")
    if not isinstance(frozen_pins, Mapping):
        raise ReleaseContractError("WP2.7 calibration config lacks frozen base pins")
    pins = BaseModelPins.from_mapping(cast(Mapping[str, object], frozen_pins))
    validate_repo_relative_path(pins.artifact_path, "wp27.frozen_base.artifact_path")
    validate_repo_relative_path(
        pins.artifact_manifest_path, "wp27.frozen_base.artifact_manifest_path"
    )
    # The real repository check uses the existing WP2.7 base identity verifier.  The root seam is
    # retained for fixture tests, where a synthetic chain need only exercise the cross-references.
    if root.resolve() == ROOT.resolve():
        try:
            frozen = freeze_base_model(pins)
            verify_calibration_decision(decision, frozen)
        except (OSError, ValueError, RuntimeError) as exc:
            raise ReleaseContractError(
                "WP2.7 calibration decision failed frozen-base verification"
            ) from exc

    if audit.get("schema_version") != 2 or audit.get("phase") != "wp2-7-holdout":
        raise ReleaseContractError("WP2.7 audit is not the completed holdout audit")
    if audit.get("holdout_open_count") != 1:
        raise ReleaseContractError("WP2.7 audit does not record exactly one logical holdout open")
    expected_stages = [
        "holdout_open",
        "membership_asserted",
        "scored",
        "bootstrap",
        "slices",
        "evidence_written",
        "holdout_closed",
        "experiment_record_written",
        "audit_finalized",
    ]
    if audit.get("stages") != expected_stages:
        raise ReleaseContractError("WP2.7 holdout audit stages are incomplete or reordered")
    counts = {key: audit.get(key) for key in ("n_rows", "n_matches", "n_goals", "n_misses")}
    if counts != {"n_rows": 1304, "n_matches": 51, "n_goals": 98, "n_misses": 1206}:
        raise ReleaseContractError("WP2.7 holdout aggregate counts changed")
    if audit.get("n_goals", 0) + audit.get("n_misses", 0) != audit.get("n_rows"):
        raise ReleaseContractError("WP2.7 holdout goal/miss counts do not reconcile")
    if audit.get("decision_sha256") != decision_sha:
        raise ReleaseContractError("WP2.7 audit decision digest is not the calibration decision")
    if (
        record.get("decision_sha256") != decision_sha
        or metrics.get("decision_sha256") != decision_sha
    ):
        raise ReleaseContractError("WP2.7 measured artifacts do not share the decision digest")
    if record.get("holdout_membership_sha256") != audit.get("membership_sha256"):
        raise ReleaseContractError("WP2.7 record and audit membership digests disagree")
    membership_sha = _digest(audit.get("membership_sha256"), "WP2.7 membership digest")
    execution = record.get("execution_provenance")
    if not isinstance(execution, Mapping):
        raise ReleaseContractError("WP2.7 record lacks execution provenance")
    execution_sha = exact_payload_sha256(cast(Mapping[str, object], execution))
    if execution_sha != audit.get("execution_provenance_sha256"):
        raise ReleaseContractError("WP2.7 audit execution provenance digest is invalid")
    if record.get("real_rows_accessed_in_this_recording") is not True:
        raise ReleaseContractError("WP2.7 record does not prove the supervised holdout execution")
    if record.get("aggregate_counts") != {
        "rows": counts["n_rows"],
        "matches": counts["n_matches"],
        "goals": counts["n_goals"],
        "misses": counts["n_misses"],
    }:
        raise ReleaseContractError("WP2.7 record aggregate counts disagree with the audit")
    for variant in ("raw", "calibrated"):
        measured = metrics.get("variants", {}).get(variant, {})
        if (
            measured.get("n") != counts["n_rows"]
            or measured.get("positive_count") != counts["n_goals"]
        ):
            raise ReleaseContractError(f"WP2.7 {variant} metrics do not match audit counts")
    if (
        record.get("adopted_variant") != decision.adopted_variant
        or record.get("adopted_variant") != "calibrated"
    ):
        raise ReleaseContractError("WP2.7 release decision is not the recorded calibrated variant")
    audit_hashes = _verify_evidence_hash_map(
        root, cast(Mapping[str, Any], audit.get("evidence_files_sha256")), label="WP2.7 audit"
    )
    record_hashes = _verify_evidence_hash_map(
        root, cast(Mapping[str, Any], record.get("evidence_files_sha256")), label="WP2.7 record"
    )
    measured_hashes = {
        path: digest
        for path, digest in {**audit_hashes, **record_hashes}.items()
        if not _is_presentation_path(path)
    }
    if set(measured_hashes) != {
        str(registration["metrics_path"]),
        str(registration["record_path"]),
    }:
        raise ReleaseContractError("WP2.7 measured evidence hash set is incomplete")
    for relative in set(audit_hashes) & set(record_hashes):
        if audit_hashes[relative] != record_hashes[relative]:
            raise ReleaseContractError(f"WP2.7 evidence hash maps disagree for {relative}")
    if metrics.get("n_rows") != counts["n_rows"] or metrics.get("n_matches") != counts["n_matches"]:
        raise ReleaseContractError("WP2.7 metrics lack the registered aggregate anchors")
    return WP27Evidence(
        decision=decision_envelope,
        audit=audit,
        metrics=metrics,
        record=record,
        decision_path=str(registration["decision_path"]),
        audit_path=str(registration["audit_path"]),
        metrics_path=str(registration["metrics_path"]),
        record_path=str(registration["record_path"]),
        decision_file_sha256=decision_file_sha,
        audit_file_sha256=audit_file_sha,
        metrics_file_sha256=metrics_file_sha,
        record_file_sha256=record_file_sha,
        decision_sha256=decision_sha,
        holdout_membership_sha256=membership_sha,
        execution_provenance_sha256=execution_sha,
        measured_evidence_sha256=measured_hashes,
    )


def _split_ids(assignments: object, split: str) -> set[object]:
    if hasattr(assignments, "ids_for"):
        return set(cast(Any, assignments).ids_for(split))
    if isinstance(assignments, Mapping):
        values = assignments.get(split, ())
        return set(cast(Iterable[object], values))
    raise DevelopmentOnlyError("assignments must expose ids_for() or be a split-to-IDs mapping")


def assert_development_only_match_ids(ids: Iterable[object], assignments: object) -> None:
    """Reject every non-development ID before a reproduction row can reach preprocessing."""
    development = _split_ids(assignments, "development")
    forbidden = _split_ids(assignments, "calibration") | _split_ids(assignments, "holdout")
    observed = set(ids)
    if observed & forbidden:
        raise DevelopmentOnlyError(
            "reproduction attempted to use calibration/holdout match IDs: "
            + ", ".join(sorted(map(str, observed & forbidden)))
        )
    unexpected = observed - development
    if unexpected:
        raise DevelopmentOnlyError(
            "reproduction attempted to use unregistered match IDs: "
            + ", ".join(sorted(map(str, unexpected)))
        )


def _row_value(row: object, name: str) -> object:
    if isinstance(row, Mapping):
        return row.get(name)
    return getattr(row, name, None)


def assert_development_only_rows(rows: Sequence[object], assignments: object) -> None:
    assert_development_only_match_ids([_row_value(row, "match_id") for row in rows], assignments)


def assert_development_anchors(
    rows: Sequence[object],
    *,
    expected_shots: int = 2872,
    expected_matches: int = 115,
    expected_fold_sizes: Mapping[str | int, int] | None = None,
) -> None:
    expected = expected_fold_sizes or {"0": 570, "1": 552, "2": 602, "3": 576, "4": 572}
    if len(rows) != expected_shots:
        raise DevelopmentOnlyError(
            f"development reproduction has {len(rows)} rows, expected {expected_shots}"
        )
    if len({_row_value(row, "match_id") for row in rows}) != expected_matches:
        raise DevelopmentOnlyError("development reproduction match count changed")
    fold_sizes: dict[str, int] = {}
    for row in rows:
        fold = _row_value(row, "fold")
        if fold is None:
            raise DevelopmentOnlyError("development reproduction row has no registered fold")
        key = str(fold)
        fold_sizes[key] = fold_sizes.get(key, 0) + 1
    normalized = {str(key): value for key, value in expected.items()}
    if fold_sizes != normalized:
        raise DevelopmentOnlyError(f"development fold sizes {fold_sizes} != {normalized}")


def collect_environment_fingerprint() -> dict[str, str]:
    result = subprocess.run(["uv", "--version"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise EnvironmentFingerprintError("cannot determine the uv version")
    match = re.search(r"uv\s+(\S+)", result.stdout.strip())
    if match is None:
        raise EnvironmentFingerprintError("uv --version output is malformed")
    return {
        "os": platform.system(),
        "architecture": platform.machine(),
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "uv_version": match.group(1),
    }


def build_historical_reproduction_environment(
    parent: Mapping[str, str], db_url_env: str
) -> dict[str, str]:
    """Build the child environment without inheriting training/test routing overrides."""
    if not parent.get(db_url_env):
        raise ReproductionMismatchError(f"{db_url_env} must be set for the acceptance reproduction")
    inherited = [name for name in _HISTORICAL_OVERRIDE_ENV_VARS if parent.get(name)]
    if inherited:
        raise ReproductionMismatchError(
            "historical reproduction refuses training overrides: " + ", ".join(inherited)
        )
    environment = dict(parent)
    # The WP2.4 trainer falls back to TOUCHLINE_DB_URL when its registered full-cohort variable is
    # absent.  Remove the fallback so the command cannot silently use a different database target.
    environment.pop("TOUCHLINE_DB_URL", None)
    environment["TOUCHLINE_WP28_REPRODUCTION_SCOPE"] = "development_only"
    return environment


def parse_historical_environment_fingerprint(python_output: str, uv_output: str) -> dict[str, str]:
    try:
        payload = json.loads(python_output)
    except json.JSONDecodeError as exc:
        raise EnvironmentFingerprintError(
            "historical uv run python fingerprint output is not JSON"
        ) from exc
    if not isinstance(payload, Mapping):
        raise EnvironmentFingerprintError("historical Python fingerprint is not an object")
    required = ("os", "architecture", "python_implementation", "python_version")
    if any(not isinstance(payload.get(key), str) or not payload.get(key) for key in required):
        raise EnvironmentFingerprintError("historical Python fingerprint is incomplete")
    match = re.search(r"uv\s+(\S+)", uv_output.strip())
    if match is None:
        raise EnvironmentFingerprintError("historical uv --version output is malformed")
    return {
        "os": str(payload["os"]),
        "architecture": str(payload["architecture"]),
        "python_implementation": str(payload["python_implementation"]),
        "python_version": str(payload["python_version"]),
        "uv_version": match.group(1),
    }


def _collect_historical_environment_fingerprint(
    worktree: Path, *, env: Mapping[str, str]
) -> dict[str, str]:
    python_probe = (
        "import json,platform; "
        "print(json.dumps({'os': platform.system(), 'architecture': platform.machine(), "
        "'python_implementation': platform.python_implementation(), "
        "'python_version': platform.python_version()}))"
    )
    python_result = subprocess.run(
        ["uv", "run", "python", "-c", python_probe],
        cwd=worktree,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if python_result.returncode != 0:
        raise EnvironmentFingerprintError(
            "cannot fingerprint the historical uv environment: "
            + (python_result.stderr or python_result.stdout).strip()
        )
    uv_result = subprocess.run(
        ["uv", "--version"],
        cwd=worktree,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if uv_result.returncode != 0:
        raise EnvironmentFingerprintError("cannot fingerprint uv in the historical checkout")
    return parse_historical_environment_fingerprint(python_result.stdout, uv_result.stdout)


def verify_environment_fingerprint(
    expected: Mapping[str, object], actual: Mapping[str, object]
) -> bool:
    required = (
        "os",
        "architecture",
        "python_implementation",
        "python_version",
        "uv_version",
        "uv_lock_sha256",
        "reproduction_commit",
        "config_sha256",
    )
    for key in required:
        if not isinstance(expected.get(key), str) or not expected.get(key):
            raise EnvironmentFingerprintError(f"registered fingerprint lacks {key}")
        if not isinstance(actual.get(key), str) or not actual.get(key):
            raise EnvironmentFingerprintError(f"observed fingerprint lacks {key}")
    _digest(expected["uv_lock_sha256"], "registered uv.lock fingerprint")
    _digest(expected["config_sha256"], "registered config fingerprint")
    return all(expected[key] == actual[key] for key in required)


@dataclass(frozen=True)
class ComparisonResult:
    comparison_mode: str
    canonical_json_equal: bool
    artifact_byte_identical: bool
    feature_contract_equal: bool
    metrics_within_tolerance: bool
    metadata_within_tolerance: bool
    comparison_table: tuple[Mapping[str, object], ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "comparison_mode": self.comparison_mode,
            "canonical_json_equal": self.canonical_json_equal,
            "artifact_byte_identical": self.artifact_byte_identical,
            "feature_contract_equal": self.feature_contract_equal,
            "metrics_within_tolerance": self.metrics_within_tolerance,
            "metadata_within_tolerance": self.metadata_within_tolerance,
            "comparison_table": [dict(row) for row in self.comparison_table],
        }


def _compare_values(
    expected: object, actual: object, tolerance: float, path: str = "value"
) -> None:
    if isinstance(expected, Mapping) or isinstance(actual, Mapping):
        if (
            not isinstance(expected, Mapping)
            or not isinstance(actual, Mapping)
            or set(expected) != set(actual)
        ):
            raise ReproductionMismatchError(f"reproduction metadata differs at {path}")
        for key in expected:
            _compare_values(expected[key], actual[key], tolerance, f"{path}.{key}")
        return
    if isinstance(expected, list) or isinstance(actual, list):
        if (
            not isinstance(expected, list)
            or not isinstance(actual, list)
            or len(expected) != len(actual)
        ):
            raise ReproductionMismatchError(f"reproduction metadata differs at {path}")
        for index, (left, right) in enumerate(zip(expected, actual, strict=True)):
            _compare_values(left, right, tolerance, f"{path}[{index}]")
        return
    if type(expected) in (int, float) and type(actual) in (int, float):
        if not math.isclose(
            float(cast(Real, expected)),
            float(cast(Real, actual)),
            rel_tol=0.0,
            abs_tol=tolerance,
        ):
            raise ReproductionMismatchError(f"reproduction numeric value differs at {path}")
        return
    if expected != actual:
        raise ReproductionMismatchError(f"reproduction metadata differs at {path}")


def _comparison_payload(payload: Mapping[str, Any], kind: str, exact: bool) -> dict[str, Any]:
    value = json.loads(json.dumps(payload))
    if not exact:
        value.pop("runtime_fingerprint", None)
        if kind in {"metrics", "artifact_manifest", "config"}:
            value.pop("model_pickle_sha256", None)
    return cast(dict[str, Any], value)


_COMPARISON_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("metrics.n_rows", ("metrics", "n_rows")),
    ("metrics.n_matches", ("metrics", "n_matches")),
    ("metrics.shipped_best_c", ("metrics", "shipped_best_c")),
    (
        "metrics.candidate.mean_log_loss",
        ("metrics", "candidates", "full_minus_presence", "mean_log_loss"),
    ),
    (
        "metrics.candidate.pooled_oof.log_loss",
        ("metrics", "candidates", "full_minus_presence", "pooled_oof", "log_loss"),
    ),
    (
        "metrics.candidate.pooled_oof.brier",
        ("metrics", "candidates", "full_minus_presence", "pooled_oof", "brier"),
    ),
    (
        "metrics.candidate.pooled_oof.roc_auc",
        ("metrics", "candidates", "full_minus_presence", "pooled_oof", "roc_auc"),
    ),
    ("config.expected_shots", ("config", "expected_shots")),
    ("config.expected_matches", ("config", "expected_matches")),
    ("artifact_manifest.artifact_schema_version", ("artifact_manifest", "artifact_schema_version")),
    ("artifact_manifest.shipped_best_c", ("artifact_manifest", "shipped_best_c")),
)


def _comparison_table(
    canonical: Mapping[str, Mapping[str, Any]],
    regenerated: Mapping[str, Mapping[str, Any]],
    *,
    tolerance: float,
) -> tuple[Mapping[str, object], ...]:
    rows: list[Mapping[str, object]] = []
    for label, path in _COMPARISON_FIELDS:
        source = path[0]
        expected: object = canonical[source]
        actual: object = regenerated[source]
        for key in path[1:]:
            if not isinstance(expected, Mapping) or not isinstance(actual, Mapping):
                expected = None
                actual = None
                break
            expected = expected.get(key)
            actual = actual.get(key)
        numeric = type(expected) in (int, float) and type(actual) in (int, float)
        delta: float | None = None
        if numeric:
            delta = float(cast(Real, actual)) - float(cast(Real, expected))
            within = math.isclose(delta, 0.0, rel_tol=0.0, abs_tol=tolerance)
        else:
            within = expected == actual
        rows.append(
            {
                "field": label,
                "canonical": expected,
                "regenerated": actual,
                "delta": delta,
                "tolerance": tolerance,
                "outcome": "pass" if within else "fail",
            }
        )
    return tuple(rows)


def compare_reproduction(
    canonical: Mapping[str, Mapping[str, Any]],
    regenerated: Mapping[str, Mapping[str, Any]],
    *,
    canonical_model_sha256: str,
    regenerated_model_sha256: str,
    exact_environment_match: bool,
    numeric_tolerance: float,
) -> ComparisonResult:
    """Compare old-run JSON/artifact metadata with an explicit exact-vs-tolerance mode."""
    mode = "exact" if exact_environment_match else "numeric_tolerance"
    table = _comparison_table(
        canonical, regenerated, tolerance=0.0 if exact_environment_match else numeric_tolerance
    )
    if exact_environment_match:
        for kind in ("metrics", "config", "artifact_manifest"):
            if exact_json_bytes(canonical[kind]) != exact_json_bytes(regenerated[kind]):
                raise ReproductionMismatchError(f"exact {kind} JSON reproduction differs")
        if regenerated_model_sha256 != canonical_model_sha256:
            raise ReproductionMismatchError("exact model artifact reproduction differs")
        return ComparisonResult(mode, True, True, True, True, True, table)

    try:
        _compare_values(
            _comparison_payload(canonical["metrics"], "metrics", False),
            _comparison_payload(regenerated["metrics"], "metrics", False),
            numeric_tolerance,
            "metrics",
        )
        _compare_values(
            _comparison_payload(canonical["config"], "config", False),
            _comparison_payload(regenerated["config"], "config", False),
            numeric_tolerance,
            "config",
        )
        _compare_values(
            _comparison_payload(canonical["artifact_manifest"], "artifact_manifest", False),
            _comparison_payload(regenerated["artifact_manifest"], "artifact_manifest", False),
            numeric_tolerance,
            "artifact_manifest",
        )
    except ReproductionMismatchError:
        raise
    expected_columns = canonical["metrics"].get("shipped_feature_columns")
    actual_columns = regenerated["metrics"].get("shipped_feature_columns")
    feature_equal = (
        expected_columns == actual_columns
        and canonical["metrics"].get("shipped_candidate")
        == regenerated["metrics"].get("shipped_candidate")
        and canonical["metrics"].get("shipped_feature_set")
        == regenerated["metrics"].get("shipped_feature_set")
    )
    if not feature_equal:
        raise ReproductionMismatchError("reproduced feature contract differs")
    # A non-matching environment may happen to serialize the same bytes, but WP2.8 must not make
    # a byte-identical reproduction claim outside the registered fingerprint.
    return ComparisonResult(mode, False, False, True, True, True, table)


@dataclass(frozen=True)
class ReproductionResult:
    environment_fingerprint: Mapping[str, str]
    exact_environment_match: bool
    development_shots: int
    development_matches: int
    development_fold_sizes: Mapping[str, int]
    metrics_sha256: str
    artifact_manifest_sha256: str
    model_sha256: str
    comparison: ComparisonResult
    new_holdout_access: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "scope": "development_only",
            "new_holdout_access": self.new_holdout_access,
            "holdout_rows_loaded": False,
            "environment_fingerprint": dict(self.environment_fingerprint),
            "exact_environment_match": self.exact_environment_match,
            "byte_identical_reproduction_claim": self.comparison.artifact_byte_identical
            and self.exact_environment_match,
            "development_anchors": {
                "shots": self.development_shots,
                "matches": self.development_matches,
                "fold_sizes": dict(self.development_fold_sizes),
            },
            "metrics_sha256": self.metrics_sha256,
            "artifact_manifest_sha256": self.artifact_manifest_sha256,
            "model_sha256": self.model_sha256,
            "comparison": self.comparison.as_dict(),
        }


def _expected_fingerprint(config: ReleaseConfig) -> Mapping[str, object]:
    return cast(
        Mapping[str, object], config.section("reproduction")["exact_environment_fingerprint"]
    )


def _run_checked(
    command: Sequence[str], *, cwd: Path, env: Mapping[str, str] | None = None
) -> None:
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ReproductionMismatchError(f"command failed ({' '.join(command)}): {detail}")


def _assert_historical_development_loader(worktree: Path, config: ReleaseConfig) -> None:
    train_source = (worktree / "backend/src/touchline/modeling/train.py").read_text(
        encoding="utf-8"
    )
    dataset_source = (worktree / "backend/src/touchline/modeling/dataset.py").read_text(
        encoding="utf-8"
    )
    if (
        "load_development_cohort" not in train_source
        or "verify_development_anchor" not in train_source
    ):
        raise DevelopmentOnlyError(
            "historical training command is not the registered development loader"
        )
    if "load_partition_cohort" in train_source:
        raise DevelopmentOnlyError("historical reproduction command exposes a partition loader")
    if (
        "development_match_ids" not in dataset_source
        or "DevelopmentLeakError" not in dataset_source
    ):
        raise DevelopmentOnlyError("historical loader lacks the non-development row guard")
    # The assignment file is checked before the database command starts.  This is intentionally
    # an ID-only check: no calibration or holdout row is materialized by WP2.8.
    assignments_path = _repo_path(
        worktree, config.section("wp24")["assignments_path"], "wp24.assignments_path"
    )
    raw = assignments_path.read_bytes()
    expected_hash = _digest(config.section("wp24")["assignments_sha256"], "WP2.4 assignments")
    if sha256_bytes(raw) != expected_hash:
        raise DevelopmentOnlyError(
            "historical assignment lock does not match the registered digest"
        )
    lines = raw.decode("utf-8").splitlines()
    header = lines[0].split(",")
    split_index = header.index("split")
    match_index = header.index("match_id")
    by_split: dict[str, set[str]] = {"development": set(), "calibration": set(), "holdout": set()}
    for line in lines[1:]:
        fields = line.split(",")
        split = fields[split_index]
        if split in by_split:
            by_split[split].add(fields[match_index])
    assert_development_only_match_ids(by_split["development"], by_split)
    if by_split["development"] & (by_split["calibration"] | by_split["holdout"]):
        raise DevelopmentOnlyError(
            "registered assignment lock overlaps development and forbidden IDs"
        )


def run_historical_reproduction(
    config: ReleaseConfig,
    canonical: WP24Evidence,
    *,
    root: Path = ROOT,
) -> ReproductionResult:
    """Run the real read-only DB reproduction outside ``poe check``."""
    registration = config.section("reproduction")
    wp24 = config.section("wp24")
    expected = _expected_fingerprint(config)
    reproduction_commit = str(expected["reproduction_commit"])
    worktree: Path | None = None
    temp_root: Path | None = None
    try:
        temp_root = Path(tempfile.mkdtemp(prefix="wp2-8-reproduction-"))
        worktree = temp_root / "checkout"
        _run_checked(
            [
                "git",
                "-C",
                str(root),
                "worktree",
                "add",
                "--detach",
                str(worktree),
                reproduction_commit,
            ],
            cwd=root,
        )
        _assert_historical_development_loader(worktree, config)
        _run_checked(["uv", "sync", "--locked"], cwd=worktree)
        db_env = str(wp24["db_url_env"])
        command = [
            "uv",
            "run",
            "python",
            "-m",
            "touchline.modeling.train",
            "--config",
            str(wp24["config_path"]),
        ]
        env = build_historical_reproduction_environment(dict(os.environ), db_env)
        _run_checked(command, cwd=worktree, env=env)

        generated_metrics_path = _repo_path(worktree, wp24["metrics_path"], "wp24.metrics_path")
        generated_config_path = _repo_path(
            worktree, wp24["resolved_config_path"], "wp24.resolved_config_path"
        )
        generated_manifest_path = _repo_path(
            worktree, wp24["artifact_manifest_path"], "wp24.artifact_manifest_path"
        )
        generated_model_path = _repo_path(worktree, wp24["model_path"], "wp24.model_path")
        generated_metrics = _json_object(generated_metrics_path, "reproduced WP2.4 metrics")
        generated_config = _json_object(generated_config_path, "reproduced WP2.4 config")
        generated_manifest = _json_object(
            generated_manifest_path, "reproduced WP2.4 artifact manifest"
        )
        generated_model_sha = sha256_bytes(generated_model_path.read_bytes())
        actual_fingerprint = _collect_historical_environment_fingerprint(worktree, env=env)
        actual_fingerprint.update(
            {
                "uv_lock_sha256": sha256_bytes((worktree / "uv.lock").read_bytes()),
                "reproduction_commit": reproduction_commit,
                "config_sha256": sha256_bytes(
                    _repo_path(worktree, wp24["config_path"], "wp24.config_path").read_bytes()
                ),
            }
        )
        exact = verify_environment_fingerprint(expected, actual_fingerprint)
        comparison = compare_reproduction(
            {
                "metrics": canonical.metrics,
                "config": canonical.config,
                "artifact_manifest": canonical.artifact_manifest,
            },
            {
                "metrics": generated_metrics,
                "config": generated_config,
                "artifact_manifest": generated_manifest,
            },
            canonical_model_sha256=canonical.model_sha256,
            regenerated_model_sha256=generated_model_sha,
            exact_environment_match=exact,
            numeric_tolerance=float(registration["numeric_tolerance"]),
        )
        if (
            generated_metrics.get("n_rows") != wp24["expected_shots"]
            or generated_metrics.get("n_matches") != wp24["expected_matches"]
        ):
            raise DevelopmentOnlyError(
                "historical reproduction did not meet development row/match anchors"
            )
        return ReproductionResult(
            environment_fingerprint=actual_fingerprint,
            exact_environment_match=exact,
            development_shots=int(cast(Any, generated_metrics["n_rows"])),
            development_matches=int(cast(Any, generated_metrics["n_matches"])),
            development_fold_sizes={
                str(key): int(cast(Any, value))
                for key, value in cast(Mapping[str, object], wp24["expected_fold_sizes"]).items()
            },
            metrics_sha256=sha256_bytes(generated_metrics_path.read_bytes()),
            artifact_manifest_sha256=sha256_bytes(generated_manifest_path.read_bytes()),
            model_sha256=generated_model_sha,
            comparison=comparison,
        )
    finally:
        if worktree is not None:
            subprocess.run(
                ["git", "-C", str(root), "worktree", "remove", "--force", str(worktree)],
                capture_output=True,
                text=True,
                check=False,
            )
        if temp_root is not None and temp_root.exists():
            shutil.rmtree(temp_root, ignore_errors=True)


def _packet_relative(root: Path, final: Path, name: str) -> str:
    return _repo_record_path(root, final / name)


def _notes(config: ReleaseConfig, reproduction: ReproductionResult) -> str:
    return (
        "# WP2.8 reproducible calibrated-model release\n\n"
        "This packet qualifies the frozen WP2.4 full-minus-presence logistic artifact together "
        "with the frozen WP2.7 Platt decision. The reproduction scope is development-only; "
        "WC2022 and Euro2024 rows were not loaded, preprocessed, scored, or passed to the "
        "historical training process.\n\n"
        f"Comparison mode: `{reproduction.comparison.comparison_mode}`.\n"
        f"Exact environment match: `{str(reproduction.exact_environment_match).lower()}`.\n"
        "Serving is intentionally deferred to M3; this packet does not add an API or UI claim.\n"
    )


def _manifest_payload(
    config: ReleaseConfig,
    wp24: WP24Evidence,
    wp27: WP27Evidence,
    reproduction: ReproductionResult,
    *,
    root: Path,
    final: Path,
    file_hashes: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "work_package": "WP2.8",
        "release_id": config.payload["release_id"],
        "release_status": "m2_qualified",
        "serving_status": "not_served",
        "base_commit": REQUIRED_WP27_BASE_COMMIT,
        "reproduction_scope": "development_only",
        "new_holdout_access": False,
        "holdout_rows_loaded": False,
        "authoritative_inputs": {
            "wp24": {
                "config_path": wp24.config_path,
                "config_sha256": wp24.config_sha256,
                "resolved_config_path": wp24.resolved_config_path,
                "resolved_config_sha256": wp24.resolved_config_sha256,
                "metrics_path": wp24.metrics_path,
                "metrics_sha256": wp24.metrics_sha256,
                "artifact_manifest_path": wp24.artifact_manifest_path,
                "artifact_manifest_sha256": wp24.artifact_manifest_sha256,
                "model_path": wp24.model_path,
                "model_sha256": wp24.model_sha256,
            },
            "wp27": {
                "decision_path": wp27.decision_path,
                "decision_file_sha256": wp27.decision_file_sha256,
                "audit_path": wp27.audit_path,
                "audit_file_sha256": wp27.audit_file_sha256,
                "metrics_path": wp27.metrics_path,
                "metrics_file_sha256": wp27.metrics_file_sha256,
                "record_path": wp27.record_path,
                "record_file_sha256": wp27.record_file_sha256,
                "decision_sha256": wp27.decision_sha256,
                "holdout_membership_sha256": wp27.holdout_membership_sha256,
                "execution_provenance_sha256": wp27.execution_provenance_sha256,
                "measured_evidence_sha256": dict(sorted(wp27.measured_evidence_sha256.items())),
            },
        },
        "reproduction": reproduction.as_dict(),
        "packet_files": dict(sorted(file_hashes.items())),
        "presentation_references": list(config.section("wp27")["presentation_paths"]),
        "release_manifest_path": _repo_record_path(root, final / "release-manifest.json"),
    }
    _scan_persisted_strings(payload)
    return payload


def _validate_reproduction_result(config: ReleaseConfig, result: ReproductionResult) -> None:
    if result.new_holdout_access:
        raise ReleaseContractError("WP2.8 reproduction result claims new holdout access")
    registration = config.section("wp24")
    expected_folds = {
        str(key): int(cast(Any, value))
        for key, value in cast(Mapping[str, object], registration["expected_fold_sizes"]).items()
    }
    if (
        result.development_shots != registration["expected_shots"]
        or result.development_matches != registration["expected_matches"]
        or dict(result.development_fold_sizes) != expected_folds
    ):
        raise DevelopmentOnlyError(
            "WP2.8 reproduction result does not meet registered development anchors"
        )
    _digest(result.metrics_sha256, "reproduction metrics digest")
    _digest(result.artifact_manifest_sha256, "reproduction artifact-manifest digest")
    _digest(result.model_sha256, "reproduction model digest")
    if not result.comparison.comparison_table or any(
        row.get("outcome") != "pass" for row in result.comparison.comparison_table
    ):
        raise ReproductionMismatchError(
            "reproduction comparison table is missing or contains a failure"
        )
    observed_exact = verify_environment_fingerprint(
        _expected_fingerprint(config), result.environment_fingerprint
    )
    if observed_exact != result.exact_environment_match:
        raise EnvironmentFingerprintError(
            "reproduction exact-environment flag disagrees with its fingerprint"
        )
    if result.exact_environment_match:
        if result.comparison.comparison_mode != "exact":
            raise ReproductionMismatchError("exact environment must use exact comparison mode")
        if (
            not result.comparison.canonical_json_equal
            or not result.comparison.artifact_byte_identical
        ):
            raise ReproductionMismatchError(
                "exact environment did not prove byte-identical reproduction"
            )
    else:
        if result.comparison.comparison_mode != "numeric_tolerance":
            raise ReproductionMismatchError(
                "non-matching environment must use numeric tolerance mode"
            )
        if result.comparison.canonical_json_equal or result.comparison.artifact_byte_identical:
            raise ReproductionMismatchError("non-matching environment must not claim byte identity")


def _verify_authoritative_manifest_inputs(root: Path, payload: Mapping[str, Any]) -> None:
    authoritative = payload.get("authoritative_inputs")
    if not isinstance(authoritative, Mapping):
        raise ReleaseContractError("release manifest lacks authoritative measured inputs")
    wp24 = authoritative.get("wp24")
    wp27 = authoritative.get("wp27")
    if not isinstance(wp24, Mapping) or not isinstance(wp27, Mapping):
        raise ReleaseContractError("release manifest authoritative input sections are malformed")

    def verify_pair(section: Mapping[str, Any], path_key: str, digest_key: str, label: str) -> None:
        path_name = validate_repo_relative_path(section.get(path_key), f"{label} path")
        digest = _digest(section.get(digest_key), f"{label} digest")
        _verify_file_hash(_repo_path(root, path_name, f"{label} path"), digest, label)

    for path_key, digest_key, label in (
        ("config_path", "config_sha256", "WP2.4 config"),
        ("resolved_config_path", "resolved_config_sha256", "WP2.4 resolved config"),
        ("metrics_path", "metrics_sha256", "WP2.4 metrics"),
        ("artifact_manifest_path", "artifact_manifest_sha256", "WP2.4 artifact manifest"),
        ("model_path", "model_sha256", "WP2.4 model"),
    ):
        verify_pair(wp24, path_key, digest_key, label)
    for path_key, digest_key, label in (
        ("decision_path", "decision_file_sha256", "WP2.7 decision"),
        ("audit_path", "audit_file_sha256", "WP2.7 audit"),
        ("metrics_path", "metrics_file_sha256", "WP2.7 metrics"),
        ("record_path", "record_file_sha256", "WP2.7 experiment record"),
    ):
        verify_pair(wp27, path_key, digest_key, label)
    measured = wp27.get("measured_evidence_sha256")
    if not isinstance(measured, Mapping) or not measured:
        raise ReleaseContractError("release manifest lacks measured WP2.7 evidence hashes")
    for relative, expected in measured.items():
        path_name = validate_repo_relative_path(relative, "measured evidence path")
        _verify_file_hash(
            _repo_path(root, path_name, "measured evidence path"),
            expected,
            f"measured evidence {path_name}",
        )


def verify_release_manifest(
    path: str | Path,
    *,
    root: Path = ROOT,
    staging_root: Path | None = None,
    final_relative_dir: str | None = None,
) -> dict[str, Any]:
    source = Path(path)
    envelope = _json_object(source, "WP2.8 release manifest")
    payload = envelope.get("manifest")
    if not isinstance(payload, Mapping):
        raise ReleaseContractError("WP2.8 release manifest envelope lacks manifest payload")
    expected = _digest(envelope.get("release_manifest_sha256"), "release manifest digest")
    actual = exact_payload_sha256(cast(Mapping[str, object], payload))
    if expected != actual:
        raise ReleaseContractError("WP2.8 release manifest content digest is invalid")
    if (
        payload.get("release_status") != "m2_qualified"
        or payload.get("serving_status") != "not_served"
    ):
        raise ReleaseContractError("WP2.8 release status metadata is invalid")
    if (
        payload.get("reproduction_scope") != "development_only"
        or payload.get("new_holdout_access") is not False
    ):
        raise ReleaseContractError("WP2.8 release does not prove development-only reproduction")
    _scan_persisted_strings(payload)
    _verify_authoritative_manifest_inputs(root, cast(Mapping[str, Any], payload))
    files = payload.get("packet_files")
    if not isinstance(files, Mapping) or not files:
        raise ReleaseContractError("WP2.8 release manifest has no packet file hashes")
    for relative, entry in files.items():
        path_name = validate_repo_relative_path(relative, "packet file path")
        if not isinstance(entry, Mapping):
            raise ReleaseContractError(f"packet file entry is malformed: {path_name}")
        role = entry.get("role", "measured")
        digest = _digest(entry.get("sha256"), f"packet file {path_name}")
        if role == "presentation":
            continue
        if staging_root is None:
            packet_path = _repo_path(root, path_name, "packet file path")
        else:
            if final_relative_dir is None:
                raise ReleaseContractError("staged manifest verification lacks final packet prefix")
            final_prefix = PurePosixPath(
                validate_repo_relative_path(final_relative_dir, "final packet path")
            )
            try:
                staged_name = PurePosixPath(path_name).relative_to(final_prefix)
            except ValueError as exc:
                raise ReleaseContractError(
                    f"staged packet path is outside its final packet directory: {path_name}"
                ) from exc
            packet_path = staging_root.joinpath(*staged_name.parts)
        _verify_file_hash(packet_path, digest, f"packet file {path_name}")
        if PurePosixPath(path_name).name == "comparison.json":
            comparison = _json_object(packet_path, "WP2.8 comparison table")
            table = comparison.get("comparison_table")
            if (
                not isinstance(table, list)
                or not table
                or any(
                    not isinstance(row, Mapping) or row.get("outcome") != "pass" for row in table
                )
            ):
                raise ReleaseContractError(
                    "WP2.8 comparison table is missing or contains a failure"
                )
    return cast(dict[str, Any], payload)


def _ensure_packet_absent(final: Path) -> None:
    if final.exists():
        raise ReleasePublicationError(f"refusing to overwrite existing WP2.8 packet: {final}")


def publish_release_packet(
    config: ReleaseConfig,
    wp24: WP24Evidence,
    wp27: WP27Evidence,
    reproduction: ReproductionResult,
    *,
    root: Path = ROOT,
) -> Path:
    """Stage, verify, and atomically publish a release packet without overwriting one."""
    _validate_reproduction_result(config, reproduction)
    final = _repo_path(root, config.payload["output_dir"], "output_dir")
    _ensure_packet_absent(final)
    final.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{final.name}.staging-", dir=final.parent))
    try:
        config_bytes = config.path.read_bytes()
        (staging / "config.json").write_bytes(config_bytes)
        _write_json(staging / "reproduction.json", reproduction.as_dict())
        _write_json(staging / "comparison.json", reproduction.comparison.as_dict())
        (staging / "notes.md").write_text(
            _notes(config, reproduction), encoding="utf-8", newline="\n"
        )

        packet_files: dict[str, Mapping[str, object]] = {}
        for name in ("config.json", "reproduction.json", "comparison.json", "notes.md"):
            packet_files[_packet_relative(root, final, name)] = {
                "sha256": sha256_bytes((staging / name).read_bytes()),
                "role": "presentation" if name == "notes.md" else "measured",
            }
        manifest_payload = _manifest_payload(
            config,
            wp24,
            wp27,
            reproduction,
            root=root,
            final=final,
            file_hashes=packet_files,
        )
        manifest_envelope = {
            "release_manifest_sha256": exact_payload_sha256(manifest_payload),
            "manifest": manifest_payload,
        }
        _write_json(staging / "release-manifest.json", manifest_envelope)
        # Verify the complete manifest against staging bytes before publication.  The manifest
        # records final repository-relative names, so the resolver strips that final prefix while
        # reading the temporary sibling directory; no staging absolute path is serialized.
        verify_release_manifest(
            staging / "release-manifest.json",
            root=root,
            staging_root=staging,
            final_relative_dir=_repo_record_path(root, final),
        )
        if final.exists():
            raise ReleasePublicationError(f"refusing to overwrite existing WP2.8 packet: {final}")
        try:
            staging.rename(final)
        except OSError as exc:
            raise ReleasePublicationError("atomic WP2.8 packet publication failed") from exc
        return final
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise


def run_release(
    *,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    reproduction_runner: Callable[[ReleaseConfig, WP24Evidence, WP27Evidence], ReproductionResult]
    | None = None,
    root: Path = ROOT,
) -> Path:
    """Run the official release flow; ``reproduction_runner`` is a fixture-only test seam."""
    config = load_release_config(config_path, enforce_registered=reproduction_runner is None)
    if reproduction_runner is None:
        _verify_current_base(root)
        require_clean_tracked_tree(root)
    wp24 = verify_wp24_evidence(config, root=root)
    wp27 = verify_wp27_measured_chain(config, root=root)
    if reproduction_runner is None:
        reproduction = run_historical_reproduction(config, wp24, root=root)
    else:
        reproduction = reproduction_runner(config, wp24, wp27)
    return publish_release_packet(config, wp24, wp27, reproduction, root=root)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="touchline.modeling.wp2_8")
    parser.add_argument("command", choices=("release",))
    parser.parse_args(argv)
    try:
        packet = run_release()
    except (ReleaseContractError, OSError, subprocess.SubprocessError) as exc:
        print(f"WP2.8 release refused: {exc}", file=sys.stderr)
        return 1
    print(f"Published WP2.8 release packet: {_repo_record_path(ROOT, packet)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
