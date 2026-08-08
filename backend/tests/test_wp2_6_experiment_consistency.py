"""WP2.6 writer preserves the frozen ledger and authoritative MLP identities."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import torch
from support.wp26_synthetic import wp26_rows

from touchline.modeling.experiment import RESULTS_CSV_HEADER
from touchline.modeling.metrics import canonical_metrics_json
from touchline.modeling.train_mlp import (
    MlpRunConfig,
    publish_qualified_experiment,
    run_protocol,
    write_canonical_measurement,
)


def _config(tmp_path: Path) -> MlpRunConfig:
    results = tmp_path / "results.csv"
    historical = ",".join(["historical"] + ["kept"] * 24)
    results.write_text(RESULTS_CSV_HEADER + "\n" + historical + "\n", encoding="utf-8")
    return MlpRunConfig(
        experiment_id="synthetic-wp26",
        out_dir=str(tmp_path / "experiment"),
        artifacts_dir=str(tmp_path / "artifact"),
        code_commit="code",
        reproduction_commit="code",
        data_source_commit="data",
        db_url_env="TEST_DB",
        assignments_sha256="a" * 64,
        cohort_sql_sha256="b" * 64,
        random_seed=0,
        n_folds=5,
        expected_shots=400,
        expected_matches=100,
        expected_fold_sizes={fold: 80 for fold in range(5)},
        bin_count=5,
        results_csv=str(results),
        published_wp2_5_metrics="unused",
        input_config_path="synthetic.json",
        input_config_sha256="c" * 64,
        uv_lock_sha256="d" * 64,
        runtime_fingerprint={"requested_device": "cpu"},
        require_clean_provenance=False,
        model_family="pytorch-mlp",
    )


def test_canonical_measurement_stays_ignored_until_qualification(tmp_path: Path) -> None:
    rows = wp26_rows()
    result = run_protocol(rows, device=torch.device("cpu"), published_metrics_path=None, epochs=2)
    result = replace(
        result,
        chains={
            **result.chains,
            "chain_b": {
                **result.chains["chain_b"],
                "selection_incumbent": "full_minus_presence",
            },
        },
    )
    config = _config(tmp_path)
    original_ledger = Path(config.results_csv).read_bytes()
    staging = write_canonical_measurement(rows, result, config)
    assert staging == Path(config.artifacts_dir) / "evidence-staging"
    assert not Path(config.out_dir).exists()
    assert Path(config.results_csv).read_bytes() == original_ledger


def test_publication_uses_n_a_and_binds_qualification_identity(tmp_path: Path) -> None:
    rows = wp26_rows()
    result = run_protocol(rows, device=torch.device("cpu"), published_metrics_path=None, epochs=2)
    result = replace(
        result,
        chains={
            **result.chains,
            "chain_b": {
                **result.chains["chain_b"],
                "selection_incumbent": "full_minus_presence",
            },
        },
    )
    config = _config(tmp_path)
    staging = write_canonical_measurement(rows, result, config)
    metrics = json.loads((staging / "metrics.json").read_text(encoding="utf-8"))
    qualification = {
        "qualification_schema_version": 1,
        "frozen_canonical_cpu_selection": metrics["selection_incumbent"],
        "artifact_identity": {
            key: metrics[key]
            for key in ("weights_sha256", "parameter_digest", "preprocessing_digest")
        },
        "canonical_cpu_reproduction": {"runtime_fingerprint": {"requested_device": "cpu"}},
        "cuda_qualification": {"runtime_fingerprint": {"requested_device": "cuda"}},
        "source_payload_paths": {
            "cpu": [str(staging / "cpu-1.json"), str(staging / "cpu-2.json")],
            "cuda": [str(staging / "cuda-1.json"), str(staging / "cuda-2.json")],
        },
    }
    qualification_path = staging / "cuda-qualification.json"
    qualification_path.write_bytes(canonical_metrics_json(qualification))
    publish_qualified_experiment(
        canonical_metrics_path=staging / "metrics.json",
        canonical_history_path=staging / "training-history.json",
        qualification_path=qualification_path,
    )
    output = Path(config.out_dir)
    metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "artifact-manifest.json").read_text(encoding="utf-8"))
    metadata = json.loads(
        (Path(config.artifacts_dir) / "metadata.json").read_text(encoding="utf-8")
    )
    assert metrics["model_pickle_sha256"] == "n/a"
    assert manifest["artifact_candidate"] == "pytorch_mlp"
    assert metadata["artifact_candidate"] == "pytorch_mlp"
    assert manifest["selection_incumbent"] == metrics["selection_incumbent"]
    for key in ("weights_sha256", "parameter_digest", "preprocessing_digest"):
        assert metrics[key] == manifest[key] == metadata[key]
    assert metrics["qualification_sha256"] == manifest["qualification_sha256"]
    assert metrics["qualification_record_path"].endswith("cuda-qualification.json")
    assert manifest["canonical_cpu_runtime"]["requested_device"] == "cpu"
    assert manifest["cpu_reproduction_runtime"]["requested_device"] == "cpu"
    assert manifest["cuda_qualification_runtime"]["requested_device"] == "cuda"
    assert set(manifest["recreation_commands"]) == {
        "canonical_cpu_measurement",
        "cpu_reproduction",
        "cuda_qualification",
        "finalize_and_publish",
    }
    lines = Path(config.results_csv).read_text(encoding="utf-8").splitlines()
    assert lines[0] == RESULTS_CSV_HEADER
    assert lines[1].startswith("historical,kept,")
    keys = RESULTS_CSV_HEADER.split(",")
    row = dict(zip(keys, lines[2].split(","), strict=True))
    assert row["model_pickle_sha256"] == "n/a"
    assert metrics["weights_sha256"] not in lines[2]
