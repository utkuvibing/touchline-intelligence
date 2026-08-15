"""Fail-fast loading and inference for the qualified WP2.8 serving bundle.

``ModelRuntime`` is the single serving seam. It owns package/release verification, frozen
preprocessing, model inference, the adopted Platt transform, curated evidence, and provenance.
FastAPI must not duplicate any of those operations.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, cast

import numpy as np

from touchline.features.geometry import distance_to_goal, visible_goal_angle
from touchline.modeling.artifact import (
    ArtifactBundle,
    ArtifactCompatibilityError,
    load_bundle,
    validate_column_contract,
)
from touchline.modeling.calibration import (
    PlattCalibrator,
    exact_json_bytes,
    load_calibration_decision,
    platt_parameter_digest,
)
from touchline.modeling.preprocessing import (
    CATEGORICAL_FIELDS,
    CONTINUOUS_FIELDS,
    ShotRow,
)

SERVING_RELEASE_ID = "exp-20260810-wp2_8-release"
SERVING_SCHEMA_VERSION = 1
QUALIFIED_RELEASE_CONTENT_SHA256 = (
    "bad64e5972938335e62b98d694f24961117e5f46034518f38b61209e2c3ca87d"
)
QUALIFIED_RELEASE_FILE_SHA256 = "5c2e4016291c6ebe99ba69b37884f38791b4b6b1440c81107ed2a44db95645d4"
SERVING_BUNDLE_DIR = Path(__file__).resolve().parents[2] / "model-release" / SERVING_RELEASE_ID
EXPECTED_FILES = frozenset(
    {
        "artifact-manifest.json",
        "calibration-decision.json",
        "holdout-metrics.json",
        "model.pkl",
        "serving-manifest.json",
        "wp2_8-release-manifest.json",
    }
)
EXPECTED_MEMBER_NAMES = frozenset(
    {
        "release_manifest",
        "model",
        "artifact_manifest",
        "calibration_decision",
        "holdout_metrics",
    }
)
UNSEEN_EXTERNAL_RARE = "__touchline_external_unseen_rare__"


class ServingBundleError(RuntimeError):
    """The immutable serving package cannot initialize a trustworthy runtime."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class ServingInputError(ValueError):
    """A typed request cannot be transformed under the frozen input contract."""

    def __init__(self, code: str, field: str | None, message: str) -> None:
        self.code = code
        self.field = field
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class PredictionInput:
    location_x: float
    location_y: float
    body_part: str
    technique: str
    play_pattern: str


@dataclass(frozen=True, slots=True)
class HistoricalPredictionInput:
    shot_id: str
    match_id: int
    location_x: float
    location_y: float
    body_part: str
    technique: str
    play_pattern: str


