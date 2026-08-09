"""Config-driven WP2.6 CPU evidence and non-selection CUDA qualification entry point."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
import torch

from touchline.modeling.dataset import (
    load_development_cohort,
    parse_match_assignments,
    verify_assignments_csv,
    verify_cohort_sql,
    verify_development_anchor,
)
from touchline.modeling.experiment import (
    Provenance,
    abs_path,
    open_db,
    record_path,
    replace_results_csv,
    resolve_provenance,
)
from touchline.modeling.metrics import canonical_metrics_json
from touchline.modeling.mlp import (
    BATCH_SIZE,
    BETAS,
    EPOCHS,
    EPSILON,
    LEARNING_RATE,
    NUM_WORKERS,
    SEED,
    WEIGHT_DECAY,
    FitResult,
    configure_deterministic_runtime,
    fit_mlp,
)
from touchline.modeling.mlp_artifact import infer_mlp, load_mlp_artifact, save_mlp_artifact
from touchline.modeling.mlp_protocol import (
    MLP_KEY,
    SHIPPED_FEATURE_COLUMNS,
    MlpOofResult,
    PreparedFolds,
    assert_metrics_reproduce_to_12_decimals,
    prepare_shipped_folds,
    reproduce_inherited_candidates,
    run_mlp_oof,
    selection_chains,
)
from touchline.modeling.preprocessing import ShotRow, StandardScaler, encode_rows, fit_scaler

ROOT = Path(__file__).resolve().parents[4]
CSV_PATH = ROOT / "data" / "model" / "wp2_3_match_assignments.csv"
COHORT_SQL_PATH = ROOT / "backend" / "sql" / "wp2_1" / "01_model_shot_cohort.sql"
ADR_PATH = ROOT / "docs" / "adr" / "0012-wp2-6-bounded-pytorch-mlp-lifecycle.md"
_ACCEPTED = re.compile(r"^- Status:\s*\*\*accepted\s+[—-]\s*(\d{4}-\d{2}-\d{2})\*\*$", re.MULTILINE)


class PreRegistrationError(RuntimeError):
    """The fixed WP2.6 decision has not received explicit author acceptance."""


class MlpConfigError(ValueError):
    """The run config differs from the pre-registered architecture or training contract."""


@dataclass(frozen=True)
class MlpRunConfig:
    experiment_id: str
    out_dir: str
    artifacts_dir: str
    code_commit: str
    data_source_commit: str
    db_url_env: str
    assignments_sha256: str
    cohort_sql_sha256: str
    random_seed: int
    n_folds: int
    expected_shots: int
    expected_matches: int
    expected_fold_sizes: Mapping[int, int]
    bin_count: int
    results_csv: str
    published_wp2_5_metrics: str
    input_config_path: str
    require_clean_provenance: bool
    model_family: str
    reproduction_commit: str = "unset"
    input_config_sha256: str = ""
    uv_lock_sha256: str = ""
    runtime_fingerprint: Mapping[str, object] | None = None
    dataset_id: str = "wp2_3_split_lock"
    split_strategy: str = "wp2_3_tournament_split"
    target: str = "ShotRow.y"
    feature_set: str = "geometry+categoricals"
    feature_columns: tuple[str, ...] = ()


@dataclass(frozen=True)
class Wp26RunResult:
    prepared: PreparedFolds
    candidates: Mapping[str, Mapping[str, object]]
    chains: Mapping[str, Mapping[str, object]]
    mlp_oof: MlpOofResult
    final_scaler: StandardScaler
    final_fit: FitResult


def check_pre_registration(path: Path = ADR_PATH) -> str:
    """Return the acceptance date or fail before provenance and database access."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PreRegistrationError(f"WP2.6 ADR is unavailable: {exc}") from exc
    matched = _ACCEPTED.search(text)
    if matched is None:
        raise PreRegistrationError(
            "WP2.6 ADR 0012 is not accepted; author acceptance is required before cohort execution"
        )
    return matched.group(1)


def resolve_device(name: str) -> torch.device:
    """Resolve only an explicitly requested device; never fall back silently."""
    if name == "cpu":
        return torch.device("cpu")
    if name == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA was requested but is not available in this locked environment")
        return torch.device("cuda:0")
    raise ValueError("device must be exactly 'cpu' or 'cuda'")


