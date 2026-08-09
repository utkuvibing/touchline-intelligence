"""Supervisor contracts for two-run CPU/CUDA qualification and frozen selection."""

from __future__ import annotations

import inspect
import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

from touchline.modeling.metrics import canonical_metrics_json
from touchline.modeling.qualify_mlp import QualificationError, finalize_qualification
from touchline.modeling.train_mlp import _qualification_payload


def _write(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_metrics_json(payload))
    return path


def _payload(device: str) -> dict[str, object]:
    return {
        "frozen_canonical_cpu_selection": "full_minus_presence",
        "selection_effect": "none" if device == "cuda" else "canonical_reproduction",
        "final_parameter_digest": "p" * 64 if device == "cpu" else "g" * 64,
        "artifact_reload": {
            "device": device,
            "weights_sha256": "w" * 64,
            "parameter_digest": "p" * 64,
            "preprocessing_digest": "x" * 64,
            "ordered_shot_ids": ["a", "b"],
            "probabilities": [0.1, 0.2 + (1e-7 if device == "cuda" else 0.0)],
        },
        "mlp_oof_metrics": {"mean_log_loss": 0.3},
        "ordered_oof_predictions": [{"fold": 0, "shot_id": "a", "probability": 0.1}],
        "fold_parameter_digests": ["f" * 64],
        "training_history": {"folds": [], "selection_epoch": 200},
    }


def _inputs(tmp_path: Path) -> tuple[list[Path], list[Path], Path, Path, Path]:
    experiment = tmp_path / "experiment"
    canonical = _write(
        experiment / "metrics.json",
        {
            "selection_incumbent": "full_minus_presence",
            "weights_sha256": "w" * 64,
            "parameter_digest": "p" * 64,
            "preprocessing_digest": "x" * 64,
            "candidates": {"pytorch_mlp": {"mean_log_loss": 0.3}},
            "ordered_oof_predictions": [{"fold": 0, "shot_id": "a", "probability": 0.1}],
            "fold_parameter_digests": ["f" * 64],
        },
    )
    history = _write(experiment / "training-history.json", {"folds": [], "selection_epoch": 200})
    cpu_payload = _payload("cpu")
    cuda_payload = _payload("cuda")
    cpu = [_write(tmp_path / f"cpu-{index}.json", cpu_payload) for index in range(2)]
    cuda = [_write(tmp_path / f"cuda-{index}.json", cuda_payload) for index in range(2)]
    return cpu, cuda, canonical, history, experiment / "cuda-qualification.json"


def test_supervisor_requires_two_exact_runs_and_publishes_parity(tmp_path: Path) -> None:
    cpu, cuda, canonical, history, output = _inputs(tmp_path)
    record = finalize_qualification(
        cpu_paths=cpu,
        cuda_paths=cuda,
        canonical_metrics_path=canonical,
        canonical_history_path=history,
        output_path=output,
    )
    assert output.exists()
    assert record["selection_effect"] == "none"
    parity = cast(Mapping[str, object], record["same_weight_inference_parity"])
    assert parity["atol"] == 1e-6
    assert parity["rtol"] == 1e-5


def test_supervisor_rejects_cuda_selection_or_non_repeated_payload(tmp_path: Path) -> None:
    cpu, cuda, canonical, history, output = _inputs(tmp_path)
    changed = json.loads(cuda[1].read_text(encoding="utf-8"))
    changed["selection_effect"] = "cuda_decision"
    _write(cuda[1], changed)
    with pytest.raises(QualificationError, match="payloads differ"):
        finalize_qualification(
            cpu_paths=cpu,
            cuda_paths=cuda,
            canonical_metrics_path=canonical,
            canonical_history_path=history,
            output_path=output,
        )


def test_supervisor_rejects_identical_cuda_payloads_that_claim_selection(tmp_path: Path) -> None:
    cpu, cuda, canonical, history, output = _inputs(tmp_path)
    for path in cuda:
        changed = json.loads(path.read_text(encoding="utf-8"))
        changed["selection_effect"] = "cuda_decision"
        _write(path, changed)
    with pytest.raises(QualificationError, match="selection-isolated"):
        finalize_qualification(
            cpu_paths=cpu,
            cuda_paths=cuda,
            canonical_metrics_path=canonical,
            canonical_history_path=history,
            output_path=output,
        )


def test_supervisor_rejects_same_weight_cpu_cuda_parity_failure(tmp_path: Path) -> None:
    cpu, cuda, canonical, history, output = _inputs(tmp_path)
    for path in cuda:
        changed = json.loads(path.read_text(encoding="utf-8"))
        artifact_reload = changed["artifact_reload"]
        assert isinstance(artifact_reload, dict)
        artifact_reload["probabilities"] = [0.8, 0.9]
        _write(path, changed)
    with pytest.raises(QualificationError, match="inference parity failed"):
        finalize_qualification(
            cpu_paths=cpu,
            cuda_paths=cuda,
            canonical_metrics_path=canonical,
            canonical_history_path=history,
            output_path=output,
        )


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("mlp_oof_metrics", {"mean_log_loss": 0.31}, "MLP metrics"),
        (
            "ordered_oof_predictions",
            [{"fold": 0, "shot_id": "a", "probability": 0.2}],
            "OOF predictions",
        ),
        ("fold_parameter_digests", ["z" * 64], "fold parameter digests"),
        ("training_history", {"folds": [], "selection_epoch": 199}, "training history"),
    ],
)
def test_supervisor_rejects_cpu_repeats_that_disagree_with_canonical(
    tmp_path: Path, field: str, replacement: object, message: str
) -> None:
    cpu, cuda, canonical, history, output = _inputs(tmp_path)
    for path in cpu:
        changed = json.loads(path.read_text(encoding="utf-8"))
        changed[field] = replacement
        _write(path, changed)
    with pytest.raises(QualificationError, match=message):
        finalize_qualification(
            cpu_paths=cpu,
            cuda_paths=cuda,
            canonical_metrics_path=canonical,
            canonical_history_path=history,
            output_path=output,
        )


def test_cuda_payload_builder_cannot_read_or_publish_cuda_selection_chains() -> None:
    source = inspect.getsource(_qualification_payload)
    assert "result.chains" not in source
