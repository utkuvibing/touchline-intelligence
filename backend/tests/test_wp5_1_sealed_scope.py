"""Unit contracts for M5 WP5.1 sealed external evaluation sets. No database or network required.

These tests pin the sealing contract: the enforced scope pairs, the machine-readable registry's
agreement with those constants, loud rejection at every development loader entry point
(``collect_cohort``, ``run_ingestion``, ``collect``, the split assignment, the assignment-CSV
parser), and the label-free behavior of the structural-validation scanner.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest

from touchline.ingest.run import CORE_COHORT, SourceValueError, collect_cohort, run_ingestion
from touchline.modeling.dataset import (
    ArtifactIntegrityError,
    AssignmentDataError,
    parse_match_assignments,
)
from touchline.modeling.splits import MatchRecord, assign_tournament_split
from touchline.sealed_scope import (
    REGISTRY_PATH,
    SEALED_SCOPES,
    SEALED_SET_NAMES,
    SealedScopeError,
    load_registry,
    require_unsealed_scope,
    require_unsealed_scopes,
)
from touchline.sealed_structural_check import (
    EventScan,
    MatchFileCheck,
    ScopeResult,
    _MutableScan,
    render_report,
    scan_event_payload,
    validate_match_payload,
)

D = dt.date

AFCON = (1267, 107)
COPA = (223, 282)


class _NeverTouchSource:
    """A source that must never be reached once a sealed scope is rejected."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"sealed-scope guard failed; source.{name} was touched")


def _fail_factory() -> object:
    raise AssertionError("sealed-scope guard failed; a database connection was opened")


def test_sealed_scopes_are_the_two_m5_tournament_pairs() -> None:
    """The constants themselves are the contract; mutating them must break this test."""
    assert frozenset({AFCON, COPA}) == SEALED_SCOPES
    assert SEALED_SET_NAMES == {AFCON: "AFCON 2023", COPA: "Copa America 2024"}
    # The season id 282 belongs to both Euro 2024 (55, 282) and Copa America 2024 (223, 282):
    # every check must compare the full pair, never a bare season id.
    assert (55, 282) not in SEALED_SCOPES


def test_registry_agrees_with_enforced_constants() -> None:
    payload = load_registry(REGISTRY_PATH)
    sealed = {
        (entry["competition_id"], entry["season_id"]): entry["name"]
        for entry in payload["sealed_sets"]
    }
    assert sealed == SEALED_SET_NAMES
    pool = {(entry["competition_id"], entry["season_id"]) for entry in payload["development_pool"]}
    assert pool == set(CORE_COHORT)
    assert all(entry["status"] == "sealed" for entry in payload["sealed_sets"])
    assert all(
        entry["permitted_access"] == "target_free_structural_only"
        for entry in payload["sealed_sets"]
    )


def test_core_cohort_scopes_are_never_sealed() -> None:
    require_unsealed_scopes(CORE_COHORT)
    for scope in CORE_COHORT:
        require_unsealed_scope(scope)


@pytest.mark.parametrize("scope", [AFCON, COPA])
def test_single_scope_guard_names_the_sealed_set(scope: tuple[int, int]) -> None:
    with pytest.raises(SealedScopeError) as excinfo:
        require_unsealed_scope(scope)
    assert SEALED_SET_NAMES[scope] in str(excinfo.value)
    assert "target_free_structural_only" in str(excinfo.value)


def test_collect_cohort_rejects_sealed_scope_before_touching_the_source() -> None:
    with pytest.raises(SealedScopeError):
        collect_cohort(_NeverTouchSource(), scopes=[*CORE_COHORT[:2], AFCON])  # type: ignore[arg-type]


def test_run_ingestion_rejects_sealed_scope_before_opening_a_connection() -> None:
    with pytest.raises(SealedScopeError):
        run_ingestion(_fail_factory, _NeverTouchSource(), scopes=[AFCON])  # type: ignore[arg-type]


def test_empty_scope_collections_keep_their_own_policy() -> None:
    with pytest.raises(SourceValueError):
        collect_cohort(_NeverTouchSource(), scopes=())  # type: ignore[arg-type]
    with pytest.raises(SealedScopeError):
        require_unsealed_scopes([AFCON])


def test_split_assignment_rejects_a_sealed_match_record() -> None:
    records = [
        MatchRecord(1, 43, 3, D(2018, 6, 1)),
        MatchRecord(2, COPA[0], COPA[1], D(2024, 6, 20)),
    ]
    with pytest.raises(SealedScopeError) as excinfo:
        assign_tournament_split(records)
    assert "Copa America 2024" in str(excinfo.value)


CSV_HEADER = "match_id,competition_id,season_id,match_date,split,fold"


def _csv(*rows: str) -> str:
    return "\n".join([CSV_HEADER, *rows]) + "\n"