def _expected_architecture() -> dict[str, object]:
    return {
        "activation": "ReLU",
        "dtype": "float32",
        "hidden_dim": 8,
        "input_dim": 16,
        "output_dim": 1,
        "output_semantics": "raw_logit",
        "parameter_count": 145,
    }


def _expected_training() -> dict[str, object]:
    return {
        "amsgrad": False,
        "batch_size": BATCH_SIZE,
        "betas": list(BETAS),
        "drop_last": False,
        "early_stopping": False,
        "epochs": EPOCHS,
        "epsilon": EPSILON,
        "foreach": False,
        "fused": False,
        "gradient_clipping": False,
        "learning_rate": LEARNING_RATE,
        "mixed_precision": False,
        "num_workers": NUM_WORKERS,
        "pin_memory": False,
        "scheduler": False,
        "shuffle_training": True,
        "shuffle_validation": False,
        "torch_compile": False,
        "weight_decay": WEIGHT_DECAY,
    }


def _expected_scientific_contract() -> dict[str, object]:
    """Return the inherited WP2.3/WP2.4 scientific constants that config must pin."""
    return {
        "assignments_sha256": "e2d5517d96aa81d2229e1ef00a3c692f44f280630c3e75b7f6735e7cdc1787d8",
        "bin_count": 5,
        "cohort_sql_sha256": "301d8a620b60d8da6011c7c4d12ef8108c658df4d923f612c3e3bf9e0427978e",
        "data_source_commit": "b0bc9f22dd77c206ddedc1d742893b3bbe64baec",
        "dataset_id": "wp2_3_split_lock",
        "development_matches": 115,
        "development_shots": 2872,
        "development_tournaments": ["WC 2018", "Euro 2020"],
        "feature_columns": list(SHIPPED_FEATURE_COLUMNS),
        "feature_set": "geometry+categoricals",
        "fold_sizes": {"0": 570, "1": 552, "2": 602, "3": 576, "4": 572},
        "holdout_tournament": "Euro 2024",
        "n_folds": 5,
        "reliability_bin_count": 5,
        "split_strategy": "wp2_3_tournament_split",
        "target": "ShotRow.y",
        "calibration_tournament": "WC 2022",
    }


def _expected_immutable_run_contract() -> dict[str, object]:
    """Return non-model run identifiers that an accepted config may not redefine."""
    return {
        "artifacts_dir": "artifacts/models/exp-20260809-wp2_6-pytorch-mlp",
        "code_commit": "derived-from-clean-git-head",
        "db_url_env": "TOUCHLINE_FULL_COHORT_DB_URL",
        "experiment_id": "exp-20260809-wp2_6-pytorch-mlp",
        "out_dir": "experiments/shot_quality/exp-20260809-wp2_6-pytorch-mlp",
        "published_wp2_5_metrics": (
            "experiments/shot_quality/exp-20260806-wp2_5-gradient-boosting/metrics.json"
        ),
        "require_clean_provenance": True,
        "results_csv": "experiments/results.csv",
    }


