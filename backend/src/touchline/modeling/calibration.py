"""WP2.7 calibration contract and frozen-base identity.

This module deliberately contains no database access.  A caller must freeze and verify the
selected all-development artifact before it supplies calibration rows.  Calibration can then fit
only the one-dimensional Platt transform; the estimator and its preprocessing are inference-only.
"""

from __future__ import annotations

import hashlib
import json
import math
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
import numpy.typing as npt
from scipy.special import expit  # type: ignore[import-untyped]
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]

from touchline.modeling.artifact import ArtifactBundle, artifact_schema_version, load_bundle
from touchline.modeling.experiment import abs_path, record_path
from touchline.modeling.metrics import (
    brier_score,
    log_loss,
    reliability_table,
)
from touchline.modeling.preprocessing import ShotRow
from touchline.modeling.protocol import D11_MIN_SUPPORT

__all__ = [
    "ADOPTION_TOLERANCE",
    "CALIBRATION_RULE_VERSION",
    "D11_MIN_SUPPORT",
    "BaseModelIdentity",
    "BaseModelPins",
    "CalibrationContractError",
    "CalibrationDecision",
    "CalibrationDecisionError",
    "FrozenBaseModel",
    "PlattCalibrator",
    "assert_frozen_base_unchanged",
    "decide_calibration_adoption",
    "exact_json_bytes",
    "exact_payload_sha256",
    "fit_platt",
    "freeze_base_model",
    "load_calibration_decision",
    "paired_raw_anchor_reliability",
    "platt_parameter_digest",
    "verify_calibration_decision",
    "write_calibration_decision",
]

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int_]

CALIBRATION_RULE_VERSION = "wp2.7-calibration-adoption-v1"
ADOPTION_TOLERANCE = 1e-12
N_RELIABILITY_BINS = 5
RAW_ANCHOR_BIN_EDGES: tuple[float, ...] = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)


class CalibrationContractError(ValueError):
    """A calibration or frozen-base contract was violated."""


class CalibrationDecisionError(CalibrationContractError):
    """A calibration decision is missing, corrupted, or being overwritten."""


