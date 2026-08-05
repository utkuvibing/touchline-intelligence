"""Unit contracts for WP2.4 reproduction provenance and the sanitized runtime fingerprint.

Covers (blocking corrections 3 and 4):

- the code/reproduction commit is derived from the repository revision, never trusted from the
  config JSON (a git-revision seam injects a deterministic SHA for synthetic runs);
- a dirty tracked working tree fails loudly before evidence can be produced, while untracked files
  are allowed;
- the ``--code-commit`` override is forbidden when ``require_clean_provenance`` is set;
- ``input_config_sha256`` matches the exact input-config bytes and the input config is never
  overwritten by the run;
- ``uv_lock_sha256`` matches ``uv.lock``;
- the runtime fingerprint is deterministic and sanitized (no library filepaths, no usernames, no
  drive letters, no DSNs) and records Python/platform/NumPy/scikit-learn/SciPy/BLAS.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

import pytest

from touchline.modeling.logistic import L2_C_GRID
from touchline.modeling.preprocessing import ShotRow
from touchline.modeling.train import (
    ROOT,
    ProvenanceError,
    RunConfig,
    _runtime_fingerprint,
    resolve_provenance,
)

FAKE_GIT_COMMIT = "f00dcafe00000000000000000000000000000000"


def _config(tmp_path: Path, *, clean_required: bool) -> RunConfig:
    return RunConfig(
        experiment_id="provenance-test",
        out_dir=str(tmp_path / "exp"),
        artifacts_dir=str(tmp_path / "artifacts"),
        code_commit="trust-me-from-json",
        reproduction_commit="unset",
        data_source_commit="b0bc9f22dd77c206ddedc1d742893b3bbe64baec",
        input_config_path=str(tmp_path / "input-config.json"),
        input_config_sha256="",
        uv_lock_sha256="",
        runtime_fingerprint={},
        require_clean_provenance=clean_required,
        db_url_env="TOUCHLINE_DB_URL",
        assignments_sha256="0" * 64,
        cohort_sql_sha256="0" * 64,
        c_grid=L2_C_GRID,
        random_seed=0,
        n_folds=5,
        expected_shots=100,
        expected_matches=5,
        expected_fold_sizes={0: 20, 1: 20, 2: 20, 3: 20, 4: 20},
        bin_count=5,
        results_csv=str(tmp_path / "results.csv"),
    )


def _fake_git(commit: str = FAKE_GIT_COMMIT, status: str = "") -> object:
    def fake(root: Path, *args: str) -> str:
        if args and args[0] == "rev-parse":
            return commit
        if args and args[0] == "status":
            return status
        raise AssertionError(f"unexpected git args: {args}")

    return fake


def test_code_commit_is_derived_from_the_repository_revision_not_the_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import touchline.modeling.train as train_mod

    monkeypatch.setattr(train_mod, "_git", _fake_git(commit=FAKE_GIT_COMMIT, status=""))
    input_cfg = tmp_path / "input-config.json"
    input_cfg.write_text("{}\n", encoding="utf-8")
    config = _config(tmp_path, clean_required=True)
    resolved, provenance = resolve_provenance(config)
    assert provenance.code_commit == FAKE_GIT_COMMIT
    assert resolved.code_commit == FAKE_GIT_COMMIT
    assert provenance.reproduction_commit == FAKE_GIT_COMMIT
    # The JSON-supplied value must never be trusted as the authoritative revision.
    assert provenance.code_commit != config.code_commit


def test_dirty_tracked_tree_fails_loudly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import touchline.modeling.train as train_mod

    monkeypatch.setattr(
        train_mod,
        "_git",
        _fake_git(commit=FAKE_GIT_COMMIT, status=" M backend/src/touchline/modeling/train.py"),
    )
    input_cfg = tmp_path / "input-config.json"
    input_cfg.write_text("{}\n", encoding="utf-8")
    config = _config(tmp_path, clean_required=True)
    with pytest.raises(ProvenanceError):
        resolve_provenance(config)


def test_untracked_files_do_not_dirty_the_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import touchline.modeling.train as train_mod

    monkeypatch.setattr(train_mod, "_git", _fake_git(commit=FAKE_GIT_COMMIT, status="?? IDEA.md"))
    input_cfg = tmp_path / "input-config.json"
    input_cfg.write_text("{}\n", encoding="utf-8")
    config = _config(tmp_path, clean_required=True)
    resolved, _ = resolve_provenance(config)
    assert resolved.code_commit == FAKE_GIT_COMMIT


def test_code_commit_override_is_forbidden_when_clean_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import touchline.modeling.train as train_mod

    monkeypatch.setattr(train_mod, "_git", _fake_git())
    input_cfg = tmp_path / "input-config.json"
    input_cfg.write_text("{}\n", encoding="utf-8")
    config = _config(tmp_path, clean_required=True)
    with pytest.raises(ProvenanceError):
        resolve_provenance(config, code_commit_override="override")


def test_input_config_sha_matches_exact_bytes_and_uv_lock_sha_matches_uv_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import touchline.modeling.train as train_mod

    monkeypatch.setattr(train_mod, "_git", _fake_git())
    input_cfg = tmp_path / "input-config.json"
    input_bytes = b'{"a": 1}\n'
    input_cfg.write_bytes(input_bytes)
    config = _config(tmp_path, clean_required=False)
    _resolved, provenance = resolve_provenance(config, code_commit_override="synthetic")
    assert provenance.input_config_sha256 == hashlib.sha256(input_bytes).hexdigest()
    assert provenance.uv_lock_sha256 == hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest()


def test_write_experiment_never_overwrites_the_committed_input_config(tmp_path: Path) -> None:
    from touchline.modeling.train import run_protocol, write_experiment

    input_cfg = tmp_path / "input-config.json"
    input_bytes = b'{"committed": "input", "path": "portable"}\n'
    input_cfg.write_bytes(input_bytes)
    config = _config(tmp_path, clean_required=False)
    resolved, provenance = resolve_provenance(config, code_commit_override="synthetic")
    rng = __import__("numpy").random.default_rng(3)
    rows = [
        ShotRow(
            shot_id=f"p{fold}-{i}",
            match_id=400 + fold,
            fold=fold,
            competition_id=43,
            season_id=3,
            y=1 if i < 6 else 0,
            distance_to_goal=20.0 + float(rng.normal()),
            visible_goal_angle=0.3 + 0.02 * float(rng.normal()),
            body_part_name="Right Foot",
            technique_name="Normal",
            play_pattern_name="Regular Play",
            first_time=None,
            under_pressure=None,
        )
        for fold in range(5)
        for i in range(12)
    ]
    metrics, bundle = run_protocol(rows, resolved)
    write_experiment(metrics, bundle, resolved)
    assert input_cfg.read_bytes() == input_bytes
    assert metrics["input_config_sha256"] == provenance.input_config_sha256
    assert metrics["input_config_sha256"] == hashlib.sha256(input_bytes).hexdigest()


def test_runtime_fingerprint_is_deterministic_and_sanitized() -> None:
    first = _runtime_fingerprint()
    second = _runtime_fingerprint()
    assert first == second
    for key in (
        "python_implementation",
        "python_version",
        "os",
        "os_release",
        "machine",
        "numpy_version",
        "scipy_version",
        "scikit_learn_version",
        "threadpoolctl_version",
        "threadpool_info",
    ):
        assert key in first
    serialized = json.dumps(first, sort_keys=True)
    assert "filepath" not in serialized
    assert "C:" not in serialized
    assert "\\" not in serialized
    assert not any(
        marker in serialized.lower()
        for marker in (
            "@",
            "token",
            "passwd",
            "password",
            "postgres://",
            "postgresql://",
            "/home/",
            "/users/",
            "temp\\",
        )
    )
    entries = cast(Sequence[Mapping[str, object]], first["threadpool_info"])
    for entry in entries:
        assert isinstance(entry, dict) and "filepath" not in entry
    assert isinstance(first["numpy_version"], str) and first["numpy_version"]
    # Deterministic sorted serialization: re-serialize both and compare bytes.
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