def load_config(path: Path) -> MlpRunConfig:
    payload = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    for key, expected in _expected_immutable_run_contract().items():
        if payload.get(key) != expected:
            raise MlpConfigError(
                f"immutable run identifier {key} differs from the accepted contract"
            )
    if payload.get("architecture") != _expected_architecture():
        raise MlpConfigError("architecture differs from ADR 0012")
    if payload.get("training") != _expected_training():
        raise MlpConfigError("training constants differ from ADR 0012")
    if payload.get("random_seed") != SEED or payload.get("n_folds") != 5:
        raise MlpConfigError("WP2.6 requires seed 0 and five saved outer folds")
    if payload.get("model_family") != "pytorch-mlp":
        raise MlpConfigError("model_family must be pytorch-mlp")
    expected_scientific = _expected_scientific_contract()
    if payload.get("scientific_contract") != expected_scientific:
        raise MlpConfigError("scientific constants differ from the inherited WP2.3/WP2.4 contract")
    expected_fold_sizes = cast(dict[str, int], expected_scientific["fold_sizes"])
    if payload.get("expected_fold_sizes") != expected_fold_sizes:
        raise MlpConfigError("expected fold sizes differ from the inherited WP2.3 split")
    for key in (
        "assignments_sha256",
        "cohort_sql_sha256",
        "data_source_commit",
        "dataset_id",
        "split_strategy",
    ):
        if payload.get(key) != expected_scientific[key]:
            raise MlpConfigError(f"scientific identifier {key} differs from the inherited contract")
    if payload.get("expected_shots") != expected_scientific["development_shots"]:
        raise MlpConfigError(
            "expected shot count differs from the inherited development population"
        )
    if payload.get("expected_matches") != expected_scientific["development_matches"]:
        raise MlpConfigError(
            "expected match count differs from the inherited development population"
        )
    if payload.get("bin_count") != expected_scientific["bin_count"]:
        raise MlpConfigError("reliability bin count differs from the inherited protocol")
    scientific_contract = cast(dict[str, object], payload["scientific_contract"])
    fold_sizes = {int(key): int(value) for key, value in payload["expected_fold_sizes"].items()}
    return MlpRunConfig(
        experiment_id=str(payload["experiment_id"]),
        out_dir=str(payload["out_dir"]),
        artifacts_dir=str(payload["artifacts_dir"]),
        code_commit=str(payload["code_commit"]),
        data_source_commit=str(payload["data_source_commit"]),
        db_url_env=str(payload["db_url_env"]),
        assignments_sha256=str(payload["assignments_sha256"]),
        cohort_sql_sha256=str(payload["cohort_sql_sha256"]),
        random_seed=int(payload["random_seed"]),
        n_folds=int(payload["n_folds"]),
        expected_shots=int(payload["expected_shots"]),
        expected_matches=int(payload["expected_matches"]),
        expected_fold_sizes=fold_sizes,
        bin_count=int(payload["bin_count"]),
        results_csv=str(payload["results_csv"]),
        published_wp2_5_metrics=str(payload["published_wp2_5_metrics"]),
        input_config_path=str(path),
        require_clean_provenance=bool(payload["require_clean_provenance"]),
        model_family=str(payload["model_family"]),
        dataset_id=str(payload["dataset_id"]),
        split_strategy=str(payload["split_strategy"]),
        target=str(scientific_contract["target"]),
        feature_set=str(scientific_contract["feature_set"]),
        feature_columns=tuple(cast(list[str], scientific_contract["feature_columns"])),
    )


def read_nvidia_driver_version() -> str:
    """Read the installed NVIDIA driver through a bounded, read-only nvidia-smi query."""
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=driver_version",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"cannot read NVIDIA driver version with nvidia-smi: {exc}") from exc
    versions = {line.strip() for line in completed.stdout.splitlines() if line.strip()}
    if len(versions) != 1:
        raise RuntimeError(
            "nvidia-smi returned no single consistent NVIDIA driver version for the CUDA run"
        )
    version = versions.pop()
    if re.fullmatch(r"\d+(?:\.\d+)+", version) is None:
        raise RuntimeError(f"nvidia-smi returned an invalid NVIDIA driver version: {version!r}")
    return version


def _runtime_fingerprint(provenance: Provenance, device: torch.device) -> dict[str, object]:
    runtime = dict(provenance.runtime_fingerprint)
    runtime.update(
        {
            "torch_version": torch.__version__,
            "torch_cuda_version": torch.version.cuda,
            "requested_device": device.type,
            "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
            "cudnn_benchmark": torch.backends.cudnn.benchmark,
            "cudnn_deterministic": torch.backends.cudnn.deterministic,
            "fp32_precision": torch.backends.fp32_precision,  # type: ignore[attr-defined]
            "cuda_matmul_fp32_precision": torch.backends.cuda.matmul.fp32_precision,
            "cudnn_fp32_precision": torch.backends.cudnn.fp32_precision,
            "pythonhashseed": os.environ.get("PYTHONHASHSEED"),
            "mkl_num_threads": os.environ.get("MKL_NUM_THREADS"),
            "cublas_workspace_config": os.environ.get("CUBLAS_WORKSPACE_CONFIG"),
            "torch_num_threads": torch.get_num_threads(),
            "torch_num_interop_threads": torch.get_num_interop_threads(),
        }
    )
    if device.type == "cuda":
        runtime.update(
            {
                "cuda_device_name": torch.cuda.get_device_name(0),
                "cuda_compute_capability": list(torch.cuda.get_device_capability(0)),
                "cuda_device_count": torch.cuda.device_count(),
                "cudnn_version": torch.backends.cudnn.version(),  # type: ignore[no-untyped-call]
                "nvidia_driver_version": read_nvidia_driver_version(),
            }
        )
    return runtime


