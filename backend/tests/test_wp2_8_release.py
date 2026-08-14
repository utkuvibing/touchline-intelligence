"""Hermetic WP2.8 contract tests.

These tests use recorded JSON and temporary packet fixtures only.  They never open PostgreSQL,
create a historical checkout, or invoke the WP2.4 training command; that is the separate
acceptance/evidence run.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

import touchline.modeling.wp2_8 as wp2_8
from touchline.modeling.calibration import exact_json_bytes
from touchline.modeling.experiment import ProvenanceError, require_clean_tracked_tree

ROOT = Path(__file__).resolve().parents[2]


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _raw_git_fixture(tmp_path: Path) -> tuple[Path, str, bytes]:
    repository = tmp_path / "historical-repository"
    repository.mkdir()
    subprocess.run(
        ["git", "-C", str(repository), "init", "--quiet"],
        check=True,
        capture_output=True,
    )
    raw_blob = b"lock-content\nsecond-line\n"
    lock_path = repository / "uv.lock"
    lock_path.write_bytes(raw_blob)
    subprocess.run(
        [
            "git",
            "-c",
            "core.autocrlf=false",
            "-C",
            str(repository),
            "add",
            "--",
            "uv.lock",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=WP2.8 fixture",
            "-c",
            "user.email=wp2.8-fixture@example.invalid",
            "-C",
            str(repository),
            "commit",
            "--quiet",
            "-m",
            "raw blob fixture",
        ],
        check=True,
        capture_output=True,
    )
    revision = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return repository, revision, raw_blob


def _fixture_reproduction() -> wp2_8.ReproductionResult:
    comparison = wp2_8.ComparisonResult(
        comparison_mode="exact",
        canonical_json_equal=True,
        artifact_byte_identical=True,
        feature_contract_equal=True,
        metrics_within_tolerance=True,
        metadata_within_tolerance=True,
        comparison_table=(
            {
                "field": "fixture",
                "canonical": 1,
                "regenerated": 1,
                "delta": 0.0,
                "tolerance": 0.0,
                "outcome": "pass",
            },
        ),
    )
    return wp2_8.ReproductionResult(
        environment_fingerprint={
            "os": "Windows",
            "architecture": "AMD64",
            "python_implementation": "CPython",
            "python_version": "3.12.11",
            "uv_version": "0.11.25",
            "uv_lock_sha256": "58c4b2b39cf78d217284784ada544633ea7c145a9a5a0a6c4eb6312eb7ea3902",
            "reproduction_commit": "81d4a56395985cb427fbcd13f38a0eb8c42e8be6",
            "config_sha256": "30d34981d957f2b7c3832b2fe347f10986a6f14e58cca98a4abba673a56b0b0e",
        },
        exact_environment_match=True,
        development_shots=2872,
        development_matches=115,
        development_fold_sizes={"0": 570, "1": 552, "2": 602, "3": 576, "4": 572},
        metrics_sha256="d" * 64,
        artifact_manifest_sha256="e" * 64,
        model_sha256="f" * 64,
        comparison=comparison,
    )


def _synthetic_packet_inputs(
    tmp_path: Path,
) -> tuple[wp2_8.ReleaseConfig, wp2_8.WP24Evidence, wp2_8.WP27Evidence]:
    registered = wp2_8.load_release_config()
    payload = json.loads(json.dumps(registered.payload))
    payload["output_dir"] = "packet"
    config_path = tmp_path / "registered-config.json"
    config_path.write_bytes(exact_json_bytes(payload))
    config = wp2_8.ReleaseConfig(config_path, payload, _sha(config_path))

    def write_fixture(relative: str, content: bytes) -> str:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return _sha(path)

    wp24_config_sha = write_fixture("experiments/wp24-config.json", b"wp24 config\n")
    wp24_resolved_sha = write_fixture("experiments/wp24-resolved-config.json", b"wp24 resolved\n")
    wp24_metrics_sha = write_fixture("experiments/wp24-metrics.json", b"wp24 metrics\n")
    wp24_manifest_sha = write_fixture("experiments/wp24-manifest.json", b"wp24 manifest\n")
    wp24_model_sha = write_fixture("artifacts/wp24/model.pkl", b"wp24 model\n")
    wp24 = wp2_8.WP24Evidence(
        config={},
        metrics={},
        artifact_manifest={},
        config_path="experiments/wp24-config.json",
        config_sha256=wp24_config_sha,
        resolved_config_path="experiments/wp24-resolved-config.json",
        resolved_config_sha256=wp24_resolved_sha,
        metrics_path="experiments/wp24-metrics.json",
        metrics_sha256=wp24_metrics_sha,
        artifact_manifest_path="experiments/wp24-manifest.json",
        artifact_manifest_sha256=wp24_manifest_sha,
        model_path="artifacts/wp24/model.pkl",
        model_sha256=wp24_model_sha,
    )
    wp27_decision_sha = write_fixture(
        "experiments/wp27/calibration-decision.json", b"wp27 decision\n"
    )
    wp27_audit_sha = write_fixture("experiments/wp27/holdout-access-audit.json", b"wp27 audit\n")
    wp27_metrics_sha = write_fixture("experiments/wp27/holdout-metrics.json", b"wp27 metrics\n")
    wp27_record_sha = write_fixture("experiments/wp27/experiment-record.json", b"wp27 record\n")
    wp27 = wp2_8.WP27Evidence(
        decision={},
        audit={},
        metrics={},
        record={},
        decision_path="experiments/wp27/calibration-decision.json",
        audit_path="experiments/wp27/holdout-access-audit.json",
        metrics_path="experiments/wp27/holdout-metrics.json",
        record_path="experiments/wp27/experiment-record.json",
        decision_file_sha256=wp27_decision_sha,
        audit_file_sha256=wp27_audit_sha,
        metrics_file_sha256=wp27_metrics_sha,
        record_file_sha256=wp27_record_sha,
        decision_sha256="2" * 64,
        holdout_membership_sha256="3" * 64,
        execution_provenance_sha256="4" * 64,
        measured_evidence_sha256={
            "experiments/wp27/holdout-metrics.json": wp27_metrics_sha,
            "experiments/wp27/experiment-record.json": wp27_record_sha,
        },
    )
    return config, wp24, wp27


@pytest.mark.parametrize(
    "value",
    [
        "C:/repo/file.json",
        "\\\\server\\share\\file.json",
        "/repo/file.json",
        "~/file.json",
        "../file.json",
        "a\\b.json",
        "a//b.json",
        "a/./b.json",
    ],
)
def test_persisted_paths_reject_machine_local_and_noncanonical_forms(value: str) -> None:
    with pytest.raises(wp2_8.PathContractError):
        wp2_8.validate_repo_relative_path(value)


def test_persisted_paths_accept_only_canonical_repository_relative_posix() -> None:
    assert (
        wp2_8.validate_repo_relative_path("experiments/shot_quality/release.json")
        == "experiments/shot_quality/release.json"
    )


def test_registered_config_rejects_an_absolute_persisted_path(tmp_path: Path) -> None:
    registered = wp2_8.load_release_config()
    payload = json.loads(json.dumps(registered.payload))
    payload["output_dir"] = "C:/machine-local/release"
    path = tmp_path / "bad-config.json"
    path.write_bytes(exact_json_bytes(payload))
    with pytest.raises(wp2_8.PathContractError):
        wp2_8.load_release_config(path, enforce_registered=False)


def test_wrong_wp27_base_is_a_stop_condition() -> None:
    with pytest.raises(wp2_8.ReleaseContractError):
        wp2_8.verify_wp27_base(
            current_head="4fa8f201580f750281142b7a7f791a7ee815df57",
            origin_main=wp2_8.REQUIRED_WP27_BASE_COMMIT,
            current_is_descendant=False,
        )
    with pytest.raises(wp2_8.ReleaseContractError):
        wp2_8.verify_wp27_base(
            current_head=wp2_8.REQUIRED_WP27_BASE_COMMIT,
            origin_main="4fa8f201580f750281142b7a7f791a7ee815df57",
        )


def test_environment_fingerprint_requires_all_registered_fields_and_distinguishes_modes() -> None:
    expected = {
        "os": "Windows",
        "architecture": "AMD64",
        "python_implementation": "CPython",
        "python_version": "3.12.11",
        "uv_version": "0.11.25",
        "uv_lock_sha256": "a" * 64,
        "reproduction_commit": "b" * 40,
        "config_sha256": "c" * 64,
    }
    assert wp2_8.verify_environment_fingerprint(expected, dict(expected)) is True
    mismatch = dict(expected)
    mismatch["architecture"] = "ARM64"
    assert wp2_8.verify_environment_fingerprint(expected, mismatch) is False
    with pytest.raises(wp2_8.EnvironmentFingerprintError):
        wp2_8.verify_environment_fingerprint(expected, {"os": "Windows"})


def test_historical_environment_rejects_training_overrides_and_fallback_database() -> None:
    parent = {
        "TOUCHLINE_FULL_COHORT_DB_URL": "postgresql://registered",
        "TOUCHLINE_DB_URL": "postgresql://fallback",
        "TOUCHLINE_TRAIN_SCHEMA": "test_override",
    }
    with pytest.raises(wp2_8.ReproductionMismatchError):
        wp2_8.build_historical_reproduction_environment(parent, "TOUCHLINE_FULL_COHORT_DB_URL")
    environment = wp2_8.build_historical_reproduction_environment(
        {"TOUCHLINE_FULL_COHORT_DB_URL": "postgresql://registered", "TOUCHLINE_DB_URL": "fallback"},
        "TOUCHLINE_FULL_COHORT_DB_URL",
    )
    assert "TOUCHLINE_DB_URL" not in environment
    assert environment["TOUCHLINE_WP28_REPRODUCTION_SCOPE"] == "development_only"


def test_historical_fingerprint_parser_uses_the_child_process_values() -> None:
    python_output = json.dumps(
        {
            "os": "Linux",
            "architecture": "x86_64",
            "python_implementation": "CPython",
            "python_version": "3.12.12",
        }
    )
    observed = wp2_8.parse_historical_environment_fingerprint(python_output, "uv 0.11.25 (test)")
    assert observed == {
        "os": "Linux",
        "architecture": "x86_64",
        "python_implementation": "CPython",
        "python_version": "3.12.12",
        "uv_version": "0.11.25",
    }


def test_historical_byte_pin_replaces_crlf_checkout_with_raw_git_blob(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_blob = b"lock-content\nsecond-line\n"
    crlf_checkout = raw_blob.replace(b"\n", b"\r\n")
    target = tmp_path / "uv.lock"
    target.write_bytes(crlf_checkout)
    monkeypatch.setattr(wp2_8, "_read_git_blob_bytes", lambda *_args, **_kwargs: raw_blob)

    observed = wp2_8._materialize_byte_pinned_historical_input(
        tmp_path,
        tmp_path,
        revision="historical-commit",
        relative_path="uv.lock",
        expected_sha256=sha256(raw_blob).hexdigest(),
        label="historical uv.lock",
    )

    assert observed == sha256(raw_blob).hexdigest()
    assert target.read_bytes() == raw_blob


def test_historical_byte_pin_does_not_rewrite_matching_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_blob = b"lock-content\n"
    target = tmp_path / "uv.lock"
    target.write_bytes(raw_blob)
    monkeypatch.setattr(wp2_8, "_read_git_blob_bytes", lambda *_args, **_kwargs: raw_blob)

    def unexpected_write(self: Path, data: bytes) -> int:
        del self, data
        raise AssertionError("matching historical byte pin was rewritten")

    monkeypatch.setattr(Path, "write_bytes", unexpected_write)
    assert (
        wp2_8._materialize_byte_pinned_historical_input(
            tmp_path,
            tmp_path,
            revision="historical-commit",
            relative_path="uv.lock",
            expected_sha256=sha256(raw_blob).hexdigest(),
            label="historical uv.lock",
        )
        == sha256(raw_blob).hexdigest()
    )


def test_raw_git_blob_reader_ignores_simulated_crlf_historical_checkout(tmp_path: Path) -> None:
    repository, revision, raw_blob = _raw_git_fixture(tmp_path)
    lock_path = repository / "uv.lock"

    lock_path.write_bytes(raw_blob.replace(b"\n", b"\r\n"))
    assert lock_path.read_bytes() != raw_blob
    assert wp2_8._read_git_blob_bytes(repository, revision, "uv.lock") == raw_blob


def test_clean_tracked_tree_forwards_the_scoped_git_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scoped_environment = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_VALUE_0": "false"}
    observed: list[Mapping[str, str] | None] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed.append(kwargs.get("env"))  # type: ignore[arg-type]
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    require_clean_tracked_tree(tmp_path, env=scoped_environment)
    assert observed == [scoped_environment]


def test_scoped_git_checkout_is_raw_and_clean_under_host_autocrlf_true(
    tmp_path: Path,
) -> None:
    repository, revision, raw_blob = _raw_git_fixture(tmp_path)
    global_config = tmp_path / "host-global.gitconfig"
    subprocess.run(
        ["git", "config", "--file", str(global_config), "core.autocrlf", "true"],
        check=True,
        capture_output=True,
    )
    global_before = global_config.read_bytes()
    host_environment = dict(os.environ)
    for key in list(host_environment):
        if (
            key == "GIT_CONFIG_COUNT"
            or key.startswith("GIT_CONFIG_KEY_")
            or key.startswith("GIT_CONFIG_VALUE_")
        ):
            host_environment.pop(key)
    host_environment["GIT_CONFIG_GLOBAL"] = str(global_config)
    environment_before = dict(host_environment)

    host_checkout = tmp_path / "host-checkout"
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "worktree",
            "add",
            "--detach",
            str(host_checkout),
            revision,
        ],
        check=True,
        capture_output=True,
        env=host_environment,
    )
    try:
        assert (host_checkout / "uv.lock").read_bytes() == raw_blob.replace(b"\n", b"\r\n")
        (host_checkout / "uv.lock").write_bytes(raw_blob)
        with pytest.raises(ProvenanceError, match="dirty tracked working tree"):
            require_clean_tracked_tree(host_checkout, env=host_environment)
    finally:
        subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "worktree",
                "remove",
                "--force",
                str(host_checkout),
            ],
            check=True,
            capture_output=True,
            env=host_environment,
        )

    scoped_environment = wp2_8._historical_git_environment(host_environment)
    assert host_environment == environment_before
    assert scoped_environment["GIT_CONFIG_COUNT"] == "1"
    assert scoped_environment["GIT_CONFIG_KEY_0"] == "core.autocrlf"
    assert scoped_environment["GIT_CONFIG_VALUE_0"] == "false"

    scoped_checkout = tmp_path / "scoped-checkout"
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "worktree",
            "add",
            "--detach",
            str(scoped_checkout),
            revision,
        ],
        check=True,
        capture_output=True,
        env=scoped_environment,
    )
    try:
        observed = wp2_8._materialize_byte_pinned_historical_input(
            repository,
            scoped_checkout,
            revision=revision,
            relative_path="uv.lock",
            expected_sha256=sha256(raw_blob).hexdigest(),
            label="historical uv.lock",
        )
        assert observed == sha256(raw_blob).hexdigest()
        assert (scoped_checkout / "uv.lock").read_bytes() == raw_blob
        require_clean_tracked_tree(scoped_checkout, env=scoped_environment)
    finally:
        subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "worktree",
                "remove",
                "--force",
                str(scoped_checkout),
            ],
            check=True,
            capture_output=True,
            env=scoped_environment,
        )
    assert global_config.read_bytes() == global_before


def test_historical_clean_tree_gate_rejects_a_genuine_tracked_mutation(tmp_path: Path) -> None:
    repository, revision, raw_blob = _raw_git_fixture(tmp_path)
    scoped_environment = wp2_8._historical_git_environment(dict(os.environ))
    checkout = tmp_path / "checkout"
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "worktree",
            "add",
            "--detach",
            str(checkout),
            revision,
        ],
        check=True,
        capture_output=True,
        env=scoped_environment,
    )
    try:
        (checkout / "uv.lock").write_bytes(raw_blob + b"genuine mutation\n")
        with pytest.raises(ProvenanceError, match="dirty tracked working tree"):
            require_clean_tracked_tree(checkout, env=scoped_environment)
    finally:
        subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "worktree",
                "remove",
                "--force",
                str(checkout),
            ],
            check=True,
            capture_output=True,
            env=scoped_environment,
        )


def test_historical_reproduction_scopes_git_config_through_sync_and_training(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, canonical, _ = _synthetic_packet_inputs(tmp_path)
    registered_sha = str(
        config.section("reproduction")["exact_environment_fingerprint"]["uv_lock_sha256"]
    )
    canonical = replace(canonical, config={"uv_lock_sha256": registered_sha})
    monkeypatch.setenv("TOUCHLINE_FULL_COHORT_DB_URL", "postgresql://registered")
    events: list[str] = []
    checked: list[tuple[list[str], Mapping[str, str] | None]] = []
    clean_environments: list[Mapping[str, str] | None] = []

    def record_command(
        command: list[str], *, cwd: Path, env: Mapping[str, str] | None = None
    ) -> None:
        del cwd
        checked.append((command, env))
        if command[:2] == ["git", "-C"]:
            events.append("worktree")
        elif command[:2] == ["uv", "sync"]:
            events.append("sync")
        else:
            events.append("training")
            raise wp2_8.ReproductionMismatchError("stop after scoped environment assertion")

    def record_clean(root: Path, *, env: Mapping[str, str] | None = None) -> None:
        del root
        clean_environments.append(env)
        events.append("clean")

    monkeypatch.setattr(wp2_8, "_run_checked", record_command)
    monkeypatch.setattr(
        wp2_8, "_materialize_byte_pinned_historical_input", lambda *args, **kwargs: registered_sha
    )
    monkeypatch.setattr(
        wp2_8, "_assert_historical_development_loader", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(wp2_8, "require_clean_tracked_tree", record_clean)

    with pytest.raises(wp2_8.ReproductionMismatchError, match="stop after scoped"):
        wp2_8.run_historical_reproduction(config, canonical, root=tmp_path)

    assert events == ["worktree", "clean", "sync", "training"]
    assert len(clean_environments) == 1
    for _, environment in checked:
        assert environment is not None
        assert environment["GIT_CONFIG_KEY_0"] == "core.autocrlf"
        assert environment["GIT_CONFIG_VALUE_0"] == "false"
    assert clean_environments[0] is checked[0][1]


@pytest.mark.parametrize(
    ("blob", "expected"),
    [
        (b"wrong-blob\n", sha256(b"registered-blob\n").hexdigest()),
        (b"registered-blob\n", "0" * 64),
    ],
)
def test_historical_byte_pin_rejects_incorrect_blob_or_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blob: bytes, expected: str
) -> None:
    target = tmp_path / "uv.lock"
    original_checkout = b"existing\r\n"
    target.write_bytes(original_checkout)
    monkeypatch.setattr(wp2_8, "_read_git_blob_bytes", lambda *_args, **_kwargs: blob)

    with pytest.raises(wp2_8.ReproductionMismatchError):
        wp2_8._materialize_byte_pinned_historical_input(
            tmp_path,
            tmp_path,
            revision="historical-commit",
            relative_path="uv.lock",
            expected_sha256=expected,
            label="historical uv.lock",
        )
    assert target.read_bytes() == original_checkout


def test_historical_reproduction_rejects_canonical_registered_lock_mismatch_before_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, canonical, _ = _synthetic_packet_inputs(tmp_path)
    payload = json.loads(json.dumps(config.payload))
    payload["reproduction"]["exact_environment_fingerprint"]["uv_lock_sha256"] = "b" * 64
    config = replace(config, payload=payload)
    canonical = replace(canonical, config={"uv_lock_sha256": "a" * 64})
    checked_commands: list[list[str]] = []

    def record_command(command: list[str], **_: object) -> None:
        checked_commands.append(command)

    def unexpected_materialization(*_: object, **__: object) -> str:
        raise AssertionError(
            "byte-pinned historical input was materialized after a digest mismatch"
        )

    monkeypatch.setattr(wp2_8, "_run_checked", record_command)
    monkeypatch.setattr(
        wp2_8,
        "_materialize_byte_pinned_historical_input",
        unexpected_materialization,
    )

    with pytest.raises(
        wp2_8.ReproductionMismatchError,
        match=r"canonical and WP2\.8 registered uv\.lock digests disagree",
    ):
        wp2_8.run_historical_reproduction(config, canonical, root=tmp_path)

    assert len(checked_commands) == 1
    assert checked_commands[0][:5] == ["git", "-C", str(tmp_path), "worktree", "add"]


def test_development_only_guard_rejects_calibration_and_holdout_before_preprocessing() -> None:
    assignments = {"development": {1, 2}, "calibration": {3}, "holdout": {4}}
    wp2_8.assert_development_only_match_ids({1, 2}, assignments)
    with pytest.raises(wp2_8.DevelopmentOnlyError):
        wp2_8.assert_development_only_match_ids({3}, assignments)
    with pytest.raises(wp2_8.DevelopmentOnlyError):
        wp2_8.assert_development_only_match_ids({99}, assignments)
    overlapping = {"development": {3}, "calibration": {3}, "holdout": {4}}
    with pytest.raises(wp2_8.DevelopmentOnlyError):
        wp2_8.assert_development_only_match_ids({3}, overlapping)


def test_development_only_row_guard_rejects_forbidden_rows_before_preprocessing() -> None:
    assignments = {"development": {1}, "calibration": {2}, "holdout": {3}}
    rows = [{"match_id": 1, "location": [10.0, 20.0]}]
    wp2_8.assert_development_only_rows(rows, assignments)
    with pytest.raises(wp2_8.DevelopmentOnlyError):
        wp2_8.assert_development_only_rows([{"match_id": 2, "location": [10.0, 20.0]}], assignments)


def test_reproduction_tolerance_has_a_strict_boundary() -> None:
    canonical: dict[str, dict[str, object]] = {
        "metrics": {
            "score": 0.25,
            "shipped_candidate": "full_minus_presence",
            "shipped_feature_set": "geometry+categoricals",
            "shipped_feature_columns": ["x"],
        },
        "config": {"expected": 2872},
        "artifact_manifest": {"best_c": 0.1},
    }
    regenerated: dict[str, dict[str, object]] = {
        "metrics": {
            "score": 0.2500000000005,
            "shipped_candidate": "full_minus_presence",
            "shipped_feature_set": "geometry+categoricals",
            "shipped_feature_columns": ["x"],
        },
        "config": {"expected": 2872},
        "artifact_manifest": {"best_c": 0.1000000000005},
    }
    result = wp2_8.compare_reproduction(
        canonical,
        regenerated,
        canonical_model_sha256="a" * 64,
        regenerated_model_sha256="b" * 64,
        exact_environment_match=False,
        numeric_tolerance=1e-12,
    )
    assert result.comparison_mode == "numeric_tolerance"
    assert result.canonical_json_equal is False
    regenerated["metrics"]["score"] = 0.250000000002
    with pytest.raises(wp2_8.ReproductionMismatchError):
        wp2_8.compare_reproduction(
            canonical,
            regenerated,
            canonical_model_sha256="a" * 64,
            regenerated_model_sha256="b" * 64,
            exact_environment_match=False,
            numeric_tolerance=1e-12,
        )


def test_exact_reproduction_requires_byte_equal_model_artifact() -> None:
    payload = {
        "metrics": {"shipped_candidate": "full_minus_presence"},
        "config": {},
        "artifact_manifest": {},
    }
    with pytest.raises(wp2_8.ReproductionMismatchError):
        wp2_8.compare_reproduction(
            payload,
            payload,
            canonical_model_sha256="a" * 64,
            regenerated_model_sha256="b" * 64,
            exact_environment_match=True,
            numeric_tolerance=1e-12,
        )


def test_wp27_measured_chain_ignores_editorial_presentation_changes(tmp_path: Path) -> None:
    for relative in (
        "experiments/run-configs/wp2_7-calibration.json",
        "experiments/run-configs/wp2_7-holdout.json",
        "experiments/shot_quality/exp-20260809-wp2_7-calibration-holdout/calibration-decision.json",
        "experiments/shot_quality/exp-20260809-wp2_7-calibration-holdout/holdout-access-audit.json",
        "experiments/shot_quality/exp-20260809-wp2_7-calibration-holdout/holdout-metrics.json",
        "experiments/shot_quality/exp-20260809-wp2_7-calibration-holdout/experiment-record.json",
    ):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    registered = wp2_8.load_release_config()
    config = replace(registered, path=tmp_path / "release.json")
    (tmp_path / "release.json").write_bytes(registered.path.read_bytes())
    presentation = (
        tmp_path / "experiments/shot_quality/exp-20260809-wp2_7-calibration-holdout/evidence.md"
    )
    # Presentation content is intentionally not needed for the measured chain.
    presentation.parent.mkdir(parents=True, exist_ok=True)
    presentation.write_text("editorial revision\n", encoding="utf-8")
    evidence = wp2_8.verify_wp27_measured_chain(config, root=tmp_path)
    assert (
        evidence.decision_sha256
        == "f5c9ccf665924069f755fbd669d4a9abada1e5791e957d3d436d42d500277e89"
    )


def test_wp27_machine_artifact_change_is_blocking(tmp_path: Path) -> None:
    for relative in (
        "experiments/run-configs/wp2_7-calibration.json",
        "experiments/run-configs/wp2_7-holdout.json",
        "experiments/shot_quality/exp-20260809-wp2_7-calibration-holdout/calibration-decision.json",
        "experiments/shot_quality/exp-20260809-wp2_7-calibration-holdout/holdout-access-audit.json",
        "experiments/shot_quality/exp-20260809-wp2_7-calibration-holdout/holdout-metrics.json",
        "experiments/shot_quality/exp-20260809-wp2_7-calibration-holdout/experiment-record.json",
    ):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    registered = wp2_8.load_release_config()
    config = replace(registered, path=tmp_path / "release.json")
    (tmp_path / "release.json").write_bytes(registered.path.read_bytes())
    path = tmp_path / config.section("wp27")["metrics_path"]
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(wp2_8.ReleaseContractError):
        wp2_8.verify_wp27_measured_chain(config, root=tmp_path)


def test_wp24_partial_or_stale_artifact_is_blocking(tmp_path: Path) -> None:
    registered = wp2_8.load_release_config()
    for relative in (
        "experiments/run-configs/wp2_4-baselines.json",
        "experiments/shot_quality/exp-20260805-wp2_4-baselines/config.json",
        "experiments/shot_quality/exp-20260805-wp2_4-baselines/metrics.json",
        "experiments/shot_quality/exp-20260805-wp2_4-baselines/artifact-manifest.json",
        "artifacts/models/exp-20260805-wp2_4-baselines/model.pkl",
    ):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    config = replace(registered, path=tmp_path / "release.json")
    (tmp_path / "release.json").write_bytes(registered.path.read_bytes())
    stale_metrics = tmp_path / config.section("wp24")["metrics_path"]
    stale_metrics.write_bytes(stale_metrics.read_bytes() + b"\n")
    with pytest.raises(wp2_8.ReleaseContractError):
        wp2_8.verify_wp24_evidence(config, root=tmp_path)


def test_atomic_packet_publication_and_existing_packet_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, wp24, wp27 = _synthetic_packet_inputs(tmp_path)
    first = wp2_8.publish_release_packet(config, wp24, wp27, _fixture_reproduction(), root=tmp_path)
    assert (first / "release-manifest.json").is_file()
    manifest = wp2_8.verify_release_manifest(first / "release-manifest.json", root=tmp_path)
    assert manifest["release_status"] == "m2_qualified"
    assert manifest["serving_status"] == "not_served"
    assert manifest["reproduction_scope"] == "development_only"
    assert manifest["new_holdout_access"] is False
    (first / "notes.md").write_text("editorial note change\n", encoding="utf-8")
    wp2_8.verify_release_manifest(first / "release-manifest.json", root=tmp_path)
    authoritative = tmp_path / "experiments/wp24-metrics.json"
    authoritative_bytes = authoritative.read_bytes()
    authoritative.write_bytes(authoritative_bytes + b"stale\n")
    with pytest.raises(wp2_8.ReleaseContractError):
        wp2_8.verify_release_manifest(first / "release-manifest.json", root=tmp_path)
    authoritative.write_bytes(authoritative_bytes)
    manifest_path = first / "release-manifest.json"
    envelope = json.loads(manifest_path.read_text(encoding="utf-8"))
    envelope["manifest"]["release_id"] = "tampered"
    manifest_path.write_bytes(exact_json_bytes(envelope))
    with pytest.raises(wp2_8.ReleaseContractError):
        wp2_8.verify_release_manifest(manifest_path, root=tmp_path)
    monkeypatch.setattr(
        tempfile,
        "mkdtemp",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("staging must not start")),
    )
    with pytest.raises(wp2_8.ReleasePublicationError):
        wp2_8.publish_release_packet(config, wp24, wp27, _fixture_reproduction(), root=tmp_path)
    assert not list(tmp_path.glob(".packet.staging-*"))


def test_failed_staging_is_cleaned_and_publishes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, wp24, wp27 = _synthetic_packet_inputs(tmp_path)
    monkeypatch.setattr(wp2_8, "_notes", lambda *_args: 42)
    with pytest.raises(TypeError):
        wp2_8.publish_release_packet(config, wp24, wp27, _fixture_reproduction(), root=tmp_path)
    assert not (tmp_path / "packet").exists()
    assert not list(tmp_path.glob(".packet.staging-*"))