@dataclass(frozen=True, slots=True)
class ModelRuntime:
    """One fully validated, immutable model runtime initialized exactly once per application."""

    _bundle: ArtifactBundle
    _calibrator: PlattCalibrator
    _metadata: Mapping[str, object]
    _metrics: Mapping[str, object]

    @classmethod
    def load(cls, bundle_dir: str | Path = SERVING_BUNDLE_DIR) -> ModelRuntime:
        """Validate the complete package before returning any usable runtime.

        Every deterministic package failure raises ``ServingBundleError``. There is no fallback
        artifact and no degraded return value.
        """
        root = Path(bundle_dir)
        if not root.is_dir():
            raise ServingBundleError("serving_bundle_missing", "trusted bundle directory is absent")
        entries = tuple(root.iterdir())
        actual_files = {path.name for path in entries if path.is_file()}
        non_files = {path.name for path in entries if not path.is_file()}
        missing = EXPECTED_FILES - actual_files
        unexpected = (actual_files - EXPECTED_FILES) | non_files
        if missing:
            raise ServingBundleError(
                "serving_bundle_missing",
                f"required members are absent: {', '.join(sorted(missing))}",
            )
        if unexpected:
            raise ServingBundleError(
                "serving_bundle_unexpected_file",
                f"bundle contains files outside the allow-list: {', '.join(sorted(unexpected))}",
            )

        serving_envelope = _read_json_object(
            root / "serving-manifest.json", "release_manifest_invalid"
        )
        serving_payload = _mapping(serving_envelope.get("serving_bundle"), "serving_bundle")
        serving_digest = _digest_payload(serving_payload)
        if serving_envelope.get("serving_manifest_sha256") != serving_digest:
            raise ServingBundleError(
                "serving_bundle_hash_mismatch", "serving manifest content identity is invalid"
            )
        if serving_payload.get("schema_version") != SERVING_SCHEMA_VERSION:
            raise ServingBundleError(
                "release_schema_unsupported",
                f"serving schema {serving_payload.get('schema_version')!r} is unsupported",
            )
        if (
            serving_payload.get("bundle_id") != SERVING_RELEASE_ID
            or serving_payload.get("source_release_id") != SERVING_RELEASE_ID
        ):
            raise ServingBundleError("release_manifest_invalid", "serving release identity changed")

        files = _mapping(serving_payload.get("files"), "serving_bundle.files")
        if frozenset(files) != EXPECTED_MEMBER_NAMES:
            raise ServingBundleError(
                "release_manifest_invalid",
                "serving manifest member roles do not match the contract",
            )
        paths: dict[str, Path] = {}
        member_hashes: dict[str, str] = {}
        for role in sorted(EXPECTED_MEMBER_NAMES):
            member = _mapping(files.get(role), f"serving_bundle.files.{role}")
            relative = _canonical_member_path(member.get("path"), role)
            member_path = root / relative
            expected_hash = _digest(member.get("sha256"), f"serving_bundle.files.{role}.sha256")
            actual_hash = _sha256_file(member_path)
            if actual_hash != expected_hash:
                raise ServingBundleError(
                    "serving_bundle_hash_mismatch", f"{role} does not match its serving hash"
                )
            paths[role] = member_path
            member_hashes[role] = actual_hash

        release_envelope = _read_json_object(paths["release_manifest"], "release_manifest_invalid")
        release_payload = _mapping(release_envelope.get("manifest"), "release manifest payload")
        release_content_hash = _digest_payload(release_payload)
        if release_envelope.get("release_manifest_sha256") != release_content_hash:
            raise ServingBundleError(
                "release_manifest_invalid", "WP2.8 release content identity is invalid"
            )
        if (
            release_content_hash != QUALIFIED_RELEASE_CONTENT_SHA256
            or serving_payload.get("source_release_manifest_sha256") != release_content_hash
        ):
            raise ServingBundleError(
                "release_manifest_invalid", "serving manifest points at another release content"
            )
        if (
            member_hashes["release_manifest"] != QUALIFIED_RELEASE_FILE_SHA256
            or serving_payload.get("source_release_manifest_file_sha256")
            != member_hashes["release_manifest"]
        ):
            raise ServingBundleError(
                "release_manifest_invalid", "serving manifest points at other release bytes"
            )
        _validate_release(release_payload, member_hashes)

        artifact_manifest = _read_json_object(paths["artifact_manifest"], "artifact_incompatible")
        _validate_artifact_manifest(artifact_manifest, member_hashes["model"])
        try:
            artifact = load_bundle(paths["model"])
        except (ArtifactCompatibilityError, OSError, ValueError, TypeError) as exc:
            raise ServingBundleError(
                "artifact_incompatible", "trusted model cannot be loaded under its artifact schema"
            ) from exc
        _validate_artifact(artifact, artifact_manifest)

        try:
            decision = load_calibration_decision(paths["calibration_decision"])
        except (OSError, ValueError) as exc:
            raise ServingBundleError(
                "calibration_decision_invalid", "calibration decision envelope is invalid"
            ) from exc
        calibrator = _validate_calibration(decision.payload, decision.decision_sha256, artifact)

        holdout = _read_json_object(paths["holdout_metrics"], "metrics_evidence_invalid")
        metrics = _curate_metrics(holdout, decision.payload, decision.decision_sha256)
        metadata = _build_metadata(
            serving_digest=serving_digest,
            release_content_hash=release_content_hash,
            release_file_hash=member_hashes["release_manifest"],
            artifact_hash=member_hashes["model"],
            decision_hash=decision.decision_sha256,
            artifact=artifact,
        )
        return cls(
            _bundle=artifact,
            _calibrator=calibrator,
            _metadata=MappingProxyType(metadata),
            _metrics=MappingProxyType(metrics),
        )

    def metadata(self) -> dict[str, object]:
        return _json_copy(self._metadata)

    def metrics(self) -> dict[str, object]:
        return _json_copy(self._metrics)

    def predict(self, value: PredictionInput) -> float:
        row = self._to_shot_row(value, shot_id="request", match_id=0)
        logit = self._bundle.predict_logit([row])
        probability = float(self._calibrator.predict(logit)[0])
        if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
            raise ServingBundleError(
                "artifact_incompatible", "inference produced an invalid calibrated probability"
            )
        return probability

    def predict_historical(self, rows: Sequence[HistoricalPredictionInput]) -> list[float]:
        model_rows = [
            self._to_shot_row(
                PredictionInput(
                    location_x=row.location_x,
                    location_y=row.location_y,
                    body_part=row.body_part,
                    technique=row.technique,
                    play_pattern=row.play_pattern,
                ),
                shot_id=row.shot_id,
                match_id=row.match_id,
            )
            for row in rows
        ]
        if not model_rows:
            return []
        logits = self._bundle.predict_logit(model_rows)
        probabilities = self._calibrator.predict(logits)
        if (
            not np.isfinite(probabilities).all()
            or np.any(probabilities < 0.0)
            or np.any(probabilities > 1.0)
        ):
            raise ServingBundleError(
                "artifact_incompatible", "inference produced invalid calibrated probabilities"
            )
        return [float(value) for value in probabilities]

    def provenance(self) -> dict[str, str]:
        keys = (
            "model_version",
            "release_id",
            "serving_manifest_sha256",
            "release_manifest_sha256",
            "release_manifest_file_sha256",
            "artifact_sha256",
            "calibration_decision_sha256",
        )
        return {key: str(self._metadata[key]) for key in keys}

    def _to_shot_row(self, value: PredictionInput, *, shot_id: str, match_id: int) -> ShotRow:
        x = _coordinate(value.location_x, "location_x", maximum=120.0)
        y = _coordinate(value.location_y, "location_y", maximum=80.0)
        try:
            distance = distance_to_goal(x, y)
            angle = visible_goal_angle(x, y)
        except ValueError as exc:
            raise ServingInputError("input_compatibility_error", None, str(exc)) from exc
        body_part = _category(value.body_part, "body_part")
        technique = _category(value.technique, "technique")
        play_pattern = _category(value.play_pattern, "play_pattern")
        return ShotRow(
            shot_id=shot_id,
            match_id=match_id,
            fold=None,
            competition_id=0,
            season_id=0,
            y=0,
            distance_to_goal=distance,
            visible_goal_angle=angle,
            body_part_name=body_part,
            technique_name=technique,
            play_pattern_name=play_pattern,
            first_time=None,
            under_pressure=None,
        )


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ServingBundleError("release_manifest_invalid", f"{label} must be an object")
    return cast(Mapping[str, Any], value)