def apply_provenance(
    config: MlpRunConfig, provenance: Provenance, device: torch.device
) -> MlpRunConfig:
    return replace(
        config,
        code_commit=provenance.code_commit,
        reproduction_commit=provenance.reproduction_commit,
        input_config_path=provenance.input_config_path,
        input_config_sha256=provenance.input_config_sha256,
        uv_lock_sha256=provenance.uv_lock_sha256,
        runtime_fingerprint=_runtime_fingerprint(provenance, device),
    )


def run_protocol(
    rows: Sequence[ShotRow],
    *,
    device: torch.device,
    published_metrics_path: Path | None,
    epochs: int = EPOCHS,
) -> Wp26RunResult:
    """Run OOF comparison, freeze selection, then and only then refit all development rows."""
    rows_list = list(rows)
    prepared = prepare_shipped_folds(rows_list, n_folds=5)
    inherited = reproduce_inherited_candidates(rows_list, prepared)
    if published_metrics_path is not None:
        published = json.loads(published_metrics_path.read_text(encoding="utf-8"))["candidates"]
        for key in (
            "constant",
            "geometry_logistic",
            "full_logistic",
            "full_minus_presence",
            "hist_gbm",
        ):
            assert_metrics_reproduce_to_12_decimals(inherited[key], published[key], key)

    mlp_oof = run_mlp_oof(prepared.folds, device=device, epochs=epochs)
    candidates: dict[str, Mapping[str, object]] = dict(inherited)
    candidates[MLP_KEY] = mlp_oof.metrics
    chains = selection_chains(candidates)
    # Selection is now frozen. Nothing below this line can alter candidates, OOF evidence or chains.
    selection_frozen = str(chains["chain_b"]["selection_incumbent"])

    final_scaler = fit_scaler(rows_list)
    full_matrix, final_columns = encode_rows(rows_list, prepared.vocabulary, final_scaler)
    if tuple(final_columns) != prepared.all_columns:
        raise ValueError("final-refit encoder columns differ from OOF feature contract")
    selected_matrix = full_matrix[:, list(prepared.selected_indices)]
    targets = np.asarray([row.y for row in rows_list], dtype=np.int_)
    final_fit = fit_mlp(
        selected_matrix,
        targets,
        selected_matrix,
        targets,
        device=device,
        epochs=epochs,
    )
    if selection_frozen != str(chains["chain_b"]["selection_incumbent"]):
        raise RuntimeError("final refit changed the frozen OOF selection")
    return Wp26RunResult(
        prepared=prepared,
        candidates=candidates,
        chains=chains,
        mlp_oof=mlp_oof,
        final_scaler=final_scaler,
        final_fit=final_fit,
    )


def _history_payload(result: Wp26RunResult) -> dict[str, object]:
    return {
        "diagnostic_only": True,
        "selection_epoch": EPOCHS,
        "folds": [
            [
                {
                    "epoch": item.epoch,
                    "train_loss": item.train_loss,
                    "validation_loss": item.validation_loss,
                    "train_samples": item.train_samples,
                    "validation_samples": item.validation_samples,
                }
                for item in history
            ]
            for history in result.mlp_oof.histories
        ],
        "final_refit_training_loss": [item.train_loss for item in result.final_fit.history],
    }


