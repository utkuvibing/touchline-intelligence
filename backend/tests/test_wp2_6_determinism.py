"""Process-start, device and pre-registration gates for WP2.6."""

from __future__ import annotations

import inspect
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

from touchline.modeling.experiment import Provenance
from touchline.modeling.mlp import configure_deterministic_runtime
from touchline.modeling.train_mlp import (
    MlpConfigError,
    PreRegistrationError,
    _runtime_fingerprint,
    check_pre_registration,
    load_config,
    main,
    read_nvidia_driver_version,
    resolve_device,
)
from touchline.pytorch_bootstrap import REQUIRED_PROCESS_ENV, pin_process_environment

ROOT = Path(__file__).resolve().parents[2]


def test_bootstrap_pins_every_process_start_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in REQUIRED_PROCESS_ENV:
        monkeypatch.delenv(name, raising=False)
    pin_process_environment(cuda=True)
    assert os.environ["PYTHONHASHSEED"] == "0"
    assert os.environ["OMP_NUM_THREADS"] == "1"
    assert os.environ["MKL_NUM_THREADS"] == "1"
    assert os.environ["CUBLAS_WORKSPACE_CONFIG"] == ":4096:8"


def test_device_resolution_never_silently_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    assert resolve_device("cpu") == torch.device("cpu")
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    with pytest.raises(RuntimeError, match="CUDA was requested"):
        resolve_device("cuda")
    with pytest.raises(ValueError, match="device must be"):
        resolve_device("auto")


def test_accepted_adr_exposes_the_author_signoff_date() -> None:
    assert check_pre_registration(
        ROOT / "docs/adr/0012-wp2-6-bounded-pytorch-mlp-lifecycle.md"
    ) == "2026-08-09"


def test_committed_config_is_the_exact_pre_registered_contract(tmp_path: Path) -> None:
    config_path = ROOT / "experiments/run-configs/wp2_6-pytorch-mlp.json"
    config = load_config(config_path)
    assert config.random_seed == 0
    assert config.n_folds == 5
    assert config.expected_shots == 2872
    payload = config_path.read_text(encoding="utf-8").replace('"epochs": 200', '"epochs": 201')
    mutated = tmp_path / "mutated.json"
    mutated.write_text(payload, encoding="utf-8")
    with pytest.raises(MlpConfigError, match="training constants"):
        load_config(mutated)


@pytest.mark.parametrize(
    ("needle", "replacement"),
    [
        ('"expected_shots": 2872', '"expected_shots": 2871'),
        ('"expected_matches": 115', '"expected_matches": 114'),
        ('"bin_count": 5', '"bin_count": 4'),
        (
            '"assignments_sha256": '
            '"e2d5517d96aa81d2229e1ef00a3c692f44f280630c3e75b7f6735e7cdc1787d8"',
            '"assignments_sha256": "' + "0" * 64 + '"',
        ),
        (
            '"cohort_sql_sha256": '
            '"301d8a620b60d8da6011c7c4d12ef8108c658df4d923f612c3e3bf9e0427978e"',
            '"cohort_sql_sha256": "' + "1" * 64 + '"',
        ),
        ('"dataset_id": "wp2_3_split_lock"', '"dataset_id": "wrong_dataset"'),
        ('"split_strategy": "wp2_3_tournament_split"', '"split_strategy": "wrong_split"'),
        ('"0": 570', '"0": 569'),
        ('"target": "ShotRow.y"', '"target": "ShotRow.goal"'),
        ('"feature_set": "geometry+categoricals"', '"feature_set": "geometry"'),
        (
            '"published_wp2_5_metrics": '
            '"experiments/shot_quality/exp-20260806-wp2_5-gradient-boosting/metrics.json"',
            '"published_wp2_5_metrics": "wrong-metrics.json"',
        ),
        ('"require_clean_provenance": true', '"require_clean_provenance": false'),
        ('"db_url_env": "TOUCHLINE_FULL_COHORT_DB_URL"', '"db_url_env": "TOUCHLINE_DB_URL"'),
        (
            '"artifacts_dir": "artifacts/models/exp-20260809-wp2_6-pytorch-mlp"',
            '"artifacts_dir": "artifacts/models/wrong"',
        ),
        (
            '"out_dir": "experiments/shot_quality/exp-20260809-wp2_6-pytorch-mlp"',
            '"out_dir": "experiments/wrong"',
        ),
        ('"results_csv": "experiments/results.csv"', '"results_csv": "results-wrong.csv"'),
        (
            '"experiment_id": "exp-20260809-wp2_6-pytorch-mlp"',
            '"experiment_id": "wrong-experiment"',
        ),
    ],
)
def test_changed_scientific_config_fails_before_data_access(
    tmp_path: Path,
    needle: str,
    replacement: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = ROOT / "experiments/run-configs/wp2_6-pytorch-mlp.json"
    mutated = tmp_path / "mutated.json"
    mutated.write_text(
        config_path.read_text(encoding="utf-8").replace(needle, replacement), encoding="utf-8"
    )
    monkeypatch.setattr("touchline.modeling.train_mlp.check_pre_registration", lambda: "2026-08-09")
    monkeypatch.setenv("TOUCHLINE_FULL_COHORT_DB_URL", "postgresql://sentinel.invalid/touchline")
    monkeypatch.setattr(
        "touchline.modeling.train_mlp.configure_deterministic_runtime", lambda: None
    )
    monkeypatch.setattr(
        "touchline.modeling.train_mlp.open_db",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("data access occurred")),
    )
    monkeypatch.setattr(
        "touchline.modeling.train_mlp.resolve_provenance",
        lambda *_args, **_kwargs: Provenance(
            code_commit="code",
            reproduction_commit="code",
            input_config_path=str(mutated),
            input_config_sha256="c" * 64,
            uv_lock_sha256="u" * 64,
            runtime_fingerprint={},
            data_source_commit="data",
        ),
    )
    assert main(["--config", str(mutated), "--device", "cpu"]) == 1