def _read_json_object(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ServingBundleError(code, f"{path.name} is not readable canonical JSON") from exc
    if not isinstance(value, dict):
        raise ServingBundleError(code, f"{path.name} must contain one JSON object")
    return cast(dict[str, Any], value)


def _digest_payload(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(exact_json_bytes(dict(payload))).hexdigest()


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ServingBundleError("release_manifest_invalid", f"{label} is not a SHA-256 digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ServingBundleError("release_manifest_invalid", f"{label} is not hexadecimal") from exc
    return value


def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ServingBundleError("serving_bundle_missing", f"cannot read {path.name}") from exc


def _canonical_member_path(value: object, role: str) -> Path:
    if not isinstance(value, str):
        raise ServingBundleError("release_manifest_invalid", f"{role} path must be text")
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or len(pure.parts) != 1
        or pure.name != value
        or value in {"", ".", ".."}
        or "\\" in value
    ):
        raise ServingBundleError("release_manifest_invalid", f"{role} path is not canonical")
    return Path(value)


def _validate_release(payload: Mapping[str, Any], hashes: Mapping[str, str]) -> None:
    if payload.get("schema_version") != 1 or payload.get("release_id") != SERVING_RELEASE_ID:
        raise ServingBundleError(
            "release_schema_unsupported", "WP2.8 release schema/id is unsupported"
        )
    required = {
        "release_status": "m2_qualified",
        "serving_status": "not_served",
        "new_holdout_access": False,
        "holdout_rows_loaded": False,
    }
    if any(payload.get(key) != value for key, value in required.items()):
        raise ServingBundleError("release_manifest_invalid", "WP2.8 release state is incompatible")
    authoritative = _mapping(payload.get("authoritative_inputs"), "authoritative_inputs")
    wp24 = _mapping(authoritative.get("wp24"), "authoritative_inputs.wp24")
    wp27 = _mapping(authoritative.get("wp27"), "authoritative_inputs.wp27")
    expected = {
        "model": wp24.get("model_sha256"),
        "artifact_manifest": wp24.get("artifact_manifest_sha256"),
        "calibration_decision": wp27.get("decision_file_sha256"),
        "holdout_metrics": wp27.get("metrics_file_sha256"),
    }
    for role, expected_hash in expected.items():
        if expected_hash != hashes[role]:
            raise ServingBundleError(
                "release_manifest_invalid", f"{role} is not the WP2.8 authoritative input"
            )


def _validate_artifact_manifest(payload: Mapping[str, Any], model_hash: str) -> None:
    required = {
        "artifact_schema_version": 1,
        "experiment_id": "exp-20260805-wp2_4-baselines",
        "shipped_candidate": "full_minus_presence",
        "shipped_feature_set": "geometry+categoricals",
        "d5_include": False,
        "model_pickle_sha256": model_hash,
    }
    if any(payload.get(key) != value for key, value in required.items()):
        raise ServingBundleError(
            "artifact_incompatible", "artifact manifest identity is incompatible"
        )


def _validate_artifact(bundle: ArtifactBundle, manifest: Mapping[str, Any]) -> None:
    if bundle.shipped_candidate != "full_minus_presence":
        raise ServingBundleError("artifact_incompatible", "artifact contains another candidate")
    if manifest.get("shipped_feature_columns") != list(bundle.selected_columns):
        raise ServingBundleError(
            "preprocessing_contract_invalid", "selected feature columns changed"
        )
    if tuple(bundle.vocabulary.fields) != CATEGORICAL_FIELDS:
        raise ServingBundleError(
            "preprocessing_contract_invalid", "categorical field order changed"
        )
    if set(bundle.scaler.mean) != set(CONTINUOUS_FIELDS) or set(bundle.scaler.std) != set(
        CONTINUOUS_FIELDS
    ):
        raise ServingBundleError("preprocessing_contract_invalid", "scaler fields changed")
    if any(
        not math.isfinite(float(bundle.scaler.mean[field]))
        or not math.isfinite(float(bundle.scaler.std[field]))
        or float(bundle.scaler.std[field]) <= 0.0
        for field in CONTINUOUS_FIELDS
    ):
        raise ServingBundleError("preprocessing_contract_invalid", "scaler state is invalid")
    try:
        validate_column_contract(
            all_columns=bundle.all_columns,
            selected_columns=bundle.selected_columns,
            selected_indices=bundle.selected_indices,
            current_columns=bundle.vocabulary.column_names(),
            n_features_in=int(bundle.estimator.n_features_in_),
        )
    except ArtifactCompatibilityError as exc:
        raise ServingBundleError("preprocessing_contract_invalid", str(exc)) from exc
    arrays = (bundle.estimator.coef_, bundle.estimator.intercept_)
    if not all(np.isfinite(array).all() for array in arrays):
        raise ServingBundleError("artifact_incompatible", "estimator state is non-finite")


def _validate_calibration(
    payload: Mapping[str, Any], decision_hash: str, artifact: ArtifactBundle
) -> PlattCalibrator:
    if payload.get("schema_version") != 1 or payload.get("adopted_variant") != "calibrated":
        raise ServingBundleError(
            "calibration_decision_invalid", "adopted calibration is incompatible"
        )
    base = _mapping(payload.get("base_identity"), "calibration base identity")
    if (
        base.get("model_pickle_sha256")
        != "9aeac9468c00bd1b93c771e454e48ca29e2eb759cf71836182a782d674bfadca"
        or base.get("experiment_id") != artifact.experiment_id
        or base.get("candidate") != artifact.shipped_candidate
    ):
        raise ServingBundleError(
            "calibration_decision_invalid", "calibration base identity changed"
        )
    try:
        slope = float(payload["platt_slope"])
        intercept = float(payload["platt_intercept"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ServingBundleError(
            "calibration_decision_invalid", "Platt parameters are missing"
        ) from exc
    if not math.isfinite(slope) or slope <= 0.0 or not math.isfinite(intercept):
        raise ServingBundleError("calibration_decision_invalid", "Platt parameters are invalid")
    if payload.get("platt_parameter_sha256") != platt_parameter_digest(slope, intercept):
        raise ServingBundleError("calibration_decision_invalid", "Platt parameter digest changed")
    if decision_hash != ("f5c9ccf665924069f755fbd669d4a9abada1e5791e957d3d436d42d500277e89"):
        raise ServingBundleError("calibration_decision_invalid", "decision identity is unqualified")
    return PlattCalibrator(slope=slope, intercept=intercept)


def _curate_metrics(
    holdout: Mapping[str, Any], decision: Mapping[str, Any], decision_hash: str
) -> dict[str, object]:
    if (
        holdout.get("schema_version") != 1
        or holdout.get("candidate") != "full_minus_presence"
        or holdout.get("adopted_variant") != "calibrated"
        or holdout.get("decision_sha256") != decision_hash
        or holdout.get("n_rows") != 1304
        or holdout.get("n_matches") != 51
    ):
        raise ServingBundleError("metrics_evidence_invalid", "holdout aggregate identity changed")
    variants = _mapping(holdout.get("variants"), "holdout variants")
    raw = _mapping(variants.get("raw"), "raw holdout variant")
    calibrated = _mapping(variants.get("calibrated"), "calibrated holdout variant")
    for name, variant in (("raw", raw), ("calibrated", calibrated)):
        reliability = variant.get("reliability")
        if (
            variant.get("n") != 1304
            or not isinstance(reliability, list)
            or sum(int(_mapping(row, "reliability row").get("count", -1)) for row in reliability)
            != 1304
        ):
            raise ServingBundleError(
                "metrics_evidence_invalid", f"{name} holdout reliability membership changed"
            )
    adoption = _mapping(decision.get("adoption"), "calibration adoption")
    membership = _mapping(decision.get("calibration_membership"), "calibration membership")
    if membership.get("n_rows") != 1430 or membership.get("n_matches") != 64:
        raise ServingBundleError("metrics_evidence_invalid", "calibration membership changed")
    bootstrap = _mapping(holdout.get("bootstrap"), "holdout bootstrap")
    effect = _mapping(holdout.get("holdout_raw_vs_calibrated_effect"), "holdout effect")
    cal_boot = _mapping(bootstrap.get("calibrated"), "calibrated bootstrap")
    effect_boot = _mapping(bootstrap.get("effect_calibrated_minus_raw"), "effect bootstrap")
    return {
        "evidence_source": {
            "holdout_metrics_sha256": (
                "3443b4a5e19fd87b1ee599502152a7dcfe1af3d8466c09ad7cbf2bb8cae2e674"
            ),
            "evidence_status": "qualified_m2_evidence",
            "recomputed_at_request_time": False,
        },
        "calibration_adoption": {
            "split": "FIFA World Cup 2022",
            "role": "calibration",
            "shots": 1430,
            "matches": 64,
            "adopted_variant": "calibrated",
            "supported_raw_anchor_bins": adoption.get("supported_bins"),
            "raw": {
                "log_loss": adoption.get("raw_log_loss"),
                "brier": adoption.get("raw_brier"),
                "max_supported_calibration_deviation": adoption.get(
                    "raw_max_abs_deviation_supported"
                ),
            },
            "calibrated": {
                "log_loss": adoption.get("calibrated_log_loss"),
                "brier": adoption.get("calibrated_brier"),
                "max_supported_calibration_deviation": adoption.get(
                    "calibrated_max_abs_deviation_supported"
                ),
            },
            "raw_anchor_reliability": adoption.get("raw_anchor_reliability"),
        },
        "tournament_holdout": {
            "split": "UEFA Euro 2024",
            "role": "one_time_tournament_holdout",
            "shots": 1304,
            "matches": 51,
            "goals": 98,
            "observed_prevalence": holdout.get("observed_prevalence"),
            "adopted_variant": "calibrated",
            "proper_scoring": {
                "log_loss": calibrated.get("log_loss"),
                "brier": calibrated.get("brier"),
            },
            "discrimination": {
                "roc_auc": calibrated.get("roc_auc"),
                "pr_auc": calibrated.get("pr_auc"),
            },
            "uncertainty": {
                "method": "match_clustered_paired_bootstrap",
                "confidence_level": bootstrap.get("confidence_level"),
                "repetitions": bootstrap.get("repetitions"),
                "seed": bootstrap.get("seed"),
                "log_loss": cal_boot.get("log_loss"),
                "brier": cal_boot.get("brier"),
            },
            "reliability": calibrated.get("reliability"),
            "raw_comparator": {
                "proper_scoring": {
                    "log_loss": raw.get("log_loss"),
                    "brier": raw.get("brier"),
                },
                "discrimination": {
                    "roc_auc": raw.get("roc_auc"),
                    "pr_auc": raw.get("pr_auc"),
                },
                "calibrated_minus_raw": {
                    "log_loss": effect.get("log_loss"),
                    "brier": effect.get("brier"),
                    "log_loss_interval": effect_boot.get("log_loss"),
                    "brier_interval": effect_boot.get("brier"),
                },
            },
        },
    }


def _build_metadata(
    *,
    serving_digest: str,
    release_content_hash: str,
    release_file_hash: str,
    artifact_hash: str,
    decision_hash: str,
    artifact: ArtifactBundle,
) -> dict[str, object]:
    vocabulary = artifact.vocabulary
    return {
        "model_version": SERVING_RELEASE_ID,
        "release_id": SERVING_RELEASE_ID,
        "serving_manifest_sha256": serving_digest,
        "release_manifest_sha256": release_content_hash,
        "release_manifest_file_sha256": release_file_hash,
        "artifact_sha256": artifact_hash,
        "calibration_decision_sha256": decision_hash,
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
                    "reference": vocabulary.reference["body_part_name"],
                    "retained": ["Head", "Left Foot"],
                    "rare_members": list(vocabulary.rare_members["body_part_name"]),
                },
                "technique": {
                    "reference": vocabulary.reference["technique_name"],
                    "retained": ["Half Volley", "Volley"],
                    "rare_members": list(vocabulary.rare_members["technique_name"]),
                },
                "play_pattern": {
                    "reference": vocabulary.reference["play_pattern_name"],
                    "retained": [
                        "From Corner",
                        "From Counter",
                        "From Free Kick",
                        "From Goal Kick",
                        "From Keeper",
                        "From Kick Off",
                        "From Throw In",
                    ],
                    "rare_members": list(vocabulary.rare_members["play_pattern_name"]),
                },
            },
        },
    }


def _coordinate(value: float, field: str, *, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ServingInputError("request_validation_error", field, f"{field} must be a JSON number")
    number = float(value)
    if not math.isfinite(number):
        raise ServingInputError("request_validation_error", field, f"{field} must be finite")
    if not 0.0 <= number <= maximum:
        raise ServingInputError(
            "request_validation_error", field, f"{field} must be inside [0.0, {maximum}]"
        )
    return number


def _category(value: str, field: str) -> str:
    if not isinstance(value, str) or not value or not value.strip():
        raise ServingInputError(
            "request_validation_error", field, f"{field} must be a non-empty exact string"
        )
    # ``rare`` is an encoder column label, but frozen M2 evidence does not prove it is reserved in
    # external input. The approved M3 contract therefore treats the literal as unseen/reference.
    return UNSEEN_EXTERNAL_RARE if value == "rare" else value


def _json_copy(value: Mapping[str, object]) -> dict[str, object]:
    return cast(dict[str, object], json.loads(json.dumps(dict(value), allow_nan=False)))
