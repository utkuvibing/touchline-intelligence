"""Unit contracts for the WP2.4 development-cohort loader. No database.

Byte-pin behaviour, CSV parsing and the structural holdout lock are each tested without a server:

- pinned artifacts must be canonical LF (a CRLF checkout fails loudly, never silently normalized);
- a digest mismatch and a wrong CSV header both fail with named errors;
- parsing admits only development matches to the development set and rejects malformed rows;
- the loader issues a ``match_id = ANY(%s)`` query restricted to development ids and re-checks every
  returned row against the development set — a row from a non-development match raises even if the
  parameterization is broken (the structural holdout lock).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from touchline.modeling.dataset import (
    ArtifactHashMismatchError,
    AssignmentDataError,
    DevelopmentLeakError,
    MatchAssignments,
    NonCanonicalArtifactError,
    load_development_cohort,
    load_partition_cohort,
    parse_match_assignments,
    verify_assignments_csv,
    verify_cohort_sql,
)

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "data" / "model" / "wp2_3_split_manifest.json"
CSV_PATH = ROOT / "data" / "model" / "wp2_3_match_assignments.csv"
COHORT_SQL_PATH = ROOT / "backend" / "sql" / "wp2_1" / "01_model_shot_cohort.sql"

VALID_CSV = "\n".join(
    [
        "match_id,competition_id,season_id,match_date,split,fold",
        "1,43,3,2018-06-14,development,0",
        "2,55,43,2020-06-11,development,1",
        "3,43,106,2022-11-20,calibration,",
        "4,55,282,2024-06-14,holdout,",
        "",
    ]
)


def _manifest() -> dict[str, object]:
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_assignments_csv_verifies_canonical_lf_and_hash_from_committed_manifest() -> None:
    data = CSV_PATH.read_bytes()
    expected = _manifest()["assignments_sha256"]
    assert isinstance(expected, str)
    verify_assignments_csv(data, expected)  # must not raise


def test_crlf_checkout_fails_loudly_never_normalized() -> None:
    data = CSV_PATH.read_bytes()
    crlf = data.replace(b"\n", b"\r\n")
    expected = _manifest()["assignments_sha256"]
    assert isinstance(expected, str)
    with pytest.raises(NonCanonicalArtifactError):
        verify_assignments_csv(crlf, expected)


def test_hash_mismatch_fails_for_assignments_and_cohort_sql() -> None:
    data = CSV_PATH.read_bytes()
    wrong = "0" * 64
    with pytest.raises(ArtifactHashMismatchError):
        verify_assignments_csv(data, wrong)
    sql = COHORT_SQL_PATH.read_bytes()
    with pytest.raises(ArtifactHashMismatchError):
        verify_cohort_sql(sql, wrong)


def test_wrong_csv_header_fails() -> None:
    data = CSV_PATH.read_bytes()
    expected = _manifest()["assignments_sha256"]
    assert isinstance(expected, str)
    broken = b"wrong,header\n" + data.split(b"\n", 1)[1]
    with pytest.raises(ValueError):
        verify_assignments_csv(broken, expected)


def test_cohort_sql_verifies_against_committed_manifest_and_returns_sql() -> None:
    sql = COHORT_SQL_PATH.read_bytes()
    expected = _manifest()["cohort_sql_sha256"]
    assert isinstance(expected, str)
    text = verify_cohort_sql(sql, expected)
    assert "is_goal" in text


def test_parse_assignments_admits_development_only() -> None:
    assignments = parse_match_assignments(VALID_CSV)
    assert assignments.development_match_ids == frozenset({1, 2})
    assert assignments.fold_of == {1: 0, 2: 1}
    # Calibration and holdout matches are read but never in the development set.
    assert 3 not in assignments.development_match_ids
    assert 4 not in assignments.development_match_ids


def test_parse_assignments_rejects_unknown_split_and_bad_fold() -> None:
    with pytest.raises(AssignmentDataError):
        parse_match_assignments(
            "match_id,competition_id,season_id,match_date,split,fold\n1,43,3,2018-06-14,outer,0\n"
        )
    with pytest.raises(AssignmentDataError):
        parse_match_assignments(
            "match_id,competition_id,season_id,match_date,split,fold\n"
            "1,43,3,2018-06-14,development,9\n"
        )
    with pytest.raises(AssignmentDataError):
        parse_match_assignments(
            "match_id,competition_id,season_id,match_date,split,fold\n"
            "9,55,282,2024-06-14,holdout,0\n"
        )


NOOP_TRANSACTION = None


class _FakeCursor:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows
        self.executed: list[str] = []
        self.params: tuple[object, ...] = ()

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        self.executed.append(sql)
        self.params = params

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows


class _FakeConnection:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.read_only = False
        self.rows = rows
        self.cursor_used: _FakeCursor | None = None

    def cursor(self) -> _FakeCursor:
        self.cursor_used = _FakeCursor(self.rows)
        return self.cursor_used

    def transaction(self) -> _NoopTransaction:
        return _NoopTransaction()


class _NoopTransaction:
    def __enter__(self) -> _NoopTransaction:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _fake_row(match_id: int, event_index: int, is_goal: int = 0) -> tuple[object, ...]:
    # Column order mirrors the loader's LOAD_COLUMNS projection.
    return (
        f"00000000-0000-0000-0000-{event_index:012d}",  # shot_id
        match_id,
        43,  # competition_id
        3,  # season_id
        100.0,  # raw_location_x
        40.0,  # raw_location_y
        None,  # under_pressure
        "Right Foot",  # body_part_name
        "Normal",  # technique_name
        "Regular Play",  # play_pattern_name
        None,  # first_time
        is_goal,  # is_goal
    )


def _fake_evaluation_row(match_id: int, event_index: int, is_goal: int = 0) -> tuple[object, ...]:
    # Column order mirrors the loader's EVALUATION_LOAD_COLUMNS projection.
    return (
        f"00000000-0000-0000-0000-{event_index:012d}",  # shot_id
        match_id,
        55,  # competition_id
        282,  # season_id
        100.0,  # raw_location_x
        40.0,  # raw_location_y
        None,  # under_pressure
        "Right Foot",  # body_part_name
        "Normal",  # technique_name
        "Regular Play",  # play_pattern_name
        None,  # first_time
        "Open Play",  # shot_type_name
        is_goal,  # is_goal
    )


def test_loader_runs_read_only_and_queries_development_ids_only() -> None:
    assignment = MatchAssignments(development_match_ids=frozenset({1, 2}), fold_of={1: 0, 2: 1})
    conn = _FakeConnection([_fake_row(1, 1), _fake_row(2, 2)])
    rows = load_development_cohort(conn, "SELECT 1", assignment)  # type: ignore[arg-type]
    assert conn.cursor_used is not None
    assert conn.cursor_used.executed[0] == "SET TRANSACTION READ ONLY"
    assert any("match_id = ANY(%s)" in sql for sql in conn.cursor_used.executed)
    ids = conn.cursor_used.params[0]
    assert isinstance(ids, list)
    assert ids == [1, 2]
    assert [row.match_id for row in rows] == [1, 2]
    assert [row.fold for row in rows] == [0, 1]


def test_loader_rejects_a_non_development_row_that_reaches_the_client() -> None:
    # The filter let a holdout match's row through; the structural re-check must catch it.
    assignment = MatchAssignments(development_match_ids=frozenset({1}), fold_of={1: 0})
    conn = _FakeConnection([_fake_row(1, 1), _fake_row(4, 2)])
    with pytest.raises(DevelopmentLeakError):
        load_development_cohort(conn, "SELECT 1", assignment)  # type: ignore[arg-type]


def test_evaluation_loader_reads_only_the_requested_locked_partition() -> None:
    assignment = MatchAssignments(
        development_match_ids=frozenset({1, 2}),
        fold_of={1: 0, 2: 1},
        match_ids_by_split={
            "development": frozenset({1, 2}),
            "calibration": frozenset({3}),
            "holdout": frozenset({4}),
        },
    )
    conn = _FakeConnection([_fake_evaluation_row(3, 3, 1)])
    rows = load_partition_cohort(conn, "SELECT 1", assignment, "calibration")  # type: ignore[arg-type]
    assert conn.cursor_used is not None
    assert any("match_id = ANY(%s)" in sql for sql in conn.cursor_used.executed)
    assert conn.cursor_used.params[0] == [3]
    assert rows[0].match_id == 3
    assert rows[0].fold is None
    assert rows[0].shot_type_name == "Open Play"


def test_evaluation_loader_rejects_a_row_from_another_partition() -> None:
    assignment = MatchAssignments(
        development_match_ids=frozenset({1}),
        fold_of={1: 0},
        match_ids_by_split={"calibration": frozenset({3}), "holdout": frozenset({4})},
    )
    conn = _FakeConnection([_fake_evaluation_row(4, 4)])
    with pytest.raises(AssignmentDataError):
        load_partition_cohort(conn, "SELECT 1", assignment, "calibration")  # type: ignore[arg-type]
