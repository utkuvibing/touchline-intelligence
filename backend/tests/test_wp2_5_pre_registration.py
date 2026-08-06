"""WP2.5 pre-registration gate, expressed as contracts rather than prose.

WP2.5's whole value depends on the search space and the comparison target being fixed *before* the
measurement is seen. Three mechanical guards:

1. **The execution gate**, and it is one: ``train_boosting.main`` calls
   :func:`~touchline.modeling.train_boosting.check_pre_registration` **before** provenance is
   derived and **before** the database is opened. An unaccepted ADR 0011 stops the run with a
   non-zero exit while the connection is still unmade. The tests below prove the ordering by
   making both ``resolve_provenance`` and ``open_db`` explode if reached.

   Two honest edges are pinned too: the gate reads only the ADR's ``## Status`` section, so the
   word "Accepted" in surrounding prose cannot pass it; and an *absent* ADR (a published checkout,
   where ``docs/`` is git-ignored) is reported as ``unverifiable`` rather than treated as a pass.

   A separate, weaker after-the-fact check confirms that a committed WP2.5 record is accompanied
   by an accepted ADR. That one is developer-local and is **not** the gate — the gate is the
   pre-execution refusal above.

2. **Module independence.** ``train_boosting`` must not import ``train``. The two entry points
   share ``protocol`` and ``experiment`` deliberately; an import of the WP2.4 runner would smuggle
   WP2.4's logistic-specific config validation and record shape into WP2.5 through the back door.

3. **The search space is not tunable at run time.** The config loader accepts exactly the twelve
   declared D14 points; a widened, narrowed or perturbed grid in a config JSON is refused.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

import pytest

from touchline.modeling import train_boosting
from touchline.modeling.boosting import GBM_GRID
from touchline.modeling.train_boosting import (
    UNVERIFIABLE,
    PreRegistrationError,
    check_pre_registration,
)

ROOT = Path(__file__).resolve().parents[2]
ADR_PATH = ROOT / "docs" / "adr" / "0011-wp2-5-comparison-target-and-boosting-search-space.md"
EXPERIMENTS = ROOT / "experiments" / "shot_quality"

#: ``Accepted`` followed by an ISO date. A bare ``Accepted`` with no date is not a sign-off.
_DASHES = "-" + chr(0x2013) + chr(0x2014)  # hyphen, en dash, em dash
ACCEPTED_PATTERN = re.compile(r"Accepted\s*[" + _DASHES + r"]\s*\d{4}-\d{2}-\d{2}")

#: A ``Proposed`` ADR whose prose mentions another ADR's accepted status. If the gate searched the
#: whole document instead of the status section, this fixture would slip through.
PROPOSED_ADR = """# ADR 0011: WP2.5 comparison target

## Status

Proposed - drafted 2026-08-06 by the implementing agent. **Not accepted.**

## Context

Amends ADR 0005, which was Accepted - 2026-07-31.
"""

ACCEPTED_ADR = """# ADR 0011: WP2.5 comparison target

## Status

Accepted - 2026-08-07

## Context

Amends ADR 0005.
"""


def _config_payload(tmp_path: Path) -> dict[str, Any]:
    return {
        "experiment_id": "gate-test",
        "out_dir": str(tmp_path / "exp"),
        "artifacts_dir": str(tmp_path / "art"),
        "data_source_commit": "b0bc9f22dd77c206ddedc1d742893b3bbe64baec",
        "db_url_env": "TOUCHLINE_DB_URL",
        "assignments_sha256": "0" * 64,
        "cohort_sql_sha256": "0" * 64,
        "model_family": "hist-gradient-boosting",
        "c_grid": [0.01, 0.1, 1.0, 10.0],
        "gbm_grid": [point.as_dict() for point in GBM_GRID],
        "random_seed": 0,
        "n_folds": 5,
        "expected_shots": 2872,
        "expected_matches": 115,
        "expected_fold_sizes": {"0": 570, "1": 552, "2": 602, "3": 576, "4": 572},
        "bin_count": 5,
    }


def _wp25_experiment_records() -> list[Path]:
    if not EXPERIMENTS.is_dir():
        return []
    return sorted(EXPERIMENTS.glob("exp-*-wp2_5*/metrics.json"))


def test_an_unaccepted_adr_stops_main_before_provenance_or_any_database_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The gate is pre-execution: nothing downstream of it may run.

    ``resolve_provenance`` and ``open_db`` are replaced with functions that fail the test if they
    are ever called, so this asserts the *ordering* rather than merely the return code.
    """
    adr = tmp_path / "adr-0011.md"
    adr.write_text(PROPOSED_ADR, encoding="utf-8")
    monkeypatch.setattr(train_boosting, "ADR_PATH", adr)

    def must_not_run(*args: object, **kwargs: object) -> object:
        raise AssertionError("reached past the pre-registration gate")

    monkeypatch.setattr(train_boosting, "resolve_provenance", must_not_run)
    monkeypatch.setattr(train_boosting, "open_db", must_not_run)
    monkeypatch.setattr(train_boosting, "load_development_cohort", must_not_run)
    monkeypatch.setenv("TOUCHLINE_DB_URL", "postgresql://user:pw@localhost:5432/db")

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_config_payload(tmp_path)), encoding="utf-8")

    assert train_boosting.main(["--config", str(config_path)]) == 1
    assert "Refusing to run" in capsys.readouterr().err
    # Nothing was written: no experiment directory, no artifact directory.
    assert not (tmp_path / "exp").exists()
    assert not (tmp_path / "art").exists()


