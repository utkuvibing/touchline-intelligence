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
from pathlib import Path

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


def test_every_hashed_record_is_canonical_lf() -> None:
    for name in JSON_RECORDS:
        data = (EXP / name).read_bytes()
        assert b"\r" not in data, f"{name} must be canonical LF; a CRLF checkout is a re-lock"
        assert data.endswith(b"\n"), f"{name} must end with a newline"
    assert b"\r" not in RUN_CONFIG.read_bytes()


def test_the_line_ending_pin_still_covers_the_hashed_artifact_types() -> None:
    """The digests published by this work package are only reproducible while these rules hold."""
    text = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    for rule in ("*.csv text eol=lf", "*.sql text eol=lf", "*.json text eol=lf"):
        assert rule in text


def test_the_run_consumed_the_pinned_inputs_that_are_on_disk() -> None:
    """The digests the record claims must be the digests of the files in this checkout."""
    metrics = json.loads((EXP / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["assignments_sha256"] == _sha256(ASSIGNMENTS)
    assert metrics["cohort_sql_sha256"] == _sha256(COHORT_SQL)
    assert metrics["input_config_sha256"] == _sha256(RUN_CONFIG)
    assert metrics["uv_lock_sha256"] == _sha256(ROOT / "uv.lock")


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
