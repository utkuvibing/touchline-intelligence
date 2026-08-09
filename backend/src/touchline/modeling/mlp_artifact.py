"""Versioned state-dictionary artifact and inference lifecycle for WP2.6."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
import numpy.typing as npt
import torch

from touchline.modeling.artifact import ArtifactCompatibilityError, validate_column_contract
from touchline.modeling.metrics import canonical_metrics_json
from touchline.modeling.mlp import (
    HIDDEN_DIM,
    INPUT_DIM,
    PARAMETER_COUNT,
    ShotMLP,
    parameter_digest,
    predict_probabilities,
)
from touchline.modeling.preprocessing import (
    CATEGORICAL_FIELDS,
    ShotRow,
    StandardScaler,
    Vocabulary,
    encode_rows,
)

MLP_ARTIFACT_SCHEMA_VERSION = 1
ProbabilityVector = npt.NDArray[np.float64]


class MlpArtifactCompatibilityError(ValueError):
    """The MLP weights, metadata or current feature contract are incompatible."""


@dataclass(frozen=True)
class MlpArtifact:
    model: ShotMLP
    experiment_id: str
    artifact_candidate: str
    selection_incumbent: str
    scaler: StandardScaler
    vocabulary: Vocabulary
    all_columns: tuple[str, ...]
    selected_columns: tuple[str, ...]
    selected_indices: tuple[int, ...]
    weights_sha256: str
    parameter_digest: str
    preprocessing_digest: str
    metadata: Mapping[str, object]
    device: torch.device


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _architecture() -> dict[str, object]:
    return {
        "input_dim": INPUT_DIM,
        "hidden_dim": HIDDEN_DIM,
        "output_dim": 1,
        "activation": "ReLU",
        "output_semantics": "raw_logit",
        "parameter_count": PARAMETER_COUNT,
        "dtype": "torch.float32",
    }


def preprocessing_digest(
    vocabulary: Vocabulary,
    scaler: StandardScaler,
    all_columns: Sequence[str],
    selected_indices: Sequence[int],
) -> str:
    """Canonical identity for final scaler, vocabulary and selected feature schema."""
    selected = [int(index) for index in selected_indices]
    payload = {
        "scaler": scaler.as_dict(),
        "vocabulary": vocabulary.as_dict(),
        "all_columns": list(all_columns),
        "selected_indices": selected,
        "selected_columns": [all_columns[index] for index in selected],
    }
    return hashlib.sha256(canonical_metrics_json(payload)).hexdigest()


def _vocabulary_from_dict(payload: Mapping[str, object]) -> Vocabulary:
    levels = cast(Mapping[str, Sequence[str]], payload["levels"])
    reference = cast(Mapping[str, str], payload["reference"])
    rare_members = cast(Mapping[str, Sequence[str]], payload["rare_members"])
    return Vocabulary(
        levels={field: tuple(levels[field]) for field in CATEGORICAL_FIELDS},
        reference={field: reference[field] for field in CATEGORICAL_FIELDS},
        rare_members={field: tuple(rare_members[field]) for field in CATEGORICAL_FIELDS},
    )


def _scaler_from_dict(payload: Mapping[str, object]) -> StandardScaler:
    return StandardScaler(
        mean={
            k: float(cast(int | float | str, v))
            for k, v in cast(Mapping[str, object], payload["mean"]).items()
        },
        std={
            k: float(cast(int | float | str, v))
            for k, v in cast(Mapping[str, object], payload["std"]).items()
        },
    )


def save_mlp_artifact(
    *,
    model: ShotMLP,
    weights_path: Path,
    metadata_path: Path,
    experiment_id: str,
    artifact_candidate: str,
    selection_incumbent: str,
    scaler: StandardScaler,
    vocabulary: Vocabulary,
    all_columns: Sequence[str],
    selected_indices: Sequence[int],
    provenance: Mapping[str, object],
) -> dict[str, object]:
    """Persist only a state dictionary plus canonical JSON metadata."""
    weights_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    selected = tuple(int(index) for index in selected_indices)
    selected_columns = tuple(all_columns[index] for index in selected)
    validate_column_contract(
        all_columns=all_columns,
        selected_columns=selected_columns,
        selected_indices=selected,
        current_columns=all_columns,
        n_features_in=INPUT_DIM,
    )
    cpu_state = {
        name: tensor.detach().to(device="cpu").contiguous()
        for name, tensor in model.state_dict().items()
    }
    torch.save(cpu_state, weights_path)
    weights_sha = _sha256(weights_path)
    params_sha = parameter_digest(model)
    preprocessing_sha = preprocessing_digest(vocabulary, scaler, all_columns, selected)
    payload: dict[str, object] = {
        "artifact_schema_version": MLP_ARTIFACT_SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "artifact_candidate": artifact_candidate,
        "selection_incumbent": selection_incumbent,
        "weights_path": weights_path.as_posix(),
        "weights_sha256": weights_sha,
        "parameter_digest": params_sha,
        "preprocessing_digest": preprocessing_sha,
        "architecture": _architecture(),
        "all_columns": list(all_columns),
        "selected_columns": list(selected_columns),
        "selected_indices": list(selected),
        "scaler": scaler.as_dict(),
        "vocabulary": vocabulary.as_dict(),
        "provenance": dict(provenance),
    }
    metadata_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return payload


def load_mlp_artifact(
    weights_path: Path,
    metadata_path: Path,
    *,
    device: torch.device,
    expected_preprocessing_digest: str,
) -> MlpArtifact:
    """Verify metadata and exact weights, then reconstruct and strictly load trusted code."""
    try:
        payload = cast(dict[str, Any], json.loads(metadata_path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        raise MlpArtifactCompatibilityError(f"cannot read MLP metadata: {exc}") from exc
    if payload.get("artifact_schema_version") != MLP_ARTIFACT_SCHEMA_VERSION:
        raise MlpArtifactCompatibilityError("unsupported MLP artifact schema version")
    if payload.get("architecture") != _architecture():
        raise MlpArtifactCompatibilityError("MLP architecture metadata does not match trusted code")
    expected_weights_sha = str(payload.get("weights_sha256", ""))
    if _sha256(weights_path) != expected_weights_sha:
        raise MlpArtifactCompatibilityError("weights SHA-256 does not match metadata")
    vocabulary = _vocabulary_from_dict(cast(Mapping[str, object], payload["vocabulary"]))
    scaler = _scaler_from_dict(cast(Mapping[str, object], payload["scaler"]))
    all_columns = tuple(str(value) for value in payload["all_columns"])
    selected_columns = tuple(str(value) for value in payload["selected_columns"])
    selected_indices = tuple(int(value) for value in payload["selected_indices"])
    try:
        validate_column_contract(
            all_columns=all_columns,
            selected_columns=selected_columns,
            selected_indices=selected_indices,
            current_columns=vocabulary.column_names(),
            n_features_in=INPUT_DIM,
        )
    except ArtifactCompatibilityError as exc:
        raise MlpArtifactCompatibilityError(str(exc)) from exc
    actual_preprocessing_digest = preprocessing_digest(
        vocabulary, scaler, all_columns, selected_indices
    )
    if (
        actual_preprocessing_digest != str(payload.get("preprocessing_digest", ""))
        or actual_preprocessing_digest != expected_preprocessing_digest
    ):
        raise MlpArtifactCompatibilityError(
            "preprocessing digest does not match trusted committed evidence"
        )
    try:
        state = torch.load(weights_path, map_location=device, weights_only=True)
        if not isinstance(state, dict) or not all(
            isinstance(name, str) and isinstance(tensor, torch.Tensor)
            for name, tensor in state.items()
        ):
            raise MlpArtifactCompatibilityError("weights.pt is not a tensor state dictionary")
        model = ShotMLP().to(device=device, dtype=torch.float32)
        model.load_state_dict(state, strict=True)
    except (RuntimeError, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, MlpArtifactCompatibilityError):
            raise
        raise MlpArtifactCompatibilityError(
            f"cannot strictly load MLP state dictionary: {exc}"
        ) from exc
    actual_parameter_digest = parameter_digest(model)
    if actual_parameter_digest != str(payload.get("parameter_digest", "")):
        raise MlpArtifactCompatibilityError("parameter digest does not match metadata")
    model.eval()
    return MlpArtifact(
        model=model,
        experiment_id=str(payload["experiment_id"]),
        artifact_candidate=str(payload["artifact_candidate"]),
        selection_incumbent=str(payload["selection_incumbent"]),
        scaler=scaler,
        vocabulary=vocabulary,
        all_columns=all_columns,
        selected_columns=selected_columns,
        selected_indices=selected_indices,
        weights_sha256=expected_weights_sha,
        parameter_digest=actual_parameter_digest,
        preprocessing_digest=actual_preprocessing_digest,
        metadata=payload,
        device=device,
    )


def infer_mlp(artifact: MlpArtifact, rows: Sequence[ShotRow]) -> ProbabilityVector:
    """Score raw rows through persisted preprocessing and the strict selected-column contract."""
    full, current_columns = encode_rows(rows, artifact.vocabulary, artifact.scaler)
    try:
        validate_column_contract(
            all_columns=artifact.all_columns,
            selected_columns=artifact.selected_columns,
            selected_indices=artifact.selected_indices,
            current_columns=current_columns,
            n_features_in=INPUT_DIM,
        )
    except ArtifactCompatibilityError as exc:
        raise MlpArtifactCompatibilityError(str(exc)) from exc
    selected = full[:, list(artifact.selected_indices)]
    return predict_probabilities(artifact.model, selected, artifact.device)
