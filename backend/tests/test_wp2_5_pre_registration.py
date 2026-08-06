"""WP2.5 pre-registration gate, expressed as contracts rather than prose.

WP2.5's whole value depends on the search space and the comparison target being fixed *before* the
measurement is seen. Three mechanical guards:

1. **The sign-off gate.** If ADR 0011 is present on disk *and* a WP2.5 experiment record exists,
   the ADR must read ``Accepted``. Producing evidence under a ``Proposed`` pre-registration is the
   exact failure PLAN §4.1 exists to prevent.

   Known limit, stated rather than glossed: ``docs/`` is git-ignored, so in a published checkout
   the ADR is absent and this assertion is a documented no-op. It is a **developer-local** gate,
   green in CI either way. Guards 2 and 3 are unconditional and are what CI actually enforces.

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

import pytest

from touchline.modeling import train_boosting
from touchline.modeling.boosting import GBM_GRID

ROOT = Path(__file__).resolve().parents[2]
ADR_PATH = ROOT / "docs" / "adr" / "0011-wp2-5-comparison-target-and-boosting-search-space.md"
EXPERIMENTS = ROOT / "experiments" / "shot_quality"

#: ``Accepted`` followed by an ISO date, e.g. ``Accepted - 2026-08-07``. A bare ``Accepted`` with
#: no date is not a sign-off.
ACCEPTED_PATTERN = re.compile(r"Accepted\s*[-—]\s*\d{4}-\d{2}-\d{2}")


def _wp25_experiment_records() -> list[Path]:
    if not EXPERIMENTS.is_dir():
        return []
    return sorted(EXPERIMENTS.glob("exp-*-wp2_5*/metrics.json"))


def test_a_wp2_5_experiment_record_requires_an_accepted_adr_0011() -> None:
    records = _wp25_experiment_records()
    if not records:
        pytest.skip("no WP2.5 experiment record yet; the run has not happened")
    if not ADR_PATH.is_file():
        pytest.skip(
            "ADR 0011 is absent: docs/ is git-ignored, so this gate is developer-local only"
        )
    text = ADR_PATH.read_text(encoding="utf-8")
    assert ACCEPTED_PATTERN.search(text), (
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
