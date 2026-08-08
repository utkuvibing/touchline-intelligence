"""Byte-integrity of the committed WP2.5 evidence packet.

Plain unit tests: no database, no network, so they run on every CI platform. They assert that the
committed records are canonical LF and that the pinned inputs the run claims to have consumed are
the ones actually on disk. A CRLF checkout or an edited record fails here rather than silently
invalidating the published hashes.

The model pickle itself is git-ignored, so what is checkable from a clone is the *claim*: the
manifest, the metrics and the results row must all state the same digest.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from touchline.modeling.experiment import (
    GitRepositoryUnavailableError,
    HistoricalGitObjectError,
    historical_git_blob_bytes,
    historical_git_blob_sha256,
)

ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / "experiments" / "shot_quality" / "exp-20260806-wp2_5-gradient-boosting"
RUN_CONFIG = ROOT / "experiments" / "run-configs" / "wp2_5-gradient-boosting.json"
ASSIGNMENTS = ROOT / "data" / "model" / "wp2_3_match_assignments.csv"
COHORT_SQL = ROOT / "backend" / "sql" / "wp2_1" / "01_model_shot_cohort.sql"
REPORT = ROOT / "reports" / "wp2.5-gradient-boosting-evidence.md"

#: Only the JSON records are line-ending pinned. ``.gitattributes`` deliberately pins ``*.csv``,
#: ``*.sql`` and ``*.json`` and nothing else, because those are the files whose SHA-256 digests are
#: published. Markdown is stored LF in git but `core.autocrlf` may hand a Windows checkout CRLF, so
#: asserting LF on `notes.md` or the report here would fail on a platform the policy allows.
JSON_RECORDS = ("metrics.json", "config.json", "artifact-manifest.json")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


HISTORICAL_GIT_SKIP_REASON = (
    "Historical WP2.5 `uv.lock` integrity cannot be validated because Git repository data "
    "is unavailable."
)


def _historical_uv_lock_sha256(root: Path, reproduction_commit: str) -> str:
    try:
        return historical_git_blob_sha256(root, reproduction_commit, "uv.lock")
    except GitRepositoryUnavailableError:
        pytest.skip(HISTORICAL_GIT_SKIP_REASON)


def test_every_hashed_record_is_canonical_lf() -> None:
    for name in JSON_RECORDS:
        data = (EXP / name).read_bytes()
        assert b"\r" not in data, f"{name} must be canonical LF; a CRLF checkout is a re-lock"
        assert data.endswith(b"\n"), f"{name} must end with a newline"
    assert b"\r" not in RUN_CONFIG.read_bytes()


def test_the_line_ending_pin_still_covers_the_hashed_artifact_types() -> None:
    """The digests published by this work package are only reproducible while these rules hold.

    ``uv.lock`` is on this list because of a real cross-platform failure, not for symmetry. It is
    hashed into every experiment record as ``uv_lock_sha256``, but was never pinned: a Windows
    checkout hashed the CRLF working-tree copy (86,746 bytes) and recorded a digest that no Linux
    checkout of the same commit could reproduce from the LF blob (86,034 bytes). CI caught it.
    """
    text = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    for rule in (
        "*.csv text eol=lf",
        "*.sql text eol=lf",
        "*.json text eol=lf",
        "uv.lock text eol=lf",
    ):
        assert rule in text, f"{rule!r} is missing; a published digest becomes platform-dependent"


def test_the_uv_lock_on_disk_is_line_ending_canonical() -> None:
    """The pin is only worth having if the working-tree copy actually obeys it."""
    raw = (ROOT / "uv.lock").read_bytes()
    assert b"\r" not in raw, (
        "uv.lock contains CR; its SHA-256 would differ from the LF blob every other platform sees"
    )


def test_the_run_consumed_the_pinned_inputs_that_are_on_disk() -> None:
    """Current contracts match disk; the historical lock matches its reproduction commit."""
    metrics = json.loads((EXP / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["assignments_sha256"] == _sha256(ASSIGNMENTS)
    assert metrics["cohort_sql_sha256"] == _sha256(COHORT_SQL)
    assert metrics["input_config_sha256"] == _sha256(RUN_CONFIG)
    assert metrics["uv_lock_sha256"] == _historical_uv_lock_sha256(
        ROOT, str(metrics["reproduction_commit"])
    )


def _git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True)
    return result.stdout


def test_historical_lock_resolution_reads_the_recorded_commit_not_the_working_tree(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "WP2.5 integrity test")
    _git(repo, "config", "user.email", "wp25-integrity@example.invalid")
    lock = repo / "uv.lock"
    historical = b"version = 1\nrevision = 'wp2.5'\n"
    lock.write_bytes(historical)
    _git(repo, "add", "uv.lock")
    _git(repo, "commit", "-qm", "historical lock")
    reproduction_commit = _git(repo, "rev-parse", "HEAD").decode("ascii").strip()

    lock.write_bytes(b"version = 1\nrevision = 'wp2.6'\n")
    _git(repo, "add", "uv.lock")
    _git(repo, "commit", "-qm", "current lock")

    expected = hashlib.sha256(historical).hexdigest()
    assert historical_git_blob_bytes(repo, reproduction_commit, "uv.lock") == historical
    assert historical_git_blob_sha256(repo, reproduction_commit, "uv.lock") == expected
    assert _historical_uv_lock_sha256(repo, reproduction_commit) == expected
    assert expected != hashlib.sha256(lock.read_bytes()).hexdigest()


def test_non_git_checkout_skips_with_the_explicit_reason(tmp_path: Path) -> None:
    with pytest.raises(pytest.skip.Exception, match=r"Historical WP2\.5") as skipped:
        _historical_uv_lock_sha256(tmp_path, "a" * 40)
    assert str(skipped.value) == HISTORICAL_GIT_SKIP_REASON


def test_git_checkout_with_missing_historical_object_fails(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    with pytest.raises(HistoricalGitObjectError, match="fetch the recorded reproduction commit"):
        historical_git_blob_sha256(repo, "a" * 40, "uv.lock")


def test_the_model_digest_is_stated_identically_everywhere_it_appears() -> None:
    """The pickle is git-ignored, so consistency of the claim is what a clone can check."""
    metrics = json.loads((EXP / "metrics.json").read_text(encoding="utf-8"))
    manifest = json.loads((EXP / "artifact-manifest.json").read_text(encoding="utf-8"))
    digest = metrics["model_pickle_sha256"]
    assert len(digest) == 64 and set(digest) <= set("0123456789abcdef")
    assert manifest["model_pickle_sha256"] == digest
    assert digest in REPORT.read_text(encoding="utf-8")


def test_the_committed_run_config_still_declares_the_twelve_point_grid() -> None:
    payload = json.loads(RUN_CONFIG.read_text(encoding="utf-8"))
    grid = payload["gbm_grid"]
    assert len(grid) == 12
    assert {p["learning_rate"] for p in grid} == {0.03, 0.06, 0.1}
    assert {p["max_leaf_nodes"] for p in grid} == {7, 15}
    assert {p["min_samples_leaf"] for p in grid} == {20, 60}
    assert payload["model_family"] == "hist-gradient-boosting"
    assert payload["bin_count"] == 5
    assert payload["expected_shots"] == 2872
    assert payload["expected_matches"] == 115
