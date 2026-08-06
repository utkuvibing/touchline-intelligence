"""Unit contracts for the WP2.5 protocol runner.

Scope note, deliberately narrow: the fold construction, the training-rows-only scaler, the constant
baseline and the PLAN §4.1 rule body now live in ``touchline.modeling.protocol`` and are protected
by the WP2.4 contracts in ``test_wp2_4_train_modeling.py``. Re-asserting them here would be
coverage theatre. What is genuinely new in WP2.5, and therefore tested here:

- the booster consumes WP2.4's **shipped** feature columns, resolved **by name** (D13) — never a
  presence column, and never a hard-coded position;
- chain A is WP2.4's chain **extended**, not re-specified (D18): its first two outcomes must equal
  those of the unextended three-step chain run independently;
- chain B is a separate, direct comparison against the shipped logistic and is the decision of
  record — the two chains are distinct fields and may disagree;
- the D19 calibration diagnostic is diagnostic only: perturbing it cannot move a decision, because
  no decision reads it;
- the serialized bundle round-trips: scoring raw rows through the artifact equals the persisted
  estimator applied to the persisted column subset.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import cast

import numpy as np

from touchline.modeling.artifact import BoostingBundle, infer_boosting
from touchline.modeling.boosting import BoostingParams
from touchline.modeling.experiment import RESULTS_CSV_HEADER
from touchline.modeling.logistic import L2_C_GRID
from touchline.modeling.preprocessing import PRESENCE_SOURCE_FIELDS, ShotRow, encode_rows
from touchline.modeling.protocol import run_replacement_chain
from touchline.modeling.train_boosting import (
    CHAIN_A_ORDER,
    GBM_KEY,
    MODEL_FAMILY,
    SHIPPED_LOGISTIC_KEY,
    THREAD_LIMIT,
    BoostingRunConfig,
    run_protocol,
    write_experiment,
)

#: Two points only: this suite tests protocol wiring, not the size of the declared grid (which
#: ``test_wp2_5_boosting.py`` pins).
TEST_GRID = (
    BoostingParams(learning_rate=0.06, max_leaf_nodes=7, min_samples_leaf=20),
    BoostingParams(learning_rate=0.1, max_leaf_nodes=15, min_samples_leaf=60),
)

BODIES = ("Right Foot", "Left Foot", "Head", "Other")
TECHNIQUES = ("Normal", "Volley", "Half Volley")
PATTERNS = ("Regular Play", "From Corner", "From Free Kick")


def _rows(seed: int = 5, per_fold: int = 60) -> list[ShotRow]:
    """Balanced, mildly separable development rows with both classes in every fold."""
    rng = np.random.default_rng(seed)
    rows: list[ShotRow] = []
    for fold in range(5):
        for i in range(per_fold):
            y = 1 if i < per_fold // 6 else 0
            rows.append(
                ShotRow(
                    shot_id=f"s{fold}-{i}",
                    match_id=500 + fold * 8 + (i % 8),
                    fold=fold,
                    competition_id=43 if fold % 2 else 55,
                    season_id=3 if fold % 2 else 43,
                    y=y,
                    distance_to_goal=float(6.0 + 16.0 * rng.random() - 2.5 * y),
                    visible_goal_angle=float(0.45 * rng.random() + 0.2 * y),
                    body_part_name=BODIES[int(rng.integers(0, len(BODIES)))],
                    technique_name=TECHNIQUES[int(rng.integers(0, len(TECHNIQUES)))],
                    play_pattern_name=PATTERNS[int(rng.integers(0, len(PATTERNS)))],
                    first_time=bool(rng.random() < 0.3),
                    under_pressure=bool(rng.random() < 0.4),
                )
            )
    return rows


def _config(grid: Sequence[BoostingParams] = TEST_GRID) -> BoostingRunConfig:
    return BoostingRunConfig(
        experiment_id="wp2-5-unit-test",
        out_dir="experiments/shot_quality/wp2-5-unit-test",
        artifacts_dir="artifacts/models/wp2-5-unit-test",
        code_commit="unit-test-code",
        reproduction_commit="unit-test-code",
        data_source_commit="b0bc9f22dd77c206ddedc1d742893b3bbe64baec",
        input_config_path="experiments/run-configs/unit-test.json",
        input_config_sha256="0" * 64,
        uv_lock_sha256="0" * 64,
        runtime_fingerprint={},
        require_clean_provenance=False,
        db_url_env="TOUCHLINE_DB_URL",
        assignments_sha256="0" * 64,
        cohort_sql_sha256="0" * 64,
        model_family=MODEL_FAMILY,
        c_grid=L2_C_GRID,
        gbm_grid=tuple(grid),
        random_seed=0,
        n_folds=5,
        expected_shots=300,
        expected_matches=40,
        expected_fold_sizes={fold: 60 for fold in range(5)},
        bin_count=5,
        results_csv="experiments/results.csv",
    )


def _results_row(path: Path, experiment_id: str) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split(",")
    for line in lines[1:]:
        cells = line.split(",")
        if cells and cells[0] == experiment_id:
            return dict(zip(header, cells, strict=True))
    raise AssertionError(f"no results row for {experiment_id} in {path}")


def test_results_row_describes_the_boosting_artifact_when_the_booster_loses(tmp_path: Path) -> None:
    """Regression: three columns must not describe two different models.

    ``model``, the three metric columns and ``model_pickle_sha256`` all name **one** object — the
    boosting artifact this experiment produced. Reading the metrics from the *winner* instead
    emitted a row labelled ``hist-gradient-boosting``, carrying the booster's pickle hash, beside
    the **logistic's** numbers whenever the booster failed to replace it.

    ``shipped_candidate`` carries the selection outcome, which is where the disagreement belongs
    and stays visible.
    """
    rows = _rows()
    config = replace(
        _config(),
        out_dir=str(tmp_path / "exp"),
        artifacts_dir=str(tmp_path / "art"),
        results_csv=str(tmp_path / "results.csv"),
    )
    metrics, bundle = run_protocol(rows, config)

    # The fixture must actually exercise the losing branch, or this test proves nothing.
    assert metrics["shipped_candidate"] == SHIPPED_LOGISTIC_KEY, (
        "fixture no longer exercises the losing-booster case"
    )
    assert metrics["artifact_candidate"] == GBM_KEY

    write_experiment(metrics, bundle, config)
    row = _results_row(tmp_path / "results.csv", config.experiment_id)

    candidates = cast(Mapping[str, Mapping[str, object]], metrics["candidates"])
    booster = candidates[GBM_KEY]
    pooled = cast(Mapping[str, float], booster["pooled_oof"])

    # One object, described consistently.
    assert row["model"] == MODEL_FAMILY
    assert row["model_pickle_sha256"] == metrics["model_pickle_sha256"]
    assert float(row["primary_value"]) == booster["mean_log_loss"]
    assert float(row["brier"]) == pooled["brier"]
    assert float(row["log_loss"]) == pooled["log_loss"]

    # ...and demonstrably not the winner's numbers, which is the defect this replaces.
    winner = candidates[SHIPPED_LOGISTIC_KEY]
    winner_pooled = cast(Mapping[str, float], winner["pooled_oof"])
    assert float(row["primary_value"]) != winner["mean_log_loss"]
    assert float(row["log_loss"]) != winner_pooled["log_loss"]

    # The selection outcome is still recorded, in its own column.
    assert row["shipped_candidate"] == SHIPPED_LOGISTIC_KEY
    assert row["protocol_incumbent"] == metrics["protocol_incumbent"]

    # The inherited header is untouched, and the logistic-shaped columns say so explicitly.
    assert (tmp_path / "results.csv").read_text(encoding="utf-8").splitlines()[
        0
    ] == RESULTS_CSV_HEADER
    assert row["d5_include"] == "n/a"
    assert row["shipped_best_c"] == "n/a"


def test_chain_a_order_is_the_wp2_4_chain_plus_exactly_one_step() -> None:
    """D18: extended, not substituted. The booster is appended; nothing is replaced."""
    assert list(CHAIN_A_ORDER[:3]) == ["constant", "geometry_logistic", SHIPPED_LOGISTIC_KEY]
    assert CHAIN_A_ORDER[3] == GBM_KEY
    assert len(CHAIN_A_ORDER) == 4


def test_all_five_candidates_are_scored_and_the_booster_uses_the_shipped_columns() -> None:
    rows = _rows()
    metrics, bundle = run_protocol(rows, _config())

    candidates = cast(Mapping[str, Mapping[str, object]], metrics["candidates"])
    assert sorted(candidates) == [
        "constant",
        "full_logistic",
        "full_minus_presence",
        "geometry_logistic",
        "hist_gbm",
    ]

    # D13: the booster's columns are WP2.4's shipped set, resolved by name, with no presence column.
    presence_names = {f"{field}_presence" for field in PRESENCE_SOURCE_FIELDS}
    shipped_columns = cast(Sequence[str], metrics["shipped_feature_columns"])
    assert presence_names.isdisjoint(shipped_columns)
    assert set(presence_names) <= set(bundle.all_columns), "presence columns must still be encoded"
    assert list(bundle.selected_columns) == list(shipped_columns)
    # Positions are derived from names, so a reordered encoder cannot silently redefine the set.
    assert bundle.selected_indices == tuple(
        bundle.all_columns.index(name) for name in shipped_columns
    )
    assert metrics["shipped_feature_set"] == "geometry+categoricals"
    assert metrics["thread_limit"] == THREAD_LIMIT


def test_chain_a_extends_the_unextended_chain_rather_than_re_specifying_it() -> None:
    """The first two outcomes must equal an independently-run three-step chain."""
    rows = _rows()
    metrics, _bundle = run_protocol(rows, _config())
    candidates = cast(Mapping[str, Mapping[str, object]], metrics["candidates"])
    chain_a = cast(Mapping[str, object], metrics["replacement_chain_a"])

    unextended, _incumbent = run_replacement_chain(
        candidates, ["constant", "geometry_logistic", SHIPPED_LOGISTIC_KEY]
    )
    assert chain_a["geometry_beats_constant"] is unextended[0]
    assert chain_a["shipped_beats_incumbent"] is unextended[1]
    assert list(cast(Sequence[str], chain_a["order"])) == list(CHAIN_A_ORDER)


def test_chain_b_is_a_separate_direct_comparison_and_is_the_decision_of_record() -> None:
    rows = _rows()
    metrics, _bundle = run_protocol(rows, _config())
    chain_a = cast(Mapping[str, object], metrics["replacement_chain_a"])
    chain_b = cast(Mapping[str, object], metrics["replacement_chain_b"])

    assert chain_b["incumbent"] == SHIPPED_LOGISTIC_KEY
    assert chain_b["candidate"] == GBM_KEY
    # The recorded top-level fields keep the two chains apart: one is continuity, one is the
    # decision. Collapsing them into a single field is the failure this asserts against.
    assert metrics["protocol_incumbent"] == chain_a["protocol_incumbent"]
    assert metrics["shipped_candidate"] == chain_b["selection_incumbent"]
    assert metrics["artifact_candidate"] == GBM_KEY
    assert chain_b["selection_incumbent"] in {SHIPPED_LOGISTIC_KEY, GBM_KEY}
    # Chain B's verdict is exactly the boolean it recorded, never chain A's running incumbent.
    expected = GBM_KEY if chain_b["gbm_beats_shipped_logistic"] else SHIPPED_LOGISTIC_KEY
    assert chain_b["selection_incumbent"] == expected


def test_the_d19_diagnostic_is_reported_but_never_read_by_a_decision() -> None:
    rows = _rows()
    metrics, _bundle = run_protocol(rows, _config())
    diagnostic = cast(Mapping[str, object], metrics["calibration_support_diagnostic"])
    candidates = cast(Mapping[str, Mapping[str, object]], metrics["candidates"])

    assert diagnostic["min_support"] == metrics["d11_min_support"]
    paired = cast(Sequence[int], diagnostic["paired_supported_bins"])
    assert diagnostic["paired_supported_bin_count"] == len(paired)
    # The paired set can never exceed either candidate's own supported set.
    assert len(paired) <= int(cast(int, diagnostic["incumbent_supported_bins"]))
    assert len(paired) <= int(cast(int, diagnostic["candidate_supported_bins"]))
    assert (
        diagnostic["incumbent_supported_bins"] == candidates[SHIPPED_LOGISTIC_KEY]["supported_bins"]
    )
    assert diagnostic["candidate_supported_bins"] == candidates[GBM_KEY]["supported_bins"]

    # The decision is reproducible from the unchanged per-candidate values alone: recomputing the
    # §4.1 verdict without ever touching the diagnostic gives the same answer.
    chain_b = cast(Mapping[str, object], metrics["replacement_chain_b"])
    recomputed, _ = run_replacement_chain(candidates, [SHIPPED_LOGISTIC_KEY, GBM_KEY])
    assert recomputed[0] is chain_b["gbm_beats_shipped_logistic"]


def test_bundle_round_trip_scores_raw_rows_through_the_persisted_preprocessing() -> None:
    rows = _rows()
    _metrics, bundle = run_protocol(rows, _config())
    assert isinstance(bundle, BoostingBundle)

    query = rows[:20]
    via_bundle = infer_boosting(bundle, query)
    full_encoded, _ = encode_rows(query, bundle.vocabulary, bundle.scaler)
    subset = full_encoded[:, list(bundle.selected_indices)]
    expected = bundle.estimator.predict_proba(subset)[:, 1]
    assert np.array_equal(via_bundle, expected)
    assert bundle.estimator.n_features_in_ == len(bundle.selected_columns)
    assert bundle.hyperparameters == {
        key: float(value)
        for key, value in cast(
            Mapping[str, float], _metrics["gbm_selected_hyperparameters"]
        ).items()
    }


def test_row_order_changes_no_reported_metric_on_this_fixture() -> None:
    """Fold membership comes from each row's own ``fold`` field, never from input ordering.

    Measured boundary, stated rather than assumed: reversing the input permutes the summation
    order inside every mean, which moves the raw floats by ~1e-16. The canonical record's
    twelve-decimal rounding absorbs all of it, so every reported metric is identical here. The one
    value that is not permutation-stable is ``model_pickle_sha256``: the final refit's coefficients
    differ in their last bits, and a pickle hash has no tolerance. That hash is only ever claimed
    stable for a repeated run on the same input — which ``test_wp2_5_determinism.py`` pins.

    Read this as an observation on this fixture, not as a permutation-invariance guarantee: the
    rounding absorbs a 1e-16 perturbation, but nothing here proves it always would.
    """
    from touchline.modeling.metrics import canonical_metrics_json

    rows = _rows()
    reversed_rows = list(reversed(rows))
    metrics_a, _ = run_protocol(rows, _config())
    metrics_b, _ = run_protocol(reversed_rows, _config())

    # Structurally order-independent by construction: the vocabulary is built from counts and the
    # column set from names, so neither can depend on input order.
    assert metrics_a["vocabulary"] == metrics_b["vocabulary"]
    assert metrics_a["shipped_feature_columns"] == metrics_b["shipped_feature_columns"]

    # Observed on this fixture, and deliberately not stated as a guarantee: the selected grid
    # point and both verdicts are unchanged. They are decided by comparisons between floats that
    # the permutation moves at ~1e-16, so two near-tied grid points could in principle swap. The
    # narrow claim this suite makes about selection stability is in test_wp2_5_boosting.py:
    # repeat calls on the same input agree, and the ordering key is total.
    assert metrics_a["gbm_selected_hyperparameters"] == metrics_b["gbm_selected_hyperparameters"]
    assert metrics_a["replacement_chain_a"] == metrics_b["replacement_chain_a"]
    assert metrics_a["replacement_chain_b"] == metrics_b["replacement_chain_b"]
    assert metrics_a["protocol_incumbent"] == metrics_b["protocol_incumbent"]
    assert metrics_a["shipped_candidate"] == metrics_b["shipped_candidate"]

    # Every reported metric is identical once rounded; the pickle hash is the sole exception.
    record_a = dict(metrics_a)
    record_b = dict(metrics_b)
    assert record_a.pop("model_pickle_sha256") != "" and record_b.pop("model_pickle_sha256") != ""
    assert canonical_metrics_json(record_a) == canonical_metrics_json(record_b)