def test_fresh_bootstrap_process_imports_torch_only_after_environment_pin() -> None:
    probe = (
        "import os,sys; from touchline.pytorch_bootstrap import pin_process_environment; "
        "assert 'torch' not in sys.modules; pin_process_environment(cuda=False); import torch; "
        "assert os.environ['PYTHONHASHSEED']=='0'; assert os.environ['OMP_NUM_THREADS']=='1'; "
        "assert os.environ['MKL_NUM_THREADS']=='1'"
    )
    result = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, check=False)
    assert result.returncode == 0


def test_canonical_cpu_lifecycle_reproduces_in_two_fresh_processes() -> None:
    environment = dict(os.environ)
    environment.update({"PYTHONHASHSEED": "0", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"})
    environment["PYTHONPATH"] = str(ROOT / "backend/tests")
    first = subprocess.run(
        [sys.executable, "-m", "support.wp26_cpu_probe"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    second = subprocess.run(
        [sys.executable, "-m", "support.wp26_cpu_probe"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert first.stdout == second.stdout


def test_deterministic_algorithms_are_hard_errors_in_the_runtime_policy() -> None:
    source = inspect.getsource(configure_deterministic_runtime)
    assert "torch.use_deterministic_algorithms(True, warn_only=False)" in source


def test_nvidia_driver_query_is_read_only_and_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], bool]] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append((command, bool(kwargs.get("shell", False))))
        return SimpleNamespace(stdout="610.62\n")

    monkeypatch.setattr("touchline.modeling.train_mlp.subprocess.run", fake_run)
    assert read_nvidia_driver_version() == "610.62"
    assert calls == [
        (
            [
                "nvidia-smi",
                "--query-gpu=driver_version",
                "--format=csv,noheader,nounits",
            ],
            False,
        )
    ]


def test_cuda_runtime_fingerprint_records_cudnn_and_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("touchline.modeling.train_mlp.read_nvidia_driver_version", lambda: "610.62")
    monkeypatch.setattr(torch.backends.cudnn, "version", lambda: 9100)
    provenance = Provenance(
        code_commit="code",
        reproduction_commit="code",
        input_config_path="config.json",
        input_config_sha256="c" * 64,
        uv_lock_sha256="u" * 64,
        runtime_fingerprint={},
        data_source_commit="data",
    )
    monkeypatch.setattr(torch.cuda, "get_device_name", lambda _index: "RTX 4050")
    monkeypatch.setattr(torch.cuda, "get_device_capability", lambda _index: (8, 9))
    monkeypatch.setattr(torch.cuda, "device_count", lambda: 1)
    runtime = _runtime_fingerprint(provenance, torch.device("cuda"))
    assert runtime["cudnn_version"] == 9100
    assert runtime["nvidia_driver_version"] == "610.62"
