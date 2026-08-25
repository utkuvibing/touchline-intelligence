"""Unit contracts for M5 WP5.2 preregistered v2 protocol. No database or network required.

These tests pin the preregistration: the machine-readable gate config at
``data/model/v2_protocol.json`` parses under an exact allowed-key schema, every numerical gate
equals its literal here so prose/config/test drift fails CI, the development pool and sealed sets
mirror the WP5.1 evaluation registry exactly, and the frozen target-free fold semantics are valid
as pure functions on synthetic fixtures.

The fold functions below are the *executable specification* referenced by the WP5.2 contract.
M7's production fold primitive must reproduce these behaviors; it does not import them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_PATH = ROOT / "data" / "model" / "v2_protocol.json"
REGISTRY_PATH = ROOT / "data" / "model" / "v2_evaluation_registry.json"

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


# --- Frozen fold semantics --------------------------------------------------


def _reference_inner_folds(matches: list[tuple[str, int]]) -> dict[int, int]:
    """Executable specification of the frozen inner rule.

    Matches sorted by ``(match_date, match_id)``; grouped strictly by ``match_id``; assigned
    ``inner_fold = index % 5``; no shuffling, no seed.
    """
    ordered = sorted(matches)
    return {match_id: index % INNER_SPLIT_COUNT for index, (_, match_id) in enumerate(ordered)}


def test_outer_scopes_are_exactly_four_loto_scopes_in_fixed_order() -> None:
    scopes = [
        (
            scope["outer_fold"],
            scope["holdout_tournament"],
            scope["competition_id"],
            scope["season_id"],
        )
        for scope in PAYLOAD["fold_rules"]["outer"]["scopes"]
    ]
    assert scopes == OUTER_SCOPES
    assert PAYLOAD["fold_rules"]["outer"]["scheme"] == "leave_one_tournament_out"
    assert PAYLOAD["fold_rules"]["outer"]["iteration_order_fixed"] is True
    held_out = {(scope[2], scope[3]) for scope in scopes}
    pool = {(comp, season) for _, comp, season in DEVELOPMENT_POOL}
    assert held_out == pool
    assert len(held_out) == len(scopes)


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
    matches = [
        ("2018-06-17", 3),
        ("2018-06-15", 1),
        ("2020-07-01", 9),
        ("2018-06-15", 2),
        ("2022-11-22", 5),
        ("2024-06-15", 4),
        ("2020-06-28", 8),
        ("2022-12-01", 6),
        ("2024-07-05", 10),
        ("2020-06-21", 7),
    ]
    reordered = matches[::-1]
    assert _reference_inner_folds(reordered) == _reference_inner_folds(matches)


def test_inner_folds_partition_matches_without_splitting_a_match() -> None:
    matches = [(f"2018-06-{day:02d}", match_id) for day, match_id in enumerate(range(35), start=1)]
    assignment = _reference_inner_folds(matches)
    assert len(assignment) == 35
    by_fold: dict[int, set[int]] = {}
    for match_id, fold in assignment.items():
        by_fold.setdefault(fold, set()).add(match_id)
    assert set(by_fold) == {0, 1, 2, 3, 4}
    all_ids = [match_id for fold_ids in by_fold.values() for match_id in fold_ids]
    assert len(all_ids) == len(set(all_ids)) == 35
    assert all(len(members) == 7 for members in by_fold.values())


def test_inner_folds_stay_balanced_for_uneven_partitions() -> None:
    matches = [(f"date-{index:03d}", index) for index in range(37)]
    by_fold: dict[int, int] = {}
    for _, fold in _reference_inner_folds(matches).items():
        by_fold[fold] = by_fold.get(fold, 0) + 1
    assert sorted(by_fold.values()) == [7, 7, 7, 8, 8]


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