def _base_metrics(
    rows: Sequence[ShotRow], result: Wp26RunResult, config: MlpRunConfig, device: torch.device
) -> dict[str, object]:
    ordered_oof: list[dict[str, object]] = []
    for fold, probabilities in enumerate(result.mlp_oof.probabilities_by_fold):
        validation_rows = [row for row in rows if row.fold == fold]
        ordered_oof.extend(
            {"fold": fold, "shot_id": row.shot_id, "probability": float(probability)}
            for row, probability in zip(validation_rows, probabilities, strict=True)
        )
    return {
        "experiment_id": config.experiment_id,
        "code_commit": config.code_commit,
        "reproduction_commit": config.reproduction_commit,
        "data_source_commit": config.data_source_commit,
        "input_config_path": config.input_config_path,
        "input_config_sha256": config.input_config_sha256,
        "uv_lock_sha256": config.uv_lock_sha256,
        "dataset_id": config.dataset_id,
        "split_strategy": config.split_strategy,
        "target": config.target,
        "feature_set": config.feature_set,
        "feature_columns": list(config.feature_columns or result.prepared.selected_columns),
        "cohort_sql_sha256": config.cohort_sql_sha256,
        "assignments_sha256": config.assignments_sha256,
        "runtime_fingerprint": config.runtime_fingerprint,
        "canonical_device": device.type,
        "n_rows": len(rows),
        "n_matches": len({row.match_id for row in rows}),
        "model_family": config.model_family,
        "artifact_candidate": MLP_KEY,
        "selection_incumbent": result.chains["chain_b"]["selection_incumbent"],
        "candidates": result.candidates,
        "replacement_chain_a": result.chains["chain_a"],
        "replacement_chain_b": result.chains["chain_b"],
        "shipped_feature_columns": list(result.prepared.selected_columns),
        "vocabulary": result.prepared.vocabulary.as_dict(),
        "fold_parameter_digests": list(result.mlp_oof.parameter_digests),
        "ordered_oof_predictions": ordered_oof,
        "final_refit_rows": len(rows),
        "final_refit_after_selection": True,
    }


def write_canonical_measurement(
    rows: Sequence[ShotRow], result: Wp26RunResult, config: MlpRunConfig
) -> Path:
    """Persist canonical CPU evidence only under the ignored artifact tree."""
    artifact_dir = abs_path(config.artifacts_dir)
    weights_path = artifact_dir / "weights.pt"
    metadata_path = artifact_dir / "metadata.json"
    selection_incumbent = str(result.chains["chain_b"]["selection_incumbent"])
    metadata = save_mlp_artifact(
        model=result.final_fit.model,
        weights_path=weights_path,
        metadata_path=metadata_path,
        experiment_id=config.experiment_id,
        artifact_candidate=MLP_KEY,
        selection_incumbent=selection_incumbent,
        scaler=result.final_scaler,
        vocabulary=result.prepared.vocabulary,
        all_columns=result.prepared.all_columns,
        selected_indices=result.prepared.selected_indices,
        provenance={
            "code_commit": config.code_commit,
            "reproduction_commit": config.reproduction_commit,
            "data_source_commit": config.data_source_commit,
            "assignments_sha256": config.assignments_sha256,
            "cohort_sql_sha256": config.cohort_sql_sha256,
            "input_config_sha256": config.input_config_sha256,
            "uv_lock_sha256": config.uv_lock_sha256,
        },
    )
    metrics = _base_metrics(rows, result, config, torch.device("cpu"))
    metrics.update(
        {
            "weights_path": record_path(weights_path),
            "weights_sha256": metadata["weights_sha256"],
            "parameter_digest": metadata["parameter_digest"],
            "preprocessing_digest": metadata["preprocessing_digest"],
            "model_pickle_sha256": "n/a",
        }
    )
    output = artifact_dir / "evidence-staging"
    output.mkdir(parents=True, exist_ok=True)
    (output / "metrics.json").write_bytes(canonical_metrics_json(metrics))
    (output / "training-history.json").write_bytes(canonical_metrics_json(_history_payload(result)))
    config_record = {
        **config.__dict__,
        "expected_fold_sizes": dict(config.expected_fold_sizes),
    }
    (output / "config.json").write_bytes(canonical_metrics_json(config_record))
    manifest = {
        "artifact_schema_version": metadata["artifact_schema_version"],
        "experiment_id": config.experiment_id,
        "artifact_candidate": MLP_KEY,
        "selection_incumbent": selection_incumbent,
        "weights_path": record_path(weights_path),
        "metadata_path": record_path(metadata_path),
        "weights_sha256": metadata["weights_sha256"],
        "parameter_digest": metadata["parameter_digest"],
        "preprocessing_digest": metadata["preprocessing_digest"],
        "architecture": metadata["architecture"],
        "selected_columns": metadata["selected_columns"],
        "provenance": metadata["provenance"],
        "recreation_command": (
            "uv run poe train-mlp --config experiments/run-configs/wp2_6-pytorch-mlp.json "
            "--device cpu"
        ),
    }
    (output / "artifact-manifest.json").write_bytes(canonical_metrics_json(manifest))
    return output