def test_assignment_csv_parser_rejects_a_smuggled_sealed_row_in_any_split() -> None:
    dev_row = "9001,43,3,2018-06-15,development,0"
    afcon_as_holdout = "9002,1267,107,2024-01-13,holdout,"
    with pytest.raises(SealedScopeError) as excinfo:
        parse_match_assignments(_csv(dev_row, afcon_as_holdout))
    assert "AFCON 2023" in str(excinfo.value)

    copa_as_development = "9003,223,282,2024-06-20,development,1"
    with pytest.raises(SealedScopeError):
        parse_match_assignments(_csv(dev_row, copa_as_development))


def test_assignment_csv_parser_still_rejects_malformed_fields() -> None:
    bad_season = "9001,43,notanint,2018-06-15,development,0"
    with pytest.raises(AssignmentDataError):
        parse_match_assignments(_csv(bad_season))
    with pytest.raises(ArtifactIntegrityError):
        parse_match_assignments("wrong header\n")


def test_committed_assignment_csv_parses_cleanly() -> None:
    """The real lock contains no sealed pair, so the new guard must be invisible to it."""
    csv_path = Path("data/model/wp2_3_match_assignments.csv")
    assignments = parse_match_assignments(csv_path.read_text(encoding="utf-8"))
    assert len(assignments.development_match_ids) == 115


def test_event_scan_counts_violations_and_admits_the_documented_exception() -> None:
    scan = _MutableScan()
    scan_event_payload(
        [
            {
                "id": "a",
                "index": 1,
                "period": 1,
                "timestamp": "00:00:01.000",
                "type": {"name": "Pass"},
                "possession": 1,
                "possession_team": {"id": 1},
                "team": {"id": 1},
                "location": [120.1, 40.0],
            },
            {
                "id": "b",
                "index": 2,
                "period": 1,
                "timestamp": "00:00:02.000",
                "type": {"name": "Pass"},
                "possession": 1,
                "possession_team": {"id": 1},
                "team": {"id": 1},
                "location": [120.2, 40.0],
            },
            {
                "id": "c",
                "index": 3,
                "period": 1,
                "timestamp": "00:00:03.000",
                "type": {"name": "Pass"},
                "possession": 1,
                "possession_team": {"id": 1},
                "team": {"id": 1},
                "location": [-1.0, 80.1],
            },
            {
                "id": "d",
                "index": 4,
                "period": 1,
                "timestamp": "00:00:04.000",
                "type": {"name": "Half End"},
                "possession": 1,
                "possession_team": {"id": 1},
                "team": {"id": 1},
            },
        ],
        scan,
    )
    assert scan.locations_scanned == 3
    assert scan.coordinate_violations == 2


def test_event_scan_flags_schema_failures_without_reading_outcomes() -> None:
    scan = _MutableScan()
    scan_event_payload([{"id": "x"}], scan)
    assert scan.schema_failures == 1
    assert scan.event_files_parsed == 1


def test_match_payload_validation_checks_identity_not_content() -> None:
    payload = [
        {
            "match_id": 1,
            "match_date": "2024-01-13",
            "kick_off": "20:00",
            "competition": {"competition_id": AFCON[0]},
            "season": {"season_id": AFCON[1]},
            "home_team": {"home_team_id": 1},
            "away_team": {"away_team_id": 2},
        }
    ]
    check = validate_match_payload(payload, "matches/1267/107.json", "sha", 10, AFCON)
    assert check.parse_success
    mismatched = validate_match_payload(
        [{**payload[0], "season": {"season_id": 999}}], "p", "sha", 10, AFCON
    )
    assert mismatched.scope_mismatches == 1
    assert not mismatched.parse_success


def test_render_report_contains_no_outcome_bearing_section() -> None:
    match_file = MatchFileCheck(
        relative_path="matches/1267/107.json",
        sha256="ab" * 32,
        byte_count=12345,
        match_count=52,
        unique_match_ids=52,
        missing_keys_by_record=0,
        scope_mismatches=0,
        parse_success=True,
    )
    result = ScopeResult(
        name="AFCON 2023",
        scope=AFCON,
        match_file=match_file,
        events=EventScan(
            matches_scanned=52,
            event_files_parsed=52,
            lineup_files_parsed=52,
            schema_failures=0,
            locations_scanned=40000,
            coordinate_violations=0,
            min_x=0.0,
            max_x=120.1,
            min_y=0.0,
            max_y=80.0,
        ),
    )
    report = render_report([result], "2026-08-25T00:00:00Z")
    assert "**Overall: PASS**" in report
    assert "no shot outcomes, goal counts, conversion rates" in report
    # The report states the prohibition; it must never carry an actual aggregate of outcomes.
    assert "conversion_rate" not in report
    assert "is_goal" not in report