@dataclass(frozen=True)
class BaseModelPins:
    """Externally registered identity of the one WP2.4 artifact WP2.7 may consume."""

    artifact_path: str
    artifact_manifest_path: str
    artifact_schema_version: int
    model_pickle_sha256: str
    artifact_manifest_sha256: str
    experiment_id: str
    candidate: str
    shipped_feature_set: str
    best_c: float
    data_source_commit: str
    cohort_sql_sha256: str
    assignments_sha256: str
    code_commit: str
    reproduction_commit: str
    input_config_sha256: str
    uv_lock_sha256: str

    def __post_init__(self) -> None:
        for field_name in (
            "model_pickle_sha256",
            "artifact_manifest_sha256",
            "cohort_sql_sha256",
            "assignments_sha256",
            "input_config_sha256",
            "uv_lock_sha256",
        ):
            _require_digest(getattr(self, field_name), f"frozen_base.{field_name}")
        if self.candidate != "full_minus_presence":
            raise CalibrationContractError(
                "WP2.7 external pins must name the selected full_minus_presence base"
            )
        if self.shipped_feature_set != "geometry+categoricals":
            raise CalibrationContractError(
                "WP2.7 external pins must name the selected geometry+categoricals feature set"
            )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> BaseModelPins:
        try:
            return cls(
                artifact_path=str(payload["artifact_path"]),
                artifact_manifest_path=str(payload["artifact_manifest_path"]),
                artifact_schema_version=int(cast(int, payload["artifact_schema_version"])),
                model_pickle_sha256=str(payload["model_pickle_sha256"]),
                artifact_manifest_sha256=str(payload["artifact_manifest_sha256"]),
                experiment_id=str(payload["experiment_id"]),
                candidate=str(payload["candidate"]),
                shipped_feature_set=str(payload["shipped_feature_set"]),
                best_c=float(cast(float, payload["best_c"])),
                data_source_commit=str(payload["data_source_commit"]),
                cohort_sql_sha256=str(payload["cohort_sql_sha256"]),
                assignments_sha256=str(payload["assignments_sha256"]),
                code_commit=str(payload["code_commit"]),
                reproduction_commit=str(payload["reproduction_commit"]),
                input_config_sha256=str(payload["input_config_sha256"]),
                uv_lock_sha256=str(payload["uv_lock_sha256"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CalibrationContractError("frozen_base registration is incomplete") from exc

    def as_dict(self) -> dict[str, object]:
        return {
            "artifact_path": self.artifact_path,
            "artifact_manifest_path": self.artifact_manifest_path,
            "artifact_schema_version": self.artifact_schema_version,
            "model_pickle_sha256": self.model_pickle_sha256,
            "artifact_manifest_sha256": self.artifact_manifest_sha256,
            "experiment_id": self.experiment_id,
            "candidate": self.candidate,
            "shipped_feature_set": self.shipped_feature_set,
            "best_c": self.best_c,
            "data_source_commit": self.data_source_commit,
            "cohort_sql_sha256": self.cohort_sql_sha256,
            "assignments_sha256": self.assignments_sha256,
            "code_commit": self.code_commit,
            "reproduction_commit": self.reproduction_commit,
            "input_config_sha256": self.input_config_sha256,
            "uv_lock_sha256": self.uv_lock_sha256,
        }


def _canonical_digest(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical_exact_json(payload)).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise CalibrationContractError(f"{label} must be a 64-character SHA-256 digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise CalibrationContractError(f"{label} is not a hexadecimal SHA-256 digest") from exc
    return value


def _jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return [_jsonable(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        return _jsonable(value.item())
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _canonical_exact_json(payload: Mapping[str, object]) -> bytes:
    """Canonical JSON that preserves every finite binary64 value on round trip.

    WP2.4's metrics serializer intentionally rounds display values to twelve decimal places. A
    calibration decision is identity material, so it instead relies on Python's shortest exact
    float representation and rejects non-finite values.
    """
    encoded = json.dumps(
        _jsonable(payload),
        sort_keys=True,
        indent=2,
        separators=(",", ": "),
        ensure_ascii=True,
        allow_nan=False,
    )
    return (encoded + "\n").encode("utf-8")


def exact_json_bytes(payload: Mapping[str, object]) -> bytes:
    """Public exact canonical serializer for WP2.7 identity and audit material."""
    return _canonical_exact_json(payload)


def exact_payload_sha256(payload: Mapping[str, object]) -> str:
    """Hash WP2.7 identity material without display-metric rounding."""
    return _canonical_digest(payload)


def _estimator_state_payload(bundle: ArtifactBundle) -> dict[str, object]:
    estimator = bundle.estimator
    return {
        "class": f"{type(estimator).__module__}.{type(estimator).__qualname__}",
        "params": _jsonable(estimator.get_params(deep=False)),
        "classes": _jsonable(estimator.classes_),
        "coef": _jsonable(estimator.coef_),
        "intercept": _jsonable(estimator.intercept_),
        "n_iter": _jsonable(estimator.n_iter_),
    }


def _preprocessing_payload(bundle: ArtifactBundle) -> dict[str, object]:
    return {
        "scaler": bundle.scaler.as_dict(),
        "vocabulary": bundle.vocabulary.as_dict(),
        "reference_levels": dict(bundle.reference_levels),
        "rare_mapping": {key: list(value) for key, value in bundle.rare_mapping.items()},
        "all_columns": list(bundle.all_columns),
        "selected_columns": list(bundle.selected_columns),
        "selected_indices": list(bundle.selected_indices),
    }


def _feature_contract_payload(bundle: ArtifactBundle) -> dict[str, object]:
    return {
        "artifact_schema_version": bundle.schema_version,
        "all_columns": list(bundle.all_columns),
        "selected_columns": list(bundle.selected_columns),
        "selected_indices": list(bundle.selected_indices),
        "n_features_in": int(bundle.estimator.n_features_in_),
    }


@dataclass(frozen=True)
class BaseModelIdentity:
    """The identity that must remain unchanged from calibration through holdout scoring."""

    candidate: str
    experiment_id: str
    base_fit_scope: str
    preprocessing_fit_scope: str
    artifact_path: str
    artifact_manifest_path: str
    artifact_schema_version: int
    model_pickle_sha256: str
    artifact_manifest_sha256: str
    estimator_state_sha256: str
    preprocessing_sha256: str
    feature_contract_sha256: str
    data_source_commit: str
    cohort_sql_sha256: str
    assignments_sha256: str
    code_commit: str
    reproduction_commit: str
    input_config_sha256: str
    uv_lock_sha256: str

    @classmethod
    def synthetic(cls) -> BaseModelIdentity:
        """Stable identity for metadata-only tests; never used by a real phase runner."""
        digest = "0" * 64
        return cls(
            candidate="full_minus_presence",
            experiment_id="synthetic-wp27",
            base_fit_scope="development_only",
            preprocessing_fit_scope="development_only",
            artifact_path="artifacts/models/synthetic/model.pkl",
            artifact_manifest_path="experiments/synthetic/artifact-manifest.json",
            artifact_schema_version=artifact_schema_version,
            model_pickle_sha256=digest,
            artifact_manifest_sha256=digest,
            estimator_state_sha256=digest,
            preprocessing_sha256=digest,
            feature_contract_sha256=digest,
            data_source_commit="synthetic-data",
            cohort_sql_sha256=digest,
            assignments_sha256=digest,
            code_commit="synthetic-code",
            reproduction_commit="synthetic-code",
            input_config_sha256=digest,
            uv_lock_sha256=digest,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate": self.candidate,
            "experiment_id": self.experiment_id,
            "base_fit_scope": self.base_fit_scope,
            "preprocessing_fit_scope": self.preprocessing_fit_scope,
            "artifact_path": self.artifact_path,
            "artifact_manifest_path": self.artifact_manifest_path,
            "artifact_schema_version": self.artifact_schema_version,
            "model_pickle_sha256": self.model_pickle_sha256,
            "artifact_manifest_sha256": self.artifact_manifest_sha256,
            "estimator_state_sha256": self.estimator_state_sha256,
            "preprocessing_sha256": self.preprocessing_sha256,
            "feature_contract_sha256": self.feature_contract_sha256,
            "data_source_commit": self.data_source_commit,
            "cohort_sql_sha256": self.cohort_sql_sha256,
            "assignments_sha256": self.assignments_sha256,
            "code_commit": self.code_commit,
            "reproduction_commit": self.reproduction_commit,
            "input_config_sha256": self.input_config_sha256,
            "uv_lock_sha256": self.uv_lock_sha256,
        }


@dataclass(frozen=True)
class FrozenBaseModel:
    """A verified artifact with inference-only access to its base logits."""

    bundle: ArtifactBundle
    identity: BaseModelIdentity

    def predict_logits(self, rows: Sequence[ShotRow]) -> FloatArray:
        return self.bundle.predict_logit(rows)


def _identity_from_bundle(
    bundle: ArtifactBundle,
    *,
    artifact_path: Path,
    manifest_path: Path,
    manifest_bytes: bytes,
) -> BaseModelIdentity:
    preprocessing = _preprocessing_payload(bundle)
    contract = _feature_contract_payload(bundle)
    return BaseModelIdentity(
        candidate=bundle.shipped_candidate,
        experiment_id=bundle.experiment_id,
        base_fit_scope="development_only",
        preprocessing_fit_scope="development_only",
        artifact_path=record_path(artifact_path),
        artifact_manifest_path=record_path(manifest_path),
        artifact_schema_version=bundle.schema_version,
        model_pickle_sha256=_sha256_bytes(artifact_path.read_bytes()),
        artifact_manifest_sha256=_sha256_bytes(manifest_bytes),
        estimator_state_sha256=_canonical_digest(_estimator_state_payload(bundle)),
        preprocessing_sha256=_canonical_digest(preprocessing),
        feature_contract_sha256=_canonical_digest(contract),
        data_source_commit=bundle.data_source_commit,
        cohort_sql_sha256=bundle.cohort_sql_sha256,
        assignments_sha256=bundle.assignments_sha256,
        code_commit=bundle.code_commit,
        reproduction_commit=bundle.reproduction_commit,
        input_config_sha256=bundle.input_config_sha256,
        uv_lock_sha256=bundle.uv_lock_sha256,
    )


def freeze_base_model(pins: BaseModelPins) -> FrozenBaseModel:
    """Verify the selected base against external WP2.7 pins before any data access."""
    artifact = abs_path(pins.artifact_path)
    manifest = abs_path(pins.artifact_manifest_path)
    if not artifact.is_file() or not manifest.is_file():
        raise CalibrationContractError("the frozen base artifact and manifest must both exist")
    actual_model_hash = _sha256_bytes(artifact.read_bytes())
    actual_manifest_hash = _sha256_bytes(manifest.read_bytes())
    if actual_model_hash != pins.model_pickle_sha256:
        raise CalibrationContractError(
            "base artifact does not match the externally pinned model SHA-256: "
            f"{actual_model_hash} != {pins.model_pickle_sha256}"
        )
    if actual_manifest_hash != pins.artifact_manifest_sha256:
        raise CalibrationContractError(
            "base manifest does not match the externally pinned manifest SHA-256: "
            f"{actual_manifest_hash} != {pins.artifact_manifest_sha256}"
        )
    manifest_bytes = manifest.read_bytes()
    try:
        payload = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CalibrationContractError(
            f"base artifact manifest is not valid JSON: {manifest}"
        ) from exc
    if not isinstance(payload, dict):
        raise CalibrationContractError("base artifact manifest must be a JSON object")
    if payload.get("shipped_candidate") != "full_minus_presence":
        raise CalibrationContractError(
            "WP2.7 requires the selected full_minus_presence logistic artifact; refusing fallback"
        )
    if payload.get("shipped_feature_set") != "geometry+categoricals":
        raise CalibrationContractError(
            "WP2.7 base artifact does not match the selected geometry+categoricals feature set"
        )
    if payload.get("d5_include") is not False:
        raise CalibrationContractError(
            "WP2.7 requires the already-selected full_minus_presence candidate; "
            "refusing a D5-inclusive artifact"
        )
    expected_path = str(payload.get("model_pickle_path", ""))
    if expected_path != record_path(artifact):
        raise CalibrationContractError(
            f"manifest model path {expected_path!r} does not match {record_path(artifact)!r}"
        )
    expected_model_hash = _require_digest(payload.get("model_pickle_sha256"), "model_pickle_sha256")
    actual_hash = actual_model_hash
    if expected_model_hash != actual_hash:
        raise CalibrationContractError(
            f"base artifact SHA-256 is {actual_hash}, expected {payload.get('model_pickle_sha256')}"
        )
    input_config_path = payload.get("input_config_path")
    input_config_hash = _require_digest(payload.get("input_config_sha256"), "input_config_sha256")
    if not isinstance(input_config_path, str) or not input_config_path:
        raise CalibrationContractError("base manifest does not identify its input configuration")
    config_path = abs_path(input_config_path)
    if not config_path.is_file():
        raise CalibrationContractError(f"base input configuration is missing: {config_path}")
    actual_config_hash = _sha256_bytes(config_path.read_bytes())
    if actual_config_hash != input_config_hash:
        raise CalibrationContractError(
            "base input configuration SHA-256 is "
            f"{actual_config_hash}, expected {input_config_hash}"
        )
    bundle = load_bundle(artifact)
    if bundle.shipped_candidate != "full_minus_presence":
        raise CalibrationContractError("loaded base bundle is not full_minus_presence")
    if int(payload.get("artifact_schema_version", -1)) != bundle.schema_version:
        raise CalibrationContractError("base manifest and bundle schema versions disagree")
    for field in (
        "experiment_id",
        "code_commit",
        "reproduction_commit",
        "data_source_commit",
        "input_config_sha256",
        "uv_lock_sha256",
        "shipped_candidate",
    ):
        manifest_value = payload.get(field)
        bundle_value = getattr(bundle, field)
        if manifest_value != bundle_value:
            raise CalibrationContractError(
                f"base manifest field {field!r} does not match the serialized bundle"
            )
    for field in ("cohort_sql_sha256", "assignments_sha256", "uv_lock_sha256"):
        _require_digest(getattr(bundle, field), f"bundle.{field}")
    shipped_columns = payload.get("shipped_feature_columns")
    if shipped_columns != list(bundle.selected_columns):
        raise CalibrationContractError(
            "base manifest shipped_feature_columns do not match the serialized feature contract"
        )
    if float(payload.get("shipped_best_c", float("nan"))) != bundle.best_c:
        raise CalibrationContractError(
            "base manifest selected C does not match the serialized bundle"
        )
    registered_fields = {
        "artifact_schema_version": pins.artifact_schema_version,
        "experiment_id": pins.experiment_id,
        "candidate": pins.candidate,
        "shipped_feature_set": pins.shipped_feature_set,
        "best_c": pins.best_c,
        "data_source_commit": pins.data_source_commit,
        "cohort_sql_sha256": pins.cohort_sql_sha256,
        "assignments_sha256": pins.assignments_sha256,
        "code_commit": pins.code_commit,
        "reproduction_commit": pins.reproduction_commit,
        "input_config_sha256": pins.input_config_sha256,
        "uv_lock_sha256": pins.uv_lock_sha256,
    }
    artifact_fields = {
        "artifact_schema_version": bundle.schema_version,
        "experiment_id": bundle.experiment_id,
        "candidate": bundle.shipped_candidate,
        "shipped_feature_set": payload.get("shipped_feature_set"),
        "best_c": bundle.best_c,
        "data_source_commit": bundle.data_source_commit,
        "cohort_sql_sha256": bundle.cohort_sql_sha256,
        "assignments_sha256": bundle.assignments_sha256,
        "code_commit": bundle.code_commit,
        "reproduction_commit": bundle.reproduction_commit,
        "input_config_sha256": bundle.input_config_sha256,
        "uv_lock_sha256": bundle.uv_lock_sha256,
    }
    if artifact_fields != registered_fields:
        raise CalibrationContractError(
            "base artifact identity does not match the externally pinned WP2.7 registration"
        )
    identity = _identity_from_bundle(
        bundle,
        artifact_path=artifact,
        manifest_path=manifest,
        manifest_bytes=manifest_bytes,
    )
    return FrozenBaseModel(bundle=bundle, identity=identity)


def assert_frozen_base_unchanged(frozen: FrozenBaseModel) -> None:
    """Fail if an inference phase mutated the estimator or preprocessing in memory."""
    current = _identity_from_bundle(
        frozen.bundle,
        artifact_path=abs_path(frozen.identity.artifact_path),
        manifest_path=abs_path(frozen.identity.artifact_manifest_path),
        manifest_bytes=abs_path(frozen.identity.artifact_manifest_path).read_bytes(),
    )
    if current != frozen.identity:
        raise CalibrationContractError(
            "base estimator or preprocessing identity changed after the frozen-base checkpoint"
        )


@dataclass(frozen=True)
class PlattCalibrator:
    """A frozen sigmoid over base logits, fitted on WC2022 only."""

    slope: float
    intercept: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.slope) or not math.isfinite(self.intercept):
            raise CalibrationContractError("Platt parameters must be finite")
        object.__setattr__(self, "slope", float(self.slope))
        object.__setattr__(self, "intercept", float(self.intercept))

    def predict(self, logits: Sequence[float] | FloatArray) -> FloatArray:
        values = np.asarray(logits, dtype=np.float64)
        if values.ndim != 1 or not np.isfinite(values).all():
            raise CalibrationContractError("Platt logits must be a finite one-dimensional array")
        return np.asarray(expit(self.slope * values + self.intercept), dtype=np.float64)

    def as_dict(self) -> dict[str, object]:
        return {"method": "platt_sigmoid", "slope": self.slope, "intercept": self.intercept}


def fit_platt(
    logits: Sequence[float] | FloatArray, y_true: Sequence[int] | IntArray
) -> PlattCalibrator:
    """Fit only the Platt parameters; no base estimator or preprocessing is fitted here."""
    x = np.asarray(logits, dtype=np.float64)
    y = np.asarray(y_true, dtype=np.int_)
    if x.ndim != 1 or y.ndim != 1 or x.shape != y.shape:
        raise CalibrationContractError(
            "Platt logits and labels must be matching one-dimensional arrays"
        )
    if x.size == 0 or not np.isfinite(x).all() or not set(np.unique(y)).issubset({0, 1}):
        raise CalibrationContractError("Platt inputs must be non-empty, finite, binary data")
    if np.unique(y).size != 2:
        raise CalibrationContractError("Platt fitting requires both calibration label classes")
    estimator = LogisticRegression(
        solver="lbfgs",
        C=np.inf,
        max_iter=100_000,
        tol=1e-12,
        random_state=0,
    )
    try:
        estimator.fit(x.reshape(-1, 1), y)
    except ValueError as exc:
        raise CalibrationContractError(f"Platt fitting failed: {exc}") from exc
    return PlattCalibrator(float(estimator.coef_[0, 0]), float(estimator.intercept_[0]))


def platt_parameter_digest(slope: float, intercept: float) -> str:
    """Return the canonical digest recorded beside the immutable Platt parameters."""
    return _canonical_digest(
        {"method": "platt_sigmoid", "slope": float(slope), "intercept": float(intercept)}
    )


def _arrays(
    y_true: Sequence[int] | IntArray,
    raw: Sequence[float] | FloatArray,
    calibrated: Sequence[float] | FloatArray,
) -> tuple[IntArray, FloatArray, FloatArray]:
    y = np.asarray(y_true, dtype=np.int_)
    raw_values = np.asarray(raw, dtype=np.float64)
    calibrated_values = np.asarray(calibrated, dtype=np.float64)
    if y.ndim != 1 or raw_values.ndim != 1 or calibrated_values.ndim != 1:
        raise CalibrationContractError("calibration arrays must be one-dimensional")
    if not (y.shape == raw_values.shape == calibrated_values.shape):
        raise CalibrationContractError("calibration arrays must have identical row membership")
    if not np.isfinite(raw_values).all() or not np.isfinite(calibrated_values).all():
        raise CalibrationContractError("calibration probabilities must be finite")
    if (
        np.any(raw_values < 0.0)
        or np.any(raw_values > 1.0)
        or np.any(calibrated_values < 0.0)
        or np.any(calibrated_values > 1.0)
    ):
        raise CalibrationContractError("calibration probabilities must lie in [0, 1]")
    return y, raw_values, calibrated_values


def _raw_anchor_bin(value: float) -> int:
    return min(
        bisect_right(RAW_ANCHOR_BIN_EDGES, value) - 1,
        N_RELIABILITY_BINS - 1,
    )


def paired_raw_anchor_reliability(
    y_true: Sequence[int] | IntArray,
    raw: Sequence[float] | FloatArray,
    calibrated: Sequence[float] | FloatArray,
) -> list[dict[str, object]]:
    """Evaluate both variants on the exact groups assigned by raw probabilities."""
    y, raw_values, calibrated_values = _arrays(y_true, raw, calibrated)
    group_ids = np.asarray([_raw_anchor_bin(float(value)) for value in raw_values], dtype=np.int_)
    entries: list[dict[str, object]] = []
    width = 1.0 / N_RELIABILITY_BINS
    for index in range(N_RELIABILITY_BINS):
        mask = group_ids == index
        count = int(mask.sum())
        entries.append(
            {
                "bin": index,
                "lower": round(index * width, 12),
                "upper": round((index + 1) * width, 12) if index < N_RELIABILITY_BINS - 1 else 1.0,
                "count": count,
                "positive_count": int(y[mask].sum()) if count else 0,
                "raw_mean_prediction": float(np.mean(raw_values[mask])) if count else None,
                "calibrated_mean_prediction": (
                    float(np.mean(calibrated_values[mask])) if count else None
                ),
                "observed_rate": float(np.mean(y[mask])) if count else None,
            }
        )
    return entries


def _max_supported_deviation(
    paired: Sequence[Mapping[str, object]], prediction_key: str
) -> tuple[float | None, int]:
    deviations: list[float] = []
    for entry in paired:
        count = int(cast(int, entry["count"]))
        observed = entry["observed_rate"]
        mean_prediction = entry[prediction_key]
        if count < D11_MIN_SUPPORT or observed is None or mean_prediction is None:
            continue
        deviations.append(abs(float(cast(float, mean_prediction)) - float(cast(float, observed))))
    return (max(deviations), len(deviations)) if deviations else (None, 0)


def _improves_by_adoption_tolerance(raw_value: float, calibrated_value: float) -> bool:
    """Inclusive decimal-rule boundary with bounded binary64 reduction protection."""
    improvement = raw_value - calibrated_value
    rounding_guard = 4.0 * max(
        math.ulp(raw_value), math.ulp(calibrated_value), math.ulp(ADOPTION_TOLERANCE)
    )
    return improvement >= ADOPTION_TOLERANCE or math.isclose(
        improvement,
        ADOPTION_TOLERANCE,
        rel_tol=0.0,
        abs_tol=rounding_guard,
    )


def decide_calibration_adoption(
    y_true: Sequence[int] | IntArray,
    raw: Sequence[float] | FloatArray,
    calibrated: Sequence[float] | FloatArray,
    *,
    platt_slope: float,
    platt_intercept: float,
) -> dict[str, object]:
    """Apply the frozen WC2022 adoption rule using raw-anchor groups only."""
    y, raw_values, calibrated_values = _arrays(y_true, raw, calibrated)
    paired = paired_raw_anchor_reliability(y, raw_values, calibrated_values)
    raw_max, raw_supported = _max_supported_deviation(paired, "raw_mean_prediction")
    calibrated_max, calibrated_supported = _max_supported_deviation(
        paired, "calibrated_mean_prediction"
    )
    raw_ll = log_loss(y, raw_values)
    calibrated_ll = log_loss(y, calibrated_values)
    raw_brier = brier_score(y, raw_values)
    calibrated_brier = brier_score(y, calibrated_values)
    reasons: list[str] = []
    if not math.isfinite(platt_slope) or platt_slope <= 0.0:
        reasons.append("platt_slope_not_finite_positive")
    if raw_supported == 0 or calibrated_supported == 0:
        reasons.append("no_supported_raw_anchor_bins")
    if (
        raw_max is None
        or calibrated_max is None
        or not _improves_by_adoption_tolerance(raw_max, calibrated_max)
    ):
        reasons.append("calibration_does_not_improve_raw_anchor_deviation")
    if calibrated_ll > raw_ll + ADOPTION_TOLERANCE:
        reasons.append("calibrated_log_loss_worsens")
    if calibrated_brier > raw_brier + ADOPTION_TOLERANCE:
        reasons.append("calibrated_brier_worsens")
    adopted = "calibrated" if not reasons else "raw"
    return {
        "rule_version": CALIBRATION_RULE_VERSION,
        "min_support": D11_MIN_SUPPORT,
        "bin_edges": list(RAW_ANCHOR_BIN_EDGES),
        "supported_bins": raw_supported,
        "raw_max_abs_deviation_supported": raw_max,
        "calibrated_max_abs_deviation_supported": calibrated_max,
        "raw_log_loss": raw_ll,
        "calibrated_log_loss": calibrated_ll,
        "raw_brier": raw_brier,
        "calibrated_brier": calibrated_brier,
        "platt_slope": float(platt_slope),
        "platt_intercept": float(platt_intercept),
        "adopted_variant": adopted,
        "rejection_reasons": reasons,
        "raw_anchor_reliability": paired,
        "raw_variant_reliability": reliability_table(y, raw_values),
        "calibrated_variant_reliability": reliability_table(y, calibrated_values),
    }


@dataclass(frozen=True)
class CalibrationDecision:
    decision_sha256: str
    payload: Mapping[str, object]

    @property
    def adopted_variant(self) -> str:
        value = self.payload.get("adopted_variant")
        if value not in {"raw", "calibrated"}:
            raise CalibrationDecisionError("calibration decision has no valid adopted_variant")
        return str(value)

    def as_dict(self) -> dict[str, object]:
        return {"decision_sha256": self.decision_sha256, "decision": dict(self.payload)}


def write_calibration_decision(
    path: str | Path, payload: Mapping[str, object]
) -> CalibrationDecision:
    """Write an immutable, content-hashed calibration decision."""
    destination = Path(path)
    content = _canonical_exact_json(dict(payload))
    digest = _sha256_bytes(content)
    envelope = {"decision_sha256": digest, "decision": dict(payload)}
    encoded = _canonical_exact_json(envelope)
    if destination.exists():
        if destination.read_bytes() != encoded:
            raise CalibrationDecisionError(
                f"refusing to overwrite immutable calibration decision {destination}"
            )
        return CalibrationDecision(digest, dict(payload))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(encoded)
    return CalibrationDecision(digest, dict(payload))


def load_calibration_decision(path: str | Path) -> CalibrationDecision:
    source = Path(path)
    try:
        envelope = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CalibrationDecisionError(f"cannot read calibration decision {source}") from exc
    if not isinstance(envelope, dict) or not isinstance(envelope.get("decision"), dict):
        raise CalibrationDecisionError("calibration decision envelope is malformed")
    payload = envelope["decision"]
    expected = envelope.get("decision_sha256")
    actual = _canonical_digest(payload)
    if expected != actual:
        raise CalibrationDecisionError(
            f"calibration decision digest is {expected!r}, but content hashes to {actual}"
        )
    return CalibrationDecision(str(actual), payload)


def verify_calibration_base_identity(
    decision: CalibrationDecision, frozen: FrozenBaseModel
) -> None:
    recorded = decision.payload.get("base_identity")
    if recorded != frozen.identity.as_dict():
        raise CalibrationContractError(
            "calibration decision base-model/preprocessing identity does not match the frozen base"
        )


def verify_calibration_decision(decision: CalibrationDecision, frozen: FrozenBaseModel) -> None:
    """Validate the complete decision envelope before any holdout rows are opened."""
    if decision.decision_sha256 != _canonical_digest(decision.payload):
        raise CalibrationDecisionError("calibration decision object has an invalid content digest")
    verify_calibration_base_identity(decision, frozen)
    payload = decision.payload
    if payload.get("schema_version") != 1:
        raise CalibrationDecisionError("calibration decision schema version is unsupported")
    if payload.get("rule_version") != CALIBRATION_RULE_VERSION:
        raise CalibrationDecisionError("calibration decision uses an unregistered adoption rule")
    if payload.get("calibration_split") != "WC2022":
        raise CalibrationDecisionError("calibration decision was not fitted on WC2022")
    if payload.get("calibration_fit_scope") != "WC2022_only":
        raise CalibrationDecisionError("calibration decision has an invalid calibration fit scope")
    if payload.get("holdout_accessed") is not False:
        raise CalibrationDecisionError("calibration decision does not prove holdout isolation")
    registered_base = payload.get("registered_base")
    if not isinstance(registered_base, Mapping):
        raise CalibrationDecisionError("calibration decision lacks its external base registration")
    registered_pins = BaseModelPins.from_mapping(registered_base)
    expected_registered = {
        "artifact_path": frozen.identity.artifact_path,
        "artifact_manifest_path": frozen.identity.artifact_manifest_path,
        "artifact_schema_version": frozen.identity.artifact_schema_version,
        "model_pickle_sha256": frozen.identity.model_pickle_sha256,
        "artifact_manifest_sha256": frozen.identity.artifact_manifest_sha256,
        "experiment_id": frozen.identity.experiment_id,
        "candidate": frozen.identity.candidate,
        "shipped_feature_set": "geometry+categoricals",
        "best_c": frozen.bundle.best_c,
        "data_source_commit": frozen.identity.data_source_commit,
        "cohort_sql_sha256": frozen.identity.cohort_sql_sha256,
        "assignments_sha256": frozen.identity.assignments_sha256,
        "code_commit": frozen.identity.code_commit,
        "reproduction_commit": frozen.identity.reproduction_commit,
        "input_config_sha256": frozen.identity.input_config_sha256,
        "uv_lock_sha256": frozen.identity.uv_lock_sha256,
    }
    if registered_pins.as_dict() != expected_registered:
        raise CalibrationDecisionError("calibration decision external base registration is invalid")
    execution = payload.get("execution_provenance")
    if not isinstance(execution, Mapping):
        raise CalibrationDecisionError("calibration decision lacks current execution provenance")
    execution_digest = payload.get("execution_provenance_sha256")
    if execution_digest != exact_payload_sha256(execution):
        raise CalibrationDecisionError(
            "calibration decision execution provenance digest is invalid"
        )
    config_digest = payload.get("calibration_config_sha256")
    if (
        not isinstance(config_digest, str)
        or len(config_digest) != 64
        or execution.get("input_config_sha256") != config_digest
    ):
        raise CalibrationDecisionError("calibration decision config provenance is invalid")
    try:
        slope = float(cast(float, payload["platt_slope"]))
        intercept = float(cast(float, payload["platt_intercept"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise CalibrationDecisionError(
            "calibration decision has no valid Platt parameters"
        ) from exc
    if payload.get("platt_parameter_sha256") != platt_parameter_digest(slope, intercept):
        raise CalibrationDecisionError("calibration decision Platt parameter digest is invalid")
    adoption = payload.get("adoption")
    if not isinstance(adoption, Mapping):
        raise CalibrationDecisionError("calibration decision lacks adoption evidence")
    if adoption.get("rule_version") != CALIBRATION_RULE_VERSION:
        raise CalibrationDecisionError("adoption evidence uses an unregistered rule")
    if adoption.get("adopted_variant") != decision.adopted_variant:
        raise CalibrationDecisionError("top-level and nested adopted variants disagree")