def _load_json_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected a JSON object at {path}")
    return cast(dict[str, object], payload)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _recreation_commands(
    config: Mapping[str, object],
    qualification: Mapping[str, object],
    canonical_metrics_path: Path,
    canonical_history_path: Path,
    qualification_path: Path,
) -> dict[str, object]:
    base = f"--config {record_path(str(config['input_config_path']))}"
    source_paths = cast(Mapping[str, Sequence[str]], qualification["source_payload_paths"])
    canonical_metrics = record_path(canonical_metrics_path)
    return {
        "canonical_cpu_measurement": f"uv run poe train-mlp {base} --device cpu",
        "cpu_reproduction": [
            f"uv run poe train-mlp {base} --device cpu --no-write "
            f"--canonical-metrics {canonical_metrics} --reproduction-output {path}"
            for path in source_paths["cpu"]
        ],
        "cuda_qualification": [
            f"uv run poe train-mlp {base} --device cuda "
            f"--canonical-metrics {canonical_metrics} --qualification-output {path}"
            for path in source_paths["cuda"]
        ],
        "finalize_and_publish": (
            "uv run poe qualify-mlp "
            + " ".join(f"--cpu-run {path}" for path in source_paths["cpu"])
            + " "
            + " ".join(f"--cuda-run {path}" for path in source_paths["cuda"])
            + f" --canonical-metrics {canonical_metrics} "
            f"--canonical-history {record_path(canonical_history_path)} "
            f"--output {record_path(qualification_path)}"
        ),
    }


def publish_qualified_experiment(
    *,
    canonical_metrics_path: Path,
    canonical_history_path: Path,
    qualification_path: Path,
) -> None:
    """Publish tracked records and the ledger only after qualification has succeeded."""
    metrics = _load_json_object(canonical_metrics_path)
    history = _load_json_object(canonical_history_path)
    qualification_bytes = qualification_path.read_bytes()
    qualification = cast(dict[str, object], json.loads(qualification_bytes))
    config_path = canonical_metrics_path.parent / "config.json"
    manifest_path = canonical_metrics_path.parent / "artifact-manifest.json"
    config = _load_json_object(config_path)
    manifest = _load_json_object(manifest_path)
    identity = cast(Mapping[str, object], qualification.get("artifact_identity", {}))
    for key in ("weights_sha256", "parameter_digest", "preprocessing_digest"):
        if identity.get(key) != metrics.get(key) or manifest.get(key) != metrics.get(key):
            raise RuntimeError(f"qualification/canonical artifact identity disagrees on {key}")
    if qualification.get("frozen_canonical_cpu_selection") != metrics.get("selection_incumbent"):
        raise RuntimeError("qualification selection differs from canonical CPU selection")
    cpu_payload = cast(Mapping[str, object], qualification["canonical_cpu_reproduction"])
    cuda_payload = cast(Mapping[str, object], qualification["cuda_qualification"])
    qualification_sha = _sha256_bytes(qualification_bytes)
    output = abs_path(str(config["out_dir"]))
    output.mkdir(parents=True, exist_ok=True)
    final_qualification_path = output / "cuda-qualification.json"
    commands = _recreation_commands(
        config,
        qualification,
        canonical_metrics_path,
        canonical_history_path,
        qualification_path,
    )
    lifecycle = {
        "qualification_record_path": record_path(final_qualification_path),
        "qualification_sha256": qualification_sha,
        "canonical_cpu_runtime": metrics["runtime_fingerprint"],
        "cpu_reproduction_runtime": cpu_payload["runtime_fingerprint"],
        "cuda_qualification_runtime": cuda_payload["runtime_fingerprint"],
        "recreation_commands": commands,
    }
    metrics.update(lifecycle)
    manifest.update(lifecycle)
    (output / "metrics.json").write_bytes(canonical_metrics_json(metrics))
    (output / "training-history.json").write_bytes(canonical_metrics_json(history))
    (output / "config.json").write_bytes(canonical_metrics_json(config))
    (output / "artifact-manifest.json").write_bytes(canonical_metrics_json(manifest))
    final_qualification_path.write_bytes(qualification_bytes)
    notes_path = output / "notes.md"
    notes_path.write_text(
        "# WP2.6 PyTorch MLP\n\n"
        "Evidence was published only after CPU reproduction and CUDA qualification passed.\n",
        encoding="utf-8",
        newline="\n",
    )
    candidates = cast(Mapping[str, Mapping[str, object]], metrics["candidates"])
    candidate = candidates[MLP_KEY]
    pooled = cast(Mapping[str, object], candidate["pooled_oof"])
    chain_a = cast(Mapping[str, object], metrics["replacement_chain_a"])
    replace_results_csv(
        str(config["results_csv"]),
        {
            "experiment_id": metrics["experiment_id"],
            "date_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "code_commit": metrics["code_commit"],
            "reproduction_commit": metrics["reproduction_commit"],
            "data_source_commit": metrics["data_source_commit"],
            "dataset_id": config["dataset_id"],
            "query_hash": metrics["cohort_sql_sha256"],
            "input_config_sha256": metrics["input_config_sha256"],
            "uv_lock_sha256": metrics["uv_lock_sha256"],
            "shipped_feature_set": "geometry+categoricals",
            "split_strategy": config["split_strategy"],
            "model": "pytorch-mlp-16-8-1",
            "seed": SEED,
            "primary_metric": "mean_log_loss",
            "primary_value": candidate["mean_log_loss"],
            "brier": pooled["brier"],
            "log_loss": pooled["log_loss"],
            "protocol_incumbent": chain_a["protocol_incumbent"],
            "shipped_candidate": metrics["selection_incumbent"],
            "d5_include": "n/a",
            "shipped_best_c": "n/a",
            "model_pickle_sha256": "n/a",
            "calibration_summary": f"maxdev={candidate['max_abs_deviation_supported']}",
            "status": "complete",
            "notes_path": record_path(notes_path),
        },
    )


