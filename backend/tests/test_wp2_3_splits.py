"""Unit contracts for the WP2.3 deterministic split assignment. No database required.

These tests pin the split rule itself — the locked scopes, the (match_date, match_id) sort with
the ``index % N_FOLDS`` fold rule, the target-free input contract, the explicit failure modes, and
determinism under input row order. Everything here is a pure function of synthetic match records.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import fields

import pytest

from touchline.modeling.splits import (
    CALIBRATION_SCOPE,
    CSV_HEADER,
    DEVELOPMENT_SCOPE,
    HOLDOUT_SCOPE,
    N_FOLDS,
    MatchRecord,
    SplitAssignmentError,
    SplitPlan,
    assign_tournament_split,
    manifest_summaries,
    render_match_assignments_csv,
)

D = dt.date

DEV_2018 = (43, 3)
DEV_2020 = (55, 43)
CALIB = (43, 106)
HOLDOUT = (55, 282)


def _match(match_id: int, scope: tuple[int, int], date: dt.date | None) -> MatchRecord:
    return MatchRecord(match_id, scope[0], scope[1], date)


def _dev(match_id: int, date: dt.date | None) -> MatchRecord:
    return _match(match_id, DEV_2018, date)


def _date(record: MatchRecord) -> dt.date:
    """Test-side non-NULL helper; assignment already raises on NULL dates."""
    assert record.match_date is not None
    return record.match_date


def test_locked_scopes_are_the_four_tournament_pairs() -> None:
    """The constants themselves are the contract; mutating them must break this test."""
    assert frozenset({DEV_2018, DEV_2020}) == DEVELOPMENT_SCOPE
    assert CALIBRATION_SCOPE == CALIB
    assert HOLDOUT_SCOPE == HOLDOUT
    assert N_FOLDS == 5


def test_every_match_receives_exactly_one_top_level_split() -> None:
    matches = [
        _match(1, DEV_2018, D(2018, 6, 1)),
        _match(2, DEV_2020, D(2021, 6, 11)),
        _match(3, CALIB, D(2022, 11, 20)),
        _match(4, HOLDOUT, D(2024, 6, 14)),
        _match(5, DEV_2018, D(2018, 6, 2)),
        _match(6, HOLDOUT, D(2024, 7, 14)),
    ]
    plan = assign_tournament_split(matches)

    assert set(plan.match_split) == {1, 2, 3, 4, 5, 6}
    assert plan.split_of(1) == "development"
    assert plan.split_of(2) == "development"
    assert plan.split_of(3) == "calibration"
    assert plan.split_of(4) == "holdout"
    assert plan.split_of(5) == "development"
    assert plan.split_of(6) == "holdout"
    assert plan.matches_in("development") == (1, 2, 5)
    assert plan.matches_in("calibration") == (3,)
    assert plan.matches_in("holdout") == (4, 6)


def test_hand_computed_fold_membership_with_same_date_ties() -> None:
    """Twelve development matches, two sharing a date, sorted and folded by hand.

    The tied pair is fed in reversed input order (103 before 102) so that a stable sort by date
    alone would produce a different assignment than the locked (match_date, match_id) sort; the
    expected membership below pins the tie-break.
    """
    matches = [
        _dev(101, D(2018, 6, 1)),
        _dev(103, D(2018, 6, 2)),  # same date as 102, but fed first: input order must not matter
        _dev(102, D(2018, 6, 2)),
        _dev(104, D(2018, 6, 3)),
        _dev(105, D(2018, 6, 5)),
        _dev(106, D(2018, 6, 6)),
        _dev(107, D(2018, 6, 7)),
        _dev(108, D(2018, 6, 10)),
        _dev(109, D(2018, 6, 11)),
        _dev(110, D(2018, 6, 12)),
        _dev(111, D(2018, 6, 13)),
        _dev(112, D(2018, 6, 14)),
    ]
    plan = assign_tournament_split(matches)

    expected = {
        101: 0,
        102: 1,
        103: 2,
        104: 3,
        105: 4,
        106: 0,
        107: 1,
        108: 2,
        109: 3,
        110: 4,
        111: 0,
        112: 1,
    }
    assert dict(plan.match_fold) == expected
    sizes = {fold: sum(1 for f in plan.match_fold.values() if f == fold) for fold in range(N_FOLDS)}
    assert sizes == {0: 3, 1: 3, 2: 2, 3: 2, 4: 2}


def test_full_size_development_has_exactly_23_matches_per_fold() -> None:
    """115 development matches (the measured dev population size) fold into 5 x 23."""
    matches = [
        _dev(match_id, D(2018, 1, 1) + dt.timedelta(days=match_id)) for match_id in range(1, 116)
    ]
    plan = assign_tournament_split(matches)

    dev_ids = set(plan.matches_in("development"))
    assert len(dev_ids) == 115
    fold_ids: dict[int, set[int]] = {fold: set() for fold in range(N_FOLDS)}
    for match_id, fold in plan.match_fold.items():
        fold_ids[fold].add(match_id)
    for fold in range(N_FOLDS):
        assert len(fold_ids[fold]) == 23, fold
    for fold in range(N_FOLDS):
        assert fold_ids[fold].issubset(dev_ids)
    assert set(plan.match_fold) == dev_ids
    union = set().union(*fold_ids.values())
    assert union == dev_ids


def test_folds_are_pairwise_disjoint() -> None:
    matches = [_dev(match_id, D(2018, 6, match_id % 20 + 1)) for match_id in range(1, 30)]
    plan = assign_tournament_split(matches)

    for a in range(N_FOLDS):
        for b in range(a + 1, N_FOLDS):
            assert not set(m for m, f in plan.match_fold.items() if f == a) & set(
                m for m, f in plan.match_fold.items() if f == b
            )


def test_match_fold_never_contains_calibration_or_holdout_matches() -> None:
    matches = [
        _dev(1, D(2018, 6, 1)),
        _dev(2, D(2018, 6, 2)),
        _match(3, CALIB, D(2022, 11, 20)),
        _match(4, HOLDOUT, D(2024, 6, 14)),
    ]
    plan = assign_tournament_split(matches)

    assert set(plan.match_fold) == {1, 2}


def test_chronology_holds_between_top_level_splits() -> None:
    """Chronological separation applies between the splits, not within development."""
    matches = [
        _dev(1, D(2018, 7, 15)),
        _dev(2, D(2021, 7, 11)),
        _match(3, CALIB, D(2022, 12, 18)),
        _match(4, HOLDOUT, D(2024, 6, 14)),
    ]
    plan = assign_tournament_split(matches)

    dev_dates = {_date(m) for m in matches if plan.split_of(m.match_id) == "development"}
    calib_dates = {_date(m) for m in matches if plan.split_of(m.match_id) == "calibration"}
    holdout_dates = {_date(m) for m in matches if plan.split_of(m.match_id) == "holdout"}
    assert max(dev_dates) < min(calib_dates)
    assert max(calib_dates) < min(holdout_dates)


def test_assignment_is_deterministic_under_row_order_changes() -> None:
    matches = [
        _dev(101, D(2018, 6, 1)),
        _dev(102, D(2018, 6, 2)),
        _dev(103, D(2018, 6, 2)),
        _dev(104, D(2018, 6, 3)),
        _match(201, CALIB, D(2022, 11, 20)),
        _match(202, CALIB, D(2022, 12, 3)),
        _match(301, HOLDOUT, D(2024, 6, 14)),
        _match(302, HOLDOUT, D(2024, 7, 14)),
    ]
    base = assign_tournament_split(matches)

    for shuffled in (
        list(reversed(matches)),
        matches[3:] + matches[:3],
        sorted(matches, key=lambda r: r.match_id % 3),
    ):
        assert assign_tournament_split(shuffled) == base


def test_null_match_date_raises_naming_the_match() -> None:
    matches = [_dev(1, D(2018, 6, 1)), _dev(2, None)]
    with pytest.raises(SplitAssignmentError, match=r"match 2 has no match_date"):
        assign_tournament_split(matches)

    calib_missing_date = [_dev(1, D(2018, 6, 1)), _match(3, CALIB, None)]
    with pytest.raises(SplitAssignmentError, match=r"match 3 has no match_date"):
        assign_tournament_split(calib_missing_date)


def test_duplicate_match_id_raises() -> None:
    matches = [_dev(1, D(2018, 6, 1)), _dev(1, D(2018, 6, 2))]
    with pytest.raises(SplitAssignmentError, match=r"duplicate match_id 1"):
        assign_tournament_split(matches)


def test_out_of_scope_pair_raises() -> None:
    matches = [_dev(1, D(2018, 6, 1)), _match(2, (11, 11), D(2018, 6, 2))]
    with pytest.raises(SplitAssignmentError, match=r"match 2 has scope \(11, 11\)"):
        assign_tournament_split(matches)


def test_empty_input_raises() -> None:
    with pytest.raises(SplitAssignmentError, match="empty input"):
        assign_tournament_split([])


def test_empty_development_set_raises() -> None:
    matches = [_match(3, CALIB, D(2022, 11, 20)), _match(4, HOLDOUT, D(2024, 6, 14))]
    with pytest.raises(SplitAssignmentError, match="no development matches"):
        assign_tournament_split(matches)


def test_match_record_fields_are_the_target_free_contract() -> None:
    """The input type carries no outcome, player or shot-level field; adding one is a contract
    change that this test makes visible."""
    assert [f.name for f in fields(MatchRecord)] == [
        "match_id",
        "competition_id",
        "season_id",
        "match_date",
    ]


def test_split_plan_accessors() -> None:
    plan = assign_tournament_split(
        [
            _dev(1, D(2018, 6, 1)),
            _match(2, CALIB, D(2022, 11, 20)),
            _match(3, HOLDOUT, D(2024, 6, 14)),
        ]
    )

    assert plan.fold_of(1) == 0
    with pytest.raises(SplitAssignmentError, match="not a development match"):
        plan.fold_of(2)
    with pytest.raises(SplitAssignmentError, match="no split assignment"):
        plan.split_of(999)


def test_csv_rendering_is_stable_and_pinned_shape() -> None:
    matches = [
        _dev(1, D(2018, 6, 1)),
        _dev(2, D(2018, 6, 2)),
        _match(3, CALIB, D(2022, 11, 20)),
        _match(4, HOLDOUT, D(2024, 6, 14)),
    ]
    plan = assign_tournament_split(matches)

    expected = (
        "match_id,competition_id,season_id,match_date,split,fold\n"
        "1,43,3,2018-06-01,development,0\n"
        "2,43,3,2018-06-02,development,1\n"
        "3,43,106,2022-11-20,calibration,\n"
        "4,55,282,2024-06-14,holdout,\n"
    )
    assert render_match_assignments_csv(plan, matches) == expected
    assert CSV_HEADER == "match_id,competition_id,season_id,match_date,split,fold"


def test_csv_rendering_rejects_an_unassigned_match() -> None:
    matches = [_dev(1, D(2018, 6, 1))]
    plan = SplitPlan(
        match_split={2: "holdout"},
        match_fold={},
    )
    with pytest.raises(SplitAssignmentError, match="no split assignment"):
        render_match_assignments_csv(plan, matches)


def test_manifest_summaries_are_label_free_counts_and_dates() -> None:
    matches = [
        _dev(1, D(2018, 6, 1)),
        _dev(2, D(2018, 6, 2)),
        _dev(3, D(2018, 6, 3)),
        _dev(4, D(2018, 6, 4)),
        _dev(5, D(2018, 6, 5)),
        _dev(6, D(2018, 6, 6)),
        _dev(7, D(2018, 6, 7)),
        _match(8, CALIB, D(2022, 11, 20)),
        _match(9, HOLDOUT, D(2024, 6, 14)),
    ]
    plan = assign_tournament_split(matches)
    eligible_shots = {1: 5, 2: 0, 3: 1, 4: 1, 5: 1, 6: 0, 7: 0, 8: 3, 9: 2}

    splits, folds = manifest_summaries(plan, matches, eligible_shots)

    assert splits == {
        "development": {
            "matches": 7,
            "eligible_shots": 8,
            "date_first": "2018-06-01",
            "date_last": "2018-06-07",
        },
        "calibration": {
            "matches": 1,
            "eligible_shots": 3,
            "date_first": "2022-11-20",
            "date_last": "2022-11-20",
        },
        "holdout": {
            "matches": 1,
            "eligible_shots": 2,
            "date_first": "2024-06-14",
            "date_last": "2024-06-14",
        },
    }
    assert folds == {
        "0": {"matches": 2, "date_first": "2018-06-01", "date_last": "2018-06-06"},
        "1": {"matches": 2, "date_first": "2018-06-02", "date_last": "2018-06-07"},
        "2": {"matches": 1, "date_first": "2018-06-03", "date_last": "2018-06-03"},
        "3": {"matches": 1, "date_first": "2018-06-04", "date_last": "2018-06-04"},
        "4": {"matches": 1, "date_first": "2018-06-05", "date_last": "2018-06-05"},
    }
