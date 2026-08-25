"""Unit contracts for M5 WP5.2 preregistered v2 protocol. No database or network required.

These tests pin the preregistration: the machine-readable gate config at
``data/model/v2_protocol.json`` parses under an exact allowed-key schema, every numerical gate
equals its literal here so prose/config/test drift fails CI, the normative statements of the
prose contract appear in ``docs/modeling/wp5_2-v2-nested-protocol-contract.md``, the development
pool and sealed sets mirror the WP5.1 evaluation registry exactly, and the frozen target-free
fold semantics hold in the single production primitive all of M6/M7 must reuse:
``touchline.modeling.v2_folds``.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from touchline.modeling.splits import MatchRecord
from touchline.modeling.v2_folds import (
    FoldConstructionError,
    assign_inner_folds,
    development_pool_scopes,
    inner_partition,
    outer_fold_specs,
    outer_partition,
)
from touchline.sealed_scope import SealedScopeError

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_PATH = ROOT / "data" / "model" / "v2_protocol.json"
REGISTRY_PATH = ROOT / "data" / "model" / "v2_evaluation_registry.json"
CONTRACT_PATH = ROOT / "docs" / "modeling" / "wp5_2-v2-nested-protocol-contract.md"

SOURCE_COMMIT = "b0bc9f22dd77c206ddedc1d742893b3bbe64baec"
DEVELOPMENT_POOL = [
    ("WC2018", 43, 3),
    ("Euro2020", 55, 43),
    ("WC2022", 43, 106),
    ("Euro2024", 55, 282),
]
OUTER_SCOPES = [
    ("loto_wc2018", "WC2018", 43, 3),
    ("loto_euro2020", "Euro2020", 55, 43),
    ("loto_wc2022", "WC2022", 43, 106),
    ("loto_euro2024", "Euro2024", 55, 282),
]
INNER_SPLIT_COUNT = 5
SLICE_FAMILIES = [
    "body_part_name",
    "technique_name",
    "play_pattern_name",
    "shot_type_name",
    "distance_statsbomb_coordinate_units",
    "visible_goal_angle_radians",
]
C_GRID = [0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0]
HGB_SEARCH_SPACE = {
    "learning_rate": [0.03, 0.1],
    "max_leaf_nodes": [8, 31],
    "min_samples_leaf": [20, 50],
    "l2_regularization": [0.0, 1.0],
    "max_iter": [300],
}
OUTCOME_FIELD_NAMES = {
    "outcome",
    "outcomes",
    "goal",
    "goals",
    "goal_count",
    "goal_counts",
    "is_goal",
    "label",
    "labels",
    "y",
}

_FREE_DICT = "__free_dict__"


def _load(path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return payload


PAYLOAD = _load(PROTOCOL_PATH)


def _assert_keys(obj: Any, expected: set[str], path: str) -> None:
    found = set(obj) if isinstance(obj, dict) else set()
    missing = sorted(expected - found)
    extra = sorted(found - expected)
    if missing or extra:
        raise AssertionError(f"{path}: missing keys {missing}, unknown keys {extra}")


def _check_against_spec(value: Any, spec: Any, path: str) -> None:
    """Recursively enforce an exact allowed-key schema.

    ``spec=None`` admits any JSON scalar. A dict spec requires exactly those keys (recursed).
    The ``_FREE_DICT`` sentinel admits an object with unrestricted string keys whose values are
    scalars or lists of scalars. An empty list spec admits a list of scalars; a one-element list
    spec validates every item against its template dict.
    """
    if spec is None:
        assert not isinstance(value, (dict, list)), f"{path}: expected a scalar"
        return
    if spec == _FREE_DICT:
        assert isinstance(value, dict), f"{path}: expected an object"
        for key, child in value.items():
            children = child if isinstance(child, list) else [child]
            for item in children:
                assert not isinstance(item, (dict, list)), (
                    f"{path}.{key}: expected a scalar or a list of scalars"
                )
        return
    if isinstance(spec, dict):
        assert isinstance(value, dict), f"{path}: expected an object"
        _assert_keys(value, set(spec), path)
        for key, sub in spec.items():
            _check_against_spec(value[key], sub, f"{path}.{key}")
        return
    if isinstance(spec, list):
        assert isinstance(value, list), f"{path}: expected a list"
        if not spec:
            for index, item in enumerate(value):
                assert not isinstance(item, (dict, list)), f"{path}[{index}]: expected a scalar"
            return
        for index, item in enumerate(value):
            _check_against_spec(item, spec[0], f"{path}[{index}]")
        return
    raise AssertionError(f"malformed schema spec at {path}")


PROTOCOL_SCHEMA: dict[str, Any] = {
    "schema_version": None,
    "attribution": None,
    "purpose": None,
    "generated_utc": None,
    "source_commit": None,
    "development_pool": [{"name": None, "competition_id": None, "season_id": None}],
    "sealed_sets": [
        {
            "name": None,
            "competition_id": None,
            "season_id": None,
            "status": None,
            "permitted_access": None,
        }
    ],
    "fold_rules": {
        "target_free_by_construction": None,
        "single_primitive_rule": None,
        "outer": {
            "scheme": None,
            "iteration_order_fixed": None,
            "scopes": [
                {
                    "outer_fold": None,
                    "holdout_tournament": None,
                    "competition_id": None,
                    "season_id": None,
                }
            ],
        },
        "inner": {
            "grouping_key": None,
            "split_count": None,
            "sort_keys": [],
            "assignment_rule": None,
            "shuffle": None,
            "seed": None,
            "semantics": None,
        },
        "tie_behavior": {
            "rule": None,
            "order": [],
            "performance_based_tiebreaks_permitted": None,
        },
    },
    "metrics": {
        "primary": [],
        "reporting_granularity": [],
        "calibration_intercept_slope": {
            "method": None,
            "ideal_intercept": None,
            "ideal_slope": None,
        },
        "reliability_bins": {"count": None, "edges": [], "fixed_a_priori": None},
        "secondary": [],
        "prespecified_slice_families": [],
        "reliability_diagrams": None,
    },
    "bootstrap": {
        "replicates": None,
        "seed": None,
        "interval": None,
        "resampling_unit": None,
        "differences": None,
        "stratification": {
            "pooled_multi_tournament_comparisons": None,
            "per_tournament_comparisons": None,
        },
    },
    "candidate_families": {
        "additional_families_prohibited": None,
        "search_space_widening_after_first_v2_run_prohibited": None,
        "allowed": [{"name": None, "definition": None, "search_space": _FREE_DICT}],
    },
    "bundle_evaluator": {
        "scope": None,
        "admission": {
            "log_loss_requirement": None,
            "max_pooled_brier_degradation": None,
            "max_tournaments_allowed_to_worsen": None,
            "max_single_tournament_log_loss_worsening": None,
            "offline_serving_parity_required": None,
            "declared_feature_coverage_required": None,
        },
    },
    "internal_replacement": {
        "comparator": None,
        "scope": None,
        "min_pooled_outer_log_loss_improvement": None,
        "ci_requirement": None,
        "max_pooled_brier_degradation": None,
        "min_tournaments_non_worse_of_four": None,
        "max_single_tournament_log_loss_worsening": None,
        "feature_coverage_and_offline_serving_parity_required": None,
        "near_miss_is_failure": None,
    },
    "calibration_policy": {
        "methods_allowed": [],
        "isotonic_excluded": None,
        "evaluation_basis": None,
        "fitting_procedure": {
            "leakage_rule": None,
            "per_outer_fold": {
                "calibrator_input": None,
                "fitted_methods": [],
                "application_target": None,
            },
            "final_refit_sequence": [],
        },
        "adoption": {
            "min_pooled_log_loss_improvement": None,
            "ci_requirement": None,
            "max_pooled_brier_degradation": None,
            "min_tournaments_with_intercept_and_slope_closer_to_ideal_of_four": None,
            "max_single_tournament_log_loss_worsening": None,
        },
        "otherwise_ship": None,
    },
    "external_qualification": {
        "sets": [],
        "opened_once_per_set": None,
        "reporting": None,
        "references_scored": [],
        "comparator": None,
        "constant_prevalence_reference": None,
        "promotion_gate": {
            "min_combined_log_loss_improvement": None,
            "ci_requirement": None,
            "max_upper_bound_of_paired_brier_difference": None,
            "max_single_external_tournament_log_loss_worsening": None,
            "coverage_artifact_integrity_offline_serving_parity_required": None,
        },
        "recycling_prohibited_after_opening": None,
        "on_failure": None,
    },
    "stop_conditions": {
        "on_external_gate_failure": None,
        "new_untouched_tournament_required_to_resume_selection": None,
        "future_reservation_recorded_in": None,
    },
    "evidence_hierarchy": {"outer_loto_results": None, "sealed_external_qualification": None},
    "rules": [],
}


# --- Schema ----------------------------------------------------------------


def test_config_parses_under_the_exact_allowed_key_schema() -> None:
    _check_against_spec(PAYLOAD, PROTOCOL_SCHEMA, "v2_protocol")


def test_unknown_top_level_key_rejects_loudly() -> None:
    mutated = {**PAYLOAD, "sneaky_threshold": 0.05}
    with pytest.raises(AssertionError, match="unknown keys \\['sneaky_threshold'\\]"):
        _check_against_spec(mutated, PROTOCOL_SCHEMA, "v2_protocol")


def test_unknown_nested_key_rejects_loudly() -> None:
    admission = dict(PAYLOAD["bundle_evaluator"]["admission"])
    admission["log_loss_improvement_over"] = 0.001
    mutated = {
        **PAYLOAD,
        "bundle_evaluator": {**PAYLOAD["bundle_evaluator"], "admission": admission},
    }
    with pytest.raises(AssertionError, match="unknown keys \\['log_loss_improvement_over'\\]"):
        _check_against_spec(mutated, PROTOCOL_SCHEMA, "v2_protocol")


# --- Identity and registry consistency -------------------------------------


def test_source_commit_is_the_pinned_revision() -> None:
    assert PAYLOAD["source_commit"] == SOURCE_COMMIT


def test_development_pool_matches_the_wp5_1_registry_exactly() -> None:
    registry = _load(REGISTRY_PATH)
    pool = [
        (entry["name"], entry["competition_id"], entry["season_id"])
        for entry in PAYLOAD["development_pool"]
    ]
    registry_pool = [
        (entry["name"], entry["competition_id"], entry["season_id"])
        for entry in registry["development_pool"]
    ]
    assert pool == DEVELOPMENT_POOL
    assert pool == registry_pool


def test_sealed_sets_match_the_wp5_1_registry_exactly() -> None:
    registry = _load(REGISTRY_PATH)
    sealed = [
        (
            entry["name"],
            entry["competition_id"],
            entry["season_id"],
            entry["status"],
            entry["permitted_access"],
        )
        for entry in PAYLOAD["sealed_sets"]
    ]
    registry_sealed = [
        (
            entry["name"],
            entry["competition_id"],
            entry["season_id"],
            entry["status"],
            entry["permitted_access"],
        )
        for entry in registry["sealed_sets"]
    ]
    assert sealed == registry_sealed
    assert sealed == [
        ("AFCON 2023", 1267, 107, "sealed", "target_free_structural_only"),
        ("Copa America 2024", 223, 282, "sealed", "target_free_structural_only"),
    ]


# --- Frozen fold semantics (production primitive: touchline.modeling.v2_folds) ---


def _match(match_id: int, day: int, scope: tuple[int, int] = (43, 3)) -> MatchRecord:
    return MatchRecord(
        match_id=match_id,
        competition_id=scope[0],
        season_id=scope[1],
        match_date=dt.date(2018, 6, 1) + dt.timedelta(days=day - 1),
    )


def _synthetic_pool() -> list[MatchRecord]:
    """One match per development-pool tournament plus WC2018 filler for inner-fold balance."""
    scopes = [(43, 3), (55, 43), (43, 106), (55, 282)]
    records = [_match(index + 1, index + 1, scope) for index, scope in enumerate(scopes)]
    records.extend(_match(100 + day, day) for day in range(1, 32))
    return records


def test_outer_specs_come_from_the_config_in_fixed_order() -> None:
    specs = outer_fold_specs(PAYLOAD)
    observed = [(spec.outer_fold, spec.holdout_tournament, spec.scope.pair) for spec in specs]
    expected = [(name, tournament, (cid, sid)) for name, tournament, cid, sid in OUTER_SCOPES]
    assert observed == expected
    assert development_pool_scopes(PAYLOAD) == {(cid, sid) for _, cid, sid in DEVELOPMENT_POOL}


def _mutated_outer_scope(index: int, **fields: object) -> dict[str, Any]:
    config = copy.deepcopy(PAYLOAD)
    config["fold_rules"]["outer"]["scopes"][index].update(fields)
    return config


def test_outer_specs_reject_a_changed_scheme() -> None:
    config = copy.deepcopy(PAYLOAD)
    config["fold_rules"]["outer"]["scheme"] = "random_k_fold"
    with pytest.raises(FoldConstructionError, match="leave_one_tournament_out"):
        outer_fold_specs(config)


def test_outer_specs_reject_an_unfixed_iteration_order() -> None:
    config = copy.deepcopy(PAYLOAD)
    config["fold_rules"]["outer"]["iteration_order_fixed"] = False
    with pytest.raises(FoldConstructionError, match="iteration_order_fixed"):
        outer_fold_specs(config)


def test_outer_specs_reject_a_duplicate_held_out_scope() -> None:
    with pytest.raises(FoldConstructionError, match="more than one outer fold"):
        outer_fold_specs(_mutated_outer_scope(1, competition_id=43, season_id=3))


def test_outer_specs_reject_a_scope_outside_the_development_pool() -> None:
    with pytest.raises(FoldConstructionError, match="outside the development pool"):
        outer_fold_specs(_mutated_outer_scope(0, competition_id=999))


def test_outer_specs_reject_a_sealed_scope() -> None:
    with pytest.raises(SealedScopeError, match="AFCON 2023"):
        outer_fold_specs(_mutated_outer_scope(0, competition_id=1267, season_id=107))


def test_inner_rule_groups_by_match_id_with_five_deterministic_splits() -> None:
    inner = PAYLOAD["fold_rules"]["inner"]
    assert inner["grouping_key"] == "match_id"
    assert inner["split_count"] == INNER_SPLIT_COUNT
    assert inner["sort_keys"] == ["match_date", "match_id"]
    assert inner["shuffle"] is False
    assert inner["seed"] is None
    assert "index % 5" in inner["assignment_rule"]
    assert inner["semantics"].startswith("deterministic match-grouped folds")


def test_inner_assignment_is_canonical_under_input_reordering() -> None:
    matches = [_match(match_id=index + 1, day=((index * 7) % 30) + 1) for index in range(10)]
    assert dict(assign_inner_folds(matches[::-1])) == dict(assign_inner_folds(matches))


def test_inner_folds_partition_matches_without_splitting_a_match() -> None:
    matches = [_match(match_id=index + 1, day=index + 1) for index in range(35)]
    assignment = assign_inner_folds(matches)
    assert len(assignment) == 35
    seen_ids: set[int] = set()
    for validation_fold in range(INNER_SPLIT_COUNT):
        training, validation = inner_partition(assignment, validation_fold)
        assert len(validation) == 7
        assert len(training) == 28
        assert not set(training) & set(validation)
        seen_ids |= set(training) | set(validation)
    assert seen_ids == {record.match_id for record in matches}


def test_inner_folds_stay_balanced_for_uneven_partitions() -> None:
    matches = [_match(match_id=index + 1, day=(index % 28) + 1) for index in range(37)]
    assignment = assign_inner_folds(matches)
    counts = sorted(
        sum(1 for fold in assignment.values() if fold == validation_fold)
        for validation_fold in range(INNER_SPLIT_COUNT)
    )
    assert counts == [7, 7, 7, 8, 8]


def test_fold_construction_fails_loudly_on_bad_inputs() -> None:
    sealed = _match(match_id=900, day=1, scope=(1267, 107))
    with pytest.raises(SealedScopeError, match="sealed external evaluation set"):
        assign_inner_folds([sealed])
    with pytest.raises(FoldConstructionError, match="no matches provided"):
        assign_inner_folds([])
    duplicated = _synthetic_pool()
    duplicated.append(_match(match_id=duplicated[0].match_id, day=2))
    with pytest.raises(FoldConstructionError, match="duplicate match_id"):
        assign_inner_folds(duplicated)
    with pytest.raises(FoldConstructionError, match="no match_date"):
        assign_inner_folds(
            [MatchRecord(1, 43, 3, dt.date(2018, 6, 1)), MatchRecord(2, 55, 43, None)]
        )
    with pytest.raises(FoldConstructionError, match="below 2"):
        assign_inner_folds(_synthetic_pool(), split_count=1)


def test_inner_partition_rejects_degenerate_or_invalid_requests() -> None:
    assignment = assign_inner_folds([_match(match_id=1, day=1)])
    with pytest.raises(FoldConstructionError, match=r"outside 0\.\.4"):
        inner_partition(assign_inner_folds(_synthetic_pool()), -1)
    with pytest.raises(FoldConstructionError, match=r"outside 0\.\.4"):
        inner_partition(assign_inner_folds(_synthetic_pool()), 5)
    with pytest.raises(FoldConstructionError, match="degenerate"):
        inner_partition(assignment, 1)


def test_outer_partition_is_deterministic_and_loud_about_foreign_scopes() -> None:
    specs = outer_fold_specs(PAYLOAD)
    pool = _synthetic_pool()
    spec = specs[3]
    training, held_out = outer_partition(pool, specs, spec)
    assert all((r.competition_id, r.season_id) == (55, 282) for r in held_out)
    assert len(held_out) == 1
    assert len(training) == len(pool) - 1
    assert list(outer_partition(pool[::-1], specs, spec)[0]) == list(training)

    foreign = [*_synthetic_pool(), _match(match_id=500, day=15, scope=(99, 9))]
    with pytest.raises(FoldConstructionError, match="outside every supplied"):
        outer_partition(foreign, specs, spec)
    with pytest.raises(FoldConstructionError, match="not among the supplied"):
        outer_partition(pool, specs[:-1], spec)
    without_euro2024 = [r for r in pool if (r.competition_id, r.season_id) != (55, 282)]
    with pytest.raises(FoldConstructionError, match="holds out no matches"):
        outer_partition(without_euro2024, specs, specs[3])


def test_fold_rules_carry_no_outcome_bearing_field_names() -> None:
    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                assert key not in OUTCOME_FIELD_NAMES, f"outcome-bearing key in fold_rules: {key}"
                _walk(child)
        elif isinstance(node, list):
            for child in node:
                _walk(child)

    _walk(PAYLOAD["fold_rules"])
    assert PAYLOAD["fold_rules"]["target_free_by_construction"] is True
    rule = PAYLOAD["fold_rules"]["single_primitive_rule"]
    assert "M6" in rule and "M7" in rule


def test_ties_resolve_to_simplicity_never_to_measured_performance() -> None:
    ties = PAYLOAD["fold_rules"]["tie_behavior"]
    assert ties["order"] == ["lower_feature_bundle_level", "logistic_over_boosting"]
    assert ties["performance_based_tiebreaks_permitted"] is False


# --- Metrics and uncertainty ------------------------------------------------


def test_metrics_pin_primary_quality_bins_and_slice_families() -> None:
    metrics = PAYLOAD["metrics"]
    assert metrics["primary"] == ["log_loss", "brier_score"]
    assert metrics["reporting_granularity"] == ["pooled", "per_tournament"]
    intercept_slope = metrics["calibration_intercept_slope"]
    assert intercept_slope["ideal_intercept"] == 0.0
    assert intercept_slope["ideal_slope"] == 1.0
    bins = metrics["reliability_bins"]
    assert bins["count"] == 5
    assert bins["edges"] == [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    assert bins["fixed_a_priori"] is True
    assert metrics["secondary"] == ["roc_auc", "pr_auc"]
    assert metrics["prespecified_slice_families"] == SLICE_FAMILIES


def test_bootstrap_keeps_wp2_7_numbers_and_adds_tournament_stratification() -> None:
    boot = PAYLOAD["bootstrap"]
    assert boot["replicates"] == 2000
    assert boot["seed"] == 0
    assert boot["interval"] == "percentile_95"
    assert boot["resampling_unit"] == "match_cluster"
    assert boot["differences"] == "paired"
    stratification = boot["stratification"]
    assert stratification["pooled_multi_tournament_comparisons"] == (
        "tournament_stratified_within_replicate_preserving_per_stratum_match_counts"
    )
    assert stratification["per_tournament_comparisons"] == "single_stratum"


# --- Candidate families ------------------------------------------------------


def test_candidate_list_is_exactly_four_families_with_frozen_search_spaces() -> None:
    families = PAYLOAD["candidate_families"]
    assert families["additional_families_prohibited"] is True
    assert families["search_space_widening_after_first_v2_run_prohibited"] is True
    names = [family["name"] for family in families["allowed"]]
    assert names == [
        "constant_prevalence",
        "v1_form_l2_logistic",
        "context_rich_spline_logistic",
        "hist_gradient_boosting_challenger",
    ]
    by_name = {family["name"]: family["search_space"] for family in families["allowed"]}
    assert by_name["constant_prevalence"] == {}
    assert by_name["v1_form_l2_logistic"] == {"C": C_GRID}
    assert by_name["context_rich_spline_logistic"] == {"C": C_GRID}
    assert by_name["hist_gradient_boosting_challenger"] == HGB_SEARCH_SPACE


# --- Numerical gates ---------------------------------------------------------


def test_bundle_evaluator_gate_matches_the_preregistered_literals() -> None:
    admission = PAYLOAD["bundle_evaluator"]["admission"]
    assert admission["max_pooled_brier_degradation"] == 0.0005
    assert admission["max_tournaments_allowed_to_worsen"] == 1
    assert admission["max_single_tournament_log_loss_worsening"] == 0.005
    assert admission["offline_serving_parity_required"] is True
    assert admission["declared_feature_coverage_required"] is True
    assert "wholly below zero" in admission["log_loss_requirement"]


def test_internal_replacement_gate_matches_the_preregistered_literals() -> None:
    replacement = PAYLOAD["internal_replacement"]
    assert replacement["min_pooled_outer_log_loss_improvement"] == 0.003
    assert "wholly below zero" in replacement["ci_requirement"]
    assert replacement["max_pooled_brier_degradation"] == 0.0005
    assert replacement["min_tournaments_non_worse_of_four"] == 3
    assert replacement["max_single_tournament_log_loss_worsening"] == 0.005
    assert replacement["feature_coverage_and_offline_serving_parity_required"] is True
    assert replacement["near_miss_is_failure"] is True


def test_calibration_policy_excludes_isotonic_and_pins_adoption_gates() -> None:
    policy = PAYLOAD["calibration_policy"]
    assert policy["methods_allowed"] == ["raw", "intercept_only", "platt"]
    assert policy["isotonic_excluded"] is True
    adoption = policy["adoption"]
    assert adoption["min_pooled_log_loss_improvement"] == 0.001
    assert "wholly below zero" in adoption["ci_requirement"]
    assert adoption["max_pooled_brier_degradation"] == 0.0
    assert adoption["min_tournaments_with_intercept_and_slope_closer_to_ideal_of_four"] == 3
    assert adoption["max_single_tournament_log_loss_worsening"] == 0.002
    assert policy["otherwise_ship"] == "raw probabilities"


def test_external_qualification_gate_matches_the_preregistered_literals() -> None:
    external = PAYLOAD["external_qualification"]
    assert external["sets"] == ["AFCON 2023", "Copa America 2024"]
    assert external["opened_once_per_set"] is True
    assert external["references_scored"] == [
        "constant_prevalence",
        "v1_raw",
        "v1_calibrated",
        "frozen_v2",
    ]
    gate = external["promotion_gate"]
    assert gate["min_combined_log_loss_improvement"] == 0.003
    assert "wholly below zero" in gate["ci_requirement"]
    assert gate["max_upper_bound_of_paired_brier_difference"] == 0.0005
    assert gate["max_single_external_tournament_log_loss_worsening"] == 0.005
    assert gate["coverage_artifact_integrity_offline_serving_parity_required"] is True
    assert external["recycling_prohibited_after_opening"] is True
    assert "retain v1" in external["on_failure"]


# --- Evidence hierarchy and stop conditions ---------------------------------


def test_evidence_hierarchy_separates_internal_from_external_evidence() -> None:
    hierarchy = PAYLOAD["evidence_hierarchy"]
    assert "internal development/selection evidence" in hierarchy["outer_loto_results"]
    assert (
        "never presented as the unbiased post-selection estimate" in hierarchy["outer_loto_results"]
    )
    assert "external generalization evidence" in hierarchy["sealed_external_qualification"]
    assert hierarchy["sealed_external_qualification"].startswith("the external")


def test_stop_conditions_freeze_selection_after_a_failed_external_gate() -> None:
    stops = PAYLOAD["stop_conditions"]
    assert "retain v1" in stops["on_external_gate_failure"]
    assert "stop model selection" in stops["on_external_gate_failure"]
    assert stops["new_untouched_tournament_required_to_resume_selection"] is True
    assert stops["future_reservation_recorded_in"] == (
        "data/model/v2_evaluation_registry.json future_reservation"
    )


# --- Calibration fitting semantics ------------------------------------------


def test_calibration_fitting_procedure_is_preregistered_and_leakage_free() -> None:
    fitting = PAYLOAD["calibration_policy"]["fitting_procedure"]
    assert fitting["leakage_rule"] == (
        "no calibrator is ever fitted on predictions of rows whose underlying model saw those "
        "rows in training"
    )
    per_fold = fitting["per_outer_fold"]
    assert per_fold["calibrator_input"] == (
        "out-of-fold raw predictions generated inside the outer training partition by the "
        "frozen inner CV"
    )
    assert per_fold["fitted_methods"] == ["intercept_only", "platt"]
    assert per_fold["application_target"] == (
        "that outer fold's untouched outer-holdout raw predictions only"
    )


def test_final_refit_sequence_is_frozen_step_by_step() -> None:
    sequence = PAYLOAD["calibration_policy"]["fitting_procedure"]["final_refit_sequence"]
    assert sequence == [
        (
            "generate development OOF raw predictions by running the frozen inner procedure "
            "once on all four development tournaments"
        ),
        "fit the selected calibrator on those development OOF raw predictions",
        "refit the base model on all development rows",
        "freeze the model-calibrator pair before opening either sealed set",
    ]


def test_external_constant_prevalence_is_frozen_full_development_prevalence() -> None:
    reference = PAYLOAD["external_qualification"]["constant_prevalence_reference"]
    assert reference.startswith(
        "the full-development non-penalty goal prevalence over the four development-pool "
        "tournaments"
    )
    assert reference.endswith("frozen before any sealed set is opened")


# --- Contract prose consistency ---------------------------------------------

#: The contract prose with all whitespace collapsed, so normative fragments match regardless of
#: Markdown line wrapping.
CONTRACT_TEXT = " ".join(CONTRACT_PATH.read_text(encoding="utf-8").split())


def _contract_contains(*fragments: str) -> None:
    missing = [fragment for fragment in fragments if fragment not in CONTRACT_TEXT]
    assert not missing, f"contract prose is missing normative fragments: {missing}"


def test_contract_states_the_outer_scopes_in_fixed_order() -> None:
    _contract_contains(
        "| `loto_wc2018` | WC2018 | `(43, 3)` |",
        "| `loto_euro2020` | Euro2020 | `(55, 43)` |",
        "| `loto_wc2022` | WC2022 | `(43, 106)` |",
        "| `loto_euro2024` | Euro2024 | `(55, 282)` |",
    )


def test_contract_states_the_inner_rule_and_tie_behavior() -> None:
    _contract_contains(
        "assigned `inner_fold = index % 5`",
        "`shuffle = false`",
        "there is **no seed**",
        "lower feature bundle level first, then logistic over boosting",
        "Ties are never broken by measured performance.",
    )


def test_contract_names_the_single_production_primitive() -> None:
    _contract_contains(
        "`backend/src/touchline/modeling/v2_folds.py`",
        "reimplementing fold logic elsewhere is prohibited",
        "remains deferred to M7's evaluation harness",
    )


def test_contract_states_the_m6_bundle_evaluator_gate() -> None:
    _contract_contains(
        "confidence interval lies wholly below zero; Brier degradation at most `0.0005`;",
        "non-worse in all but at most one tournament represented in the outer training partition;",
    )
    _contract_contains("worse by more than `0.005` log loss")
    _contract_contains("complete offline/serving parity with declared feature coverage")


def test_contract_states_the_internal_replacement_gate() -> None:
    _contract_contains(
        "improves by at least `0.003`",
        "Brier degradation is at most `0.0005`",
        "non-worse in at least three of four tournaments",
        "worse by more than `0.005` log loss",
        "A near miss is a failed gate, not permission for another search round.",
    )


def test_contract_states_the_calibration_policy_and_fitting_procedure() -> None:
    _contract_contains(
        "only raw probabilities, intercept-only recalibration and Platt scaling",
        "Isotonic regression is excluded on this corpus.",
        "at least `0.001`",
        "(`≤ 0.000`)",
        "closer to their ideals in at least three of four tournaments",
        "worse by more than `0.002` log loss",
        "Otherwise ship raw probabilities.",
    )
    _contract_contains(
        "out-of-fold raw predictions generated inside the outer training partition by the frozen "
        "inner CV",
        "that outer fold's **untouched outer-holdout** raw predictions only",
        "(1) generate development OOF raw predictions by running the frozen inner procedure once "
        "on all four development tournaments",
        "(2) fit the selected calibrator on those development OOF raw predictions",
        "(3) refit the base model on all development rows",
        "(4) freeze the model-calibrator pair before opening either sealed set",
    )


def test_contract_states_the_external_gate_and_constant_prevalence_definition() -> None:
    _contract_contains(
        "AFCON 2023 (`1267, 107`)",
        "Copa América 2024 (`223, 282`)",
        "combined log loss improves by at least `0.003`",
        "upper bound of the paired Brier difference is at most `+0.0005`",
        "neither external tournament worsens by more than `0.005` log loss",
        "**full-development non-penalty goal prevalence over the four development-pool "
        "tournaments, frozen before any sealed set is opened**",
        "Recycling AFCON 2023 or Copa América 2024 after opening is prohibited.",
    )


def test_contract_states_bootstrap_bins_slices_and_candidates() -> None:
    _contract_contains(
        "paired differences, match-clustered bootstrap, 2,000 replicates, seed 0,",
        "tournament-stratified",
        "edges `0, 0.2, 0.4, 0.6, 0.8, 1.0`",
        "{0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0}",
        "`learning_rate ∈ {0.03, 0.1}`",
        "`max_leaf_nodes ∈ {8, 31}`",
        "`min_samples_leaf ∈ {20, 50}`",
        "`l2_regularization ∈ {0.0, 1.0}`",
        "`max_iter = 300`",
        "`HistGradientBoostingClassifier`",
    )
    for family in SLICE_FAMILIES:
        assert family in CONTRACT_TEXT


def test_contract_states_the_evidence_hierarchy_and_stop_condition() -> None:
    _contract_contains(
        "**Outer LOTO predictions and metrics are internal development/selection evidence.**",
        "never presented as the unbiased post-selection estimate of v2 quality",
        "**The one-time sealed AFCON 2023 + Copa América 2024 qualification is the external "
        "generalization evidence**",
        "retain v1, publish v2 as a negative result, stop model selection until a newly pinned "
        "genuinely untouched complete tournament exists",
    )
