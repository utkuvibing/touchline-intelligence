"""State-dictionary artifact, identity, strict reload and raw-row inference contracts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import torch

from touchline.modeling.mlp import ShotMLP, predict_probabilities, reset_fit_seed
from touchline.modeling.mlp_artifact import (
    MlpArtifactCompatibilityError,
    infer_mlp,
    load_mlp_artifact,
    preprocessing_digest,
    save_mlp_artifact,
)
from touchline.modeling.preprocessing import ShotRow, StandardScaler, Vocabulary, encode_rows

SELECTED = (
    "distance_to_goal",
    "visible_goal_angle",
    "body_part_name::Head",
    "body_part_name::Left Foot",
    "body_part_name::rare",
    "technique_name::Half Volley",
    "technique_name::Volley",
    "technique_name::rare",
    "play_pattern_name::From Corner",
    "play_pattern_name::From Counter",
    "play_pattern_name::From Free Kick",
    "play_pattern_name::From Goal Kick",
    "play_pattern_name::From Keeper",
    "play_pattern_name::From Kick Off",
    "play_pattern_name::From Throw In",
    "play_pattern_name::rare",
)


def _contract() -> tuple[Vocabulary, StandardScaler, tuple[str, ...], tuple[int, ...]]:
    vocabulary = Vocabulary(
        levels={
            "body_part_name": ("Head", "Left Foot", "rare"),
            "technique_name": ("Half Volley", "Volley", "rare"),
            "play_pattern_name": (
                "From Corner",
                "From Counter",
                "From Free Kick",
                "From Goal Kick",
                "From Keeper",
                "From Kick Off",
                "From Throw In",
                "rare",
            ),
        },
        reference={
            "body_part_name": "Right Foot",
            "technique_name": "Normal",
            "play_pattern_name": "Regular Play",
        },
        rare_members={
            "body_part_name": ("Other",),
            "technique_name": ("Backheel",),
            "play_pattern_name": ("Other",),
        },
    )
    scaler = StandardScaler(
        mean={"distance_to_goal": 20.0, "visible_goal_angle": 0.3},
        std={"distance_to_goal": 5.0, "visible_goal_angle": 0.1},
    )
    all_columns = tuple(vocabulary.column_names())
    presence = {"first_time_presence", "under_pressure_presence"}
    indices = tuple(i for i, name in enumerate(all_columns) if name not in presence)
    assert tuple(all_columns[i] for i in indices) == SELECTED
    return vocabulary, scaler, all_columns, indices


def _rows() -> list[ShotRow]:
    return [
        ShotRow(
            shot_id="artifact-shot",
            match_id=1,
            fold=0,
            competition_id=43,
            season_id=3,
            y=0,
            distance_to_goal=18.0,
            visible_goal_angle=0.4,
            body_part_name="Head",
            technique_name="Volley",
            play_pattern_name="From Corner",
            first_time=None,
            under_pressure=None,
        )
    ]


def _save(tmp_path: Path) -> tuple[Path, Path, ShotMLP]:
    vocabulary, scaler, all_columns, indices = _contract()
    reset_fit_seed()
    model = ShotMLP()
    weights = tmp_path / "weights.pt"
    metadata = tmp_path / "metadata.json"
    save_mlp_artifact(
        model=model,
        weights_path=weights,
        metadata_path=metadata,
        experiment_id="synthetic-wp26",
        artifact_candidate="pytorch_mlp",
        selection_incumbent="full_minus_presence",
        scaler=scaler,
        vocabulary=vocabulary,
        all_columns=all_columns,
        selected_indices=indices,
        provenance={"code_commit": "abc", "uv_lock_sha256": "0" * 64},
    )
    return weights, metadata, model


def test_state_dict_round_trip_matches_direct_encoded_and_raw_inference(tmp_path: Path) -> None:
    weights, metadata, original = _save(tmp_path)
    expected = json.loads(metadata.read_text(encoding="utf-8"))["preprocessing_digest"]
    artifact = load_mlp_artifact(
        weights,
        metadata,
        device=torch.device("cpu"),
        expected_preprocessing_digest=expected,
    )
    rows = _rows()
    full, columns = encode_rows(rows, artifact.vocabulary, artifact.scaler)
    assert tuple(columns) == artifact.all_columns
    selected = full[:, list(artifact.selected_indices)]
    direct = predict_probabilities(original, selected, torch.device("cpu"))
    assert np.array_equal(infer_mlp(artifact, rows), direct)
    assert artifact.model.training is False


def test_metadata_identifies_weights_and_parameters_without_pickle_claim(tmp_path: Path) -> None:
    weights, metadata, _ = _save(tmp_path)
    payload = json.loads(metadata.read_text(encoding="utf-8"))
    assert len(payload["weights_sha256"]) == 64
    assert len(payload["parameter_digest"]) == 64
    assert len(payload["preprocessing_digest"]) == 64
    assert payload["weights_path"] == weights.as_posix()
    assert "model_pickle_sha256" not in payload
    assert payload["architecture"] == {
        "input_dim": 16,
        "hidden_dim": 8,
        "output_dim": 1,
        "activation": "ReLU",
        "output_semantics": "raw_logit",
        "parameter_count": 145,
        "dtype": "torch.float32",
    }


def test_corrupt_weights_and_metadata_fail_loudly(tmp_path: Path) -> None:
    weights, metadata, _ = _save(tmp_path)
    weights.write_bytes(weights.read_bytes() + b"corrupt")
    with pytest.raises(MlpArtifactCompatibilityError, match="weights SHA-256"):
        load_mlp_artifact(
            weights,
            metadata,
            device=torch.device("cpu"),
            expected_preprocessing_digest=json.loads(metadata.read_text(encoding="utf-8"))[
                "preprocessing_digest"
            ],
        )

    weights, metadata, _ = _save(tmp_path / "second")
    payload = json.loads(metadata.read_text(encoding="utf-8"))
    trusted_digest = payload["preprocessing_digest"]
    payload["selected_columns"] = list(reversed(payload["selected_columns"]))
    metadata.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(MlpArtifactCompatibilityError, match="selected_columns"):
        load_mlp_artifact(
            weights,
            metadata,
            device=torch.device("cpu"),
            expected_preprocessing_digest=trusted_digest,
        )


def test_tampered_scaler_fails_the_trusted_preprocessing_digest(tmp_path: Path) -> None:
    weights, metadata, _ = _save(tmp_path)
    payload = json.loads(metadata.read_text(encoding="utf-8"))
    trusted_digest = payload["preprocessing_digest"]
    payload["scaler"]["mean"]["distance_to_goal"] += 1.0
    vocabulary, scaler, all_columns, indices = _contract()
    changed_scaler = StandardScaler(mean={**scaler.mean, "distance_to_goal": 21.0}, std=scaler.std)
    payload["preprocessing_digest"] = preprocessing_digest(
        vocabulary, changed_scaler, all_columns, indices
    )
    metadata.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(MlpArtifactCompatibilityError, match="preprocessing digest"):
        load_mlp_artifact(
            weights,
            metadata,
            device=torch.device("cpu"),
            expected_preprocessing_digest=trusted_digest,
        )


def test_tampered_parameter_digest_fails_after_strict_weight_load(tmp_path: Path) -> None:
    weights, metadata, _ = _save(tmp_path)
    payload = json.loads(metadata.read_text(encoding="utf-8"))
    preprocessing = payload["preprocessing_digest"]
    payload["parameter_digest"] = "0" * 64
    metadata.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(MlpArtifactCompatibilityError, match="parameter digest"):
        load_mlp_artifact(
            weights,
            metadata,
            device=torch.device("cpu"),
            expected_preprocessing_digest=preprocessing,
        )


def test_preprocessing_digest_covers_scaler_vocabulary_and_column_contract() -> None:
    vocabulary, scaler, all_columns, indices = _contract()
    baseline = preprocessing_digest(vocabulary, scaler, all_columns, indices)
    changed_scaler = StandardScaler(mean={**scaler.mean, "distance_to_goal": 21.0}, std=scaler.std)
    assert preprocessing_digest(vocabulary, changed_scaler, all_columns, indices) != baseline


def test_artifact_strictly_reloads_in_fresh_cpu_and_cuda_processes(tmp_path: Path) -> None:
    weights, metadata, _ = _save(tmp_path)
    digest = json.loads(metadata.read_text(encoding="utf-8"))["preprocessing_digest"]
    environment = dict(os.environ)
    root = Path(__file__).resolve().parents[2]
    environment["PYTHONPATH"] = str(root / "backend/tests")

    def probe(device: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "support.wp26_artifact_probe",
                "--weights",
                str(weights),
                "--metadata",
                str(metadata),
                "--preprocessing-digest",
                digest,
                "--device",
                device,
            ],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
        )

    cpu = probe("cpu")
    assert cpu.returncode == 0, cpu.stderr
    if torch.cuda.is_available():
        environment["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
        cuda = probe("cuda")
        assert cuda.returncode == 0, cuda.stderr
        cpu_payload = json.loads(cpu.stdout)
        cuda_payload = json.loads(cuda.stdout)
        for key in ("weights_sha256", "parameter_digest", "preprocessing_digest"):
            assert cpu_payload[key] == cuda_payload[key]
        assert np.allclose(
            cpu_payload["probabilities"], cuda_payload["probabilities"], atol=1e-6, rtol=1e-5
        )
