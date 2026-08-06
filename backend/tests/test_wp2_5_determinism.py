"""WP2.5 determinism contract (D20).

Histogram gradient boosting sums gradients in a thread-dependent order, so the byte-identity claim
this repository makes about ``metrics.json`` is only meaningful when the thread count is pinned.
``run_protocol`` therefore wraps every fit in ``threadpool_limits(1)``.

What is asserted here is the whole claim and nothing more: **two runs of the same input under the
same runtime emit byte-identical canonical records, including the model pickle hash.** Stability
across a *different* input ordering is a separate and weaker property, measured and bounded in
``test_wp2_5_train_modeling.py``.
"""

from __future__ import annotations

import numpy as np

from touchline.modeling.boosting import BoostingParams
from touchline.modeling.logistic import L2_C_GRID
from touchline.modeling.metrics import canonical_metrics_json
from touchline.modeling.preprocessing import ShotRow
from touchline.modeling.train_boosting import (
    MODEL_FAMILY,
    THREAD_LIMIT,
    BoostingRunConfig,
    run_protocol,
)

GRID = (
    BoostingParams(learning_rate=0.06, max_leaf_nodes=7, min_samples_leaf=20),
    BoostingParams(learning_rate=0.1, max_leaf_nodes=15, min_samples_leaf=60),
)


def _rows(seed: int = 9) -> list[ShotRow]:
    rng = np.random.default_rng(seed)
    bodies = ("Right Foot", "Left Foot", "Head")
    rows: list[ShotRow] = []
    for fold in range(5):
        for i in range(48):
            y = 1 if i < 8 else 0
            rows.append(
                ShotRow(
                    shot_id=f"d{fold}-{i}",
                    match_id=700 + fold * 6 + (i % 6),
                    fold=fold,
                    competition_id=43,
                    season_id=3,
                    y=y,
                    distance_to_goal=float(7.0 + 15.0 * rng.random() - 2.0 * y),
                    visible_goal_angle=float(0.4 * rng.random() + 0.15 * y),
                    body_part_name=bodies[i % len(bodies)],
                    technique_name="Normal" if i % 4 else "Volley",
                    play_pattern_name="Regular Play" if i % 3 else "From Corner",
                    first_time=bool(rng.random() < 0.3),
                    under_pressure=bool(rng.random() < 0.4),
                )
            )
    return rows


def _config() -> BoostingRunConfig:
    return BoostingRunConfig(
        experiment_id="wp2-5-determinism",
        out_dir="experiments/shot_quality/wp2-5-determinism",
        artifacts_dir="artifacts/models/wp2-5-determinism",
        code_commit="fixed-commit",
        reproduction_commit="fixed-commit",
        data_source_commit="b0bc9f22dd77c206ddedc1d742893b3bbe64baec",
        input_config_path="experiments/run-configs/unit-test.json",
        input_config_sha256="0" * 64,
        uv_lock_sha256="0" * 64,
        runtime_fingerprint={"pinned": "for-this-test"},
        require_clean_provenance=False,
        db_url_env="TOUCHLINE_DB_URL",
        assignments_sha256="0" * 64,
        cohort_sql_sha256="0" * 64,
        model_family=MODEL_FAMILY,
        c_grid=L2_C_GRID,
        gbm_grid=GRID,
        random_seed=0,
        n_folds=5,
        expected_shots=240,
        expected_matches=30,
        expected_fold_sizes={fold: 48 for fold in range(5)},
        bin_count=5,
        results_csv="experiments/results.csv",
    )


def test_thread_limit_is_pinned_to_one() -> None:
    """The pin is the precondition for every other claim in this module."""
    assert THREAD_LIMIT == 1


def test_two_runs_emit_byte_identical_canonical_records() -> None:
    rows = _rows()
    metrics_a, bundle_a = run_protocol(rows, _config())
    metrics_b, bundle_b = run_protocol(rows, _config())

    assert canonical_metrics_json(metrics_a) == canonical_metrics_json(metrics_b)
    # The pickle hash carries no tolerance, so it is the strictest part of the claim.
    assert metrics_a["model_pickle_sha256"] == metrics_b["model_pickle_sha256"]
    assert metrics_a["thread_limit"] == THREAD_LIMIT
    # Two independently fitted final models score raw rows identically, bit for bit.
    query = rows[:12]
    assert np.array_equal(bundle_a.predict_proba(query), bundle_b.predict_proba(query))


def test_the_record_is_canonical_json_and_carries_no_nan() -> None:
    """``allow_nan=False`` means a degenerate metric would raise here rather than serialize."""
    metrics, _bundle = run_protocol(_rows(), _config())
    payload = canonical_metrics_json(metrics)
    assert payload.endswith(b"\n")
    assert b"\r\n" not in payload
    assert b"NaN" not in payload and b"Infinity" not in payload