def test_the_gate_reads_only_the_status_section(tmp_path: Path) -> None:
    """ "Accepted" in surrounding prose must not be mistaken for a sign-off."""
    adr = tmp_path / "adr-0011.md"
    adr.write_text(PROPOSED_ADR, encoding="utf-8")
    assert "Accepted - 2026-07-31" in PROPOSED_ADR, "fixture must contain the decoy"
    with pytest.raises(PreRegistrationError, match="not Accepted with a date"):
        check_pre_registration(adr)


def test_an_accepted_adr_returns_its_signoff_date(tmp_path: Path) -> None:
    adr = tmp_path / "adr-0011.md"
    adr.write_text(ACCEPTED_ADR, encoding="utf-8")
    assert check_pre_registration(adr) == "2026-08-07"


def test_a_bare_accepted_without_a_date_is_not_a_signoff(tmp_path: Path) -> None:
    adr = tmp_path / "adr-0011.md"
    adr.write_text("# ADR\n\n## Status\n\nAccepted\n", encoding="utf-8")
    with pytest.raises(PreRegistrationError):
        check_pre_registration(adr)


def test_an_absent_adr_is_reported_unverifiable_and_is_not_a_pass(tmp_path: Path) -> None:
    """A published checkout has no ``docs/``. That is reported, never silently treated as signed."""
    assert check_pre_registration(tmp_path / "does-not-exist.md") == UNVERIFIABLE
    assert UNVERIFIABLE != "accepted"


def test_a_committed_wp2_5_record_is_accompanied_by_an_accepted_adr() -> None:
    """After-the-fact record check, deliberately **not** the execution gate.

    The gate is the pre-execution refusal in ``main``. This only catches a record that somehow
    reached the tree without one, and it is developer-local: ``docs/`` is git-ignored, so in a
    published checkout there is nothing to read.
    """
    records = _wp25_experiment_records()
    if not records:
        pytest.skip("no WP2.5 experiment record yet; the run has not happened")
    if not ADR_PATH.is_file():
        pytest.skip("ADR 0011 is absent: docs/ is git-ignored, so this check is developer-local")
    assert ACCEPTED_PATTERN.search(ADR_PATH.read_text(encoding="utf-8")), (
        f"{len(records)} WP2.5 experiment record(s) exist but ADR 0011 is not Accepted with a "
        "date. Evidence must not be produced under a Proposed pre-registration."
    )


def test_train_boosting_does_not_import_the_wp2_4_runner() -> None:
    source = Path(train_boosting.__file__)
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
    offending = {name for name in imported if name.startswith("touchline.modeling.train")}
    # Its own module name is not an import of the WP2.4 runner.
    offending -= {"touchline.modeling.train_boosting"}
    assert not offending, f"train_boosting must not import the WP2.4 runner; found {offending}"