def _qualification_payload(
    rows: Sequence[ShotRow],
    result: Wp26RunResult,
    config: MlpRunConfig,
    canonical_metrics_path: Path,
    device: torch.device,
) -> dict[str, object]:
    canonical = cast(
        Mapping[str, object], json.loads(canonical_metrics_path.read_text(encoding="utf-8"))
    )
    frozen_selection = str(canonical["selection_incumbent"])
    artifact_reload = _artifact_reload_payload(rows, canonical_metrics_path, device)
    measured = _base_metrics(rows, result, config, device)
    return {
        "qualification_only": device.type == "cuda",
        "selection_effect": "none" if device.type == "cuda" else "canonical_reproduction",
        "frozen_canonical_cpu_selection": frozen_selection,
        "runtime_fingerprint": config.runtime_fingerprint,
        "mlp_oof_metrics": result.mlp_oof.metrics,
        "ordered_oof_predictions": measured["ordered_oof_predictions"],
        "training_history": _history_payload(result),
        "fold_parameter_digests": list(result.mlp_oof.parameter_digests),
        "final_parameter_digest": result.final_fit.parameter_digest,
        "artifact_reload": artifact_reload,
    }


def _artifact_reload_payload(
    rows: Sequence[ShotRow], canonical_metrics_path: Path, device: torch.device
) -> dict[str, object]:
    canonical = cast(
        Mapping[str, object], json.loads(canonical_metrics_path.read_text(encoding="utf-8"))
    )
    manifest_path = canonical_metrics_path.parent / "artifact-manifest.json"
    manifest = cast(Mapping[str, object], json.loads(manifest_path.read_text(encoding="utf-8")))
    for key in ("weights_sha256", "parameter_digest", "preprocessing_digest"):
        if canonical[key] != manifest[key]:
            raise RuntimeError(f"canonical metrics/manifest disagree on {key}")
    artifact = load_mlp_artifact(
        abs_path(str(manifest["weights_path"])),
        abs_path(str(manifest["metadata_path"])),
        device=device,
        expected_preprocessing_digest=str(manifest["preprocessing_digest"]),
    )
    if artifact.weights_sha256 != str(manifest["weights_sha256"]):
        raise RuntimeError("fresh artifact reload disagrees on weights identity")
    if artifact.parameter_digest != str(manifest["parameter_digest"]):
        raise RuntimeError("fresh artifact reload disagrees on parameter identity")
    probabilities = infer_mlp(artifact, rows)
    return {
        "device": device.type,
        "weights_sha256": artifact.weights_sha256,
        "parameter_digest": artifact.parameter_digest,
        "preprocessing_digest": artifact.preprocessing_digest,
        "ordered_shot_ids": [row.shot_id for row in rows],
        "probabilities": probabilities.tolist(),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="touchline.modeling.train_mlp")
    parser.add_argument("--config", required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), required=True)
    parser.add_argument("--assignments-csv", default=str(CSV_PATH))
    parser.add_argument("--cohort-sql", default=str(COHORT_SQL_PATH))
    parser.add_argument("--code-commit", default=None)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--qualification-output", default=None)
    parser.add_argument("--reproduction-output", default=None)
    parser.add_argument("--canonical-metrics", default=None)
    args = parser.parse_args(argv)

    try:
        check_pre_registration()
        device = resolve_device(args.device)
        configure_deterministic_runtime()
        config = load_config(Path(args.config))
        if config.require_clean_provenance and args.code_commit is not None:
            raise ValueError("--code-commit is forbidden for clean-provenance evidence")
        provenance = resolve_provenance(config, code_commit_override=args.code_commit)
        config = apply_provenance(config, provenance, device)
        db_url = os.environ.get(config.db_url_env) or os.environ.get("TOUCHLINE_DB_URL")
        if not db_url:
            raise RuntimeError(f"neither {config.db_url_env} nor TOUCHLINE_DB_URL is set")
        assignment_bytes = Path(args.assignments_csv).read_bytes()
        verify_assignments_csv(assignment_bytes, config.assignments_sha256)
        assignments = parse_match_assignments(assignment_bytes.decode("utf-8"))
        cohort_sql = verify_cohort_sql(Path(args.cohort_sql).read_bytes(), config.cohort_sql_sha256)
        connection = open_db(db_url, os.environ.get("TOUCHLINE_TRAIN_SCHEMA"))
        try:
            rows = load_development_cohort(connection, cohort_sql, assignments)
        finally:
            connection.close()
        verify_development_anchor(
            rows,
            expected_shots=config.expected_shots,
            expected_matches=config.expected_matches,
            expected_fold_sizes=config.expected_fold_sizes,
        )
        result = run_protocol(
            rows,
            device=device,
            published_metrics_path=abs_path(config.published_wp2_5_metrics),
        )
        if device.type == "cpu":
            if args.no_write:
                if args.reproduction_output is None or args.canonical_metrics is None:
                    raise ValueError(
                        "CPU --no-write reproduction requires --reproduction-output and "
                        "--canonical-metrics"
                    )
                payload = _qualification_payload(
                    rows,
                    result,
                    config,
                    Path(args.canonical_metrics),
                    device,
                )
                canonical = json.loads(Path(args.canonical_metrics).read_text(encoding="utf-8"))
                if payload["final_parameter_digest"] != canonical["parameter_digest"]:
                    raise RuntimeError(
                        "fresh CPU final-refit parameter digest differs from canonical evidence"
                    )
                reproduction_output = Path(args.reproduction_output)
                reproduction_output.parent.mkdir(parents=True, exist_ok=True)
                reproduction_output.write_bytes(canonical_metrics_json(payload))
            else:
                staging = write_canonical_measurement(rows, result, config)
                print(f"Canonical measurement staged under {staging}")
        else:
            if args.qualification_output is None or args.canonical_metrics is None:
                raise ValueError(
                    "CUDA qualification requires --qualification-output and --canonical-metrics"
                )
            payload = _qualification_payload(
                rows,
                result,
                config,
                Path(args.canonical_metrics),
                device,
            )
            qualification_output = Path(args.qualification_output)
            qualification_output.parent.mkdir(parents=True, exist_ok=True)
            qualification_output.write_bytes(canonical_metrics_json(payload))
        digest_payload = (
            payload
            if (args.no_write or device.type == "cuda")
            else _base_metrics(rows, result, config, device)
        )
        digest = hashlib.sha256(canonical_metrics_json(digest_payload)).hexdigest()
        print(f"WP2.6 {device.type} protocol complete; canonical payload SHA-256 {digest}")
        return 0
    except (PreRegistrationError, MlpConfigError, OSError, RuntimeError, ValueError) as exc:
        print(f"Refusing to run WP2.6: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