def test_the_config_loader_refuses_a_grid_that_is_not_the_declared_twelve(tmp_path: Path) -> None:
    """D17: one pass over one declared grid. A config cannot widen or shrink the search."""
    base = {
        "experiment_id": "gate-test",
        "out_dir": str(tmp_path / "exp"),
        "artifacts_dir": str(tmp_path / "art"),
        "data_source_commit": "b0bc9f22dd77c206ddedc1d742893b3bbe64baec",
        "db_url_env": "TOUCHLINE_DB_URL",
        "assignments_sha256": "0" * 64,
        "cohort_sql_sha256": "0" * 64,
        "model_family": "hist-gradient-boosting",
        "c_grid": [0.01, 0.1, 1.0, 10.0],
        "gbm_grid": [point.as_dict() for point in GBM_GRID],
        "random_seed": 0,
        "n_folds": 5,
        "expected_shots": 2872,
        "expected_matches": 115,
        "expected_fold_sizes": {"0": 570, "1": 552, "2": 602, "3": 576, "4": 572},
        "bin_count": 5,
    }

    def write(payload: dict[str, object]) -> Path:
        path = tmp_path / "config.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    # The declared grid is accepted as-is.
    accepted = train_boosting._load_config(write(dict(base)))
    assert accepted.gbm_grid == GBM_GRID
    assert len(accepted.gbm_grid) == 12

    # A widened grid is refused.
    widened = dict(base)
    widened["gbm_grid"] = [
        *[point.as_dict() for point in GBM_GRID],
        {"learning_rate": 0.2, "max_leaf_nodes": 31, "min_samples_leaf": 5},
    ]
    with pytest.raises(ValueError, match="pre-registered D14 grid"):
        train_boosting._load_config(write(widened))

    # A narrowed grid is refused.
    narrowed = dict(base)
    narrowed["gbm_grid"] = [point.as_dict() for point in GBM_GRID[:6]]
    with pytest.raises(ValueError, match="pre-registered D14 grid"):
        train_boosting._load_config(write(narrowed))

    # A grid of the right size with one perturbed value is refused.
    perturbed_points = [point.as_dict() for point in GBM_GRID]
    perturbed_points[0] = {"learning_rate": 0.04, "max_leaf_nodes": 7, "min_samples_leaf": 20}
    perturbed = dict(base)
    perturbed["gbm_grid"] = perturbed_points
    with pytest.raises(ValueError, match="pre-registered D14 grid"):
        train_boosting._load_config(write(perturbed))


def test_the_config_loader_refuses_another_model_family(tmp_path: Path) -> None:
    payload = {
        "experiment_id": "gate-test",
        "out_dir": str(tmp_path / "exp"),
        "artifacts_dir": str(tmp_path / "art"),
        "data_source_commit": "b0bc9f22dd77c206ddedc1d742893b3bbe64baec",
        "db_url_env": "TOUCHLINE_DB_URL",
        "assignments_sha256": "0" * 64,
        "cohort_sql_sha256": "0" * 64,
        "model_family": "lightgbm",
        "c_grid": [0.01, 0.1, 1.0, 10.0],
        "gbm_grid": [point.as_dict() for point in GBM_GRID],
        "random_seed": 0,
        "n_folds": 5,
        "expected_shots": 2872,
        "expected_matches": 115,
        "expected_fold_sizes": {"0": 570, "1": 552, "2": 602, "3": 576, "4": 572},
        "bin_count": 5,
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly one family"):
        train_boosting._load_config(path)


def test_the_config_loader_keeps_the_inherited_bin_count_and_c_grid_locks(tmp_path: Path) -> None:
    """WP2.5 inherits ADR 0004's five-bin lock and D10's C grid; neither is re-openable."""
    base = {
        "experiment_id": "gate-test",
        "out_dir": str(tmp_path / "exp"),
        "artifacts_dir": str(tmp_path / "art"),
        "data_source_commit": "b0bc9f22dd77c206ddedc1d742893b3bbe64baec",
        "db_url_env": "TOUCHLINE_DB_URL",
        "assignments_sha256": "0" * 64,
        "cohort_sql_sha256": "0" * 64,
        "model_family": "hist-gradient-boosting",
        "c_grid": [0.01, 0.1, 1.0, 10.0],
        "gbm_grid": [point.as_dict() for point in GBM_GRID],
        "random_seed": 0,
        "n_folds": 5,
        "expected_shots": 2872,
        "expected_matches": 115,
        "expected_fold_sizes": {"0": 570, "1": 552, "2": 602, "3": 576, "4": 572},
        "bin_count": 5,
    }
    path = tmp_path / "config.json"

    bad_bins = dict(base)
    bad_bins["bin_count"] = 10
    path.write_text(json.dumps(bad_bins), encoding="utf-8")
    with pytest.raises(ValueError, match="locked at five"):
        train_boosting._load_config(path)

    bad_c = dict(base)
    bad_c["c_grid"] = [0.5, 1.0]
    path.write_text(json.dumps(bad_c), encoding="utf-8")
    with pytest.raises(ValueError, match="pre-registered D10 grid"):
        train_boosting._load_config(path)
