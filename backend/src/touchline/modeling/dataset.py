"""Development-cohort loader for WP2.4: byte-pinned, canonical-LF, development-only.

The loader sits on the WP2.3 lock and enforces it structurally:

- The pinned artifacts are verified byte-exact against their SHA-256 in the WP2.3 split manifest
  (canonical LF; any ``\\r`` in the checked-out bytes is a loud, named failure, never a silent
  normalization — WP2.4 contract §6).
- The cohort query is executed **inside** ``WHERE match_id = ANY(%s)`` filtered to development
  match ids only, server-side. Holdout and calibration labels never leave the database, and every
  returned row's match id is re-checked to be a development match: a leakage beyond the filter
  raises even if the SQL parameterization ever changed.
- The locked full-cohort anchors (2,872 development shots, 115 matches, fold shot sizes
  {570, 552, 602, 576, 572}) are asserted here with named errors on any deviation; the fold calls
  that run on synthetic integration data pass their own expected sizes through explicitly so the
  structural lock (development-only) is testable without the real cohort.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal

import psycopg

from touchline.features.geometry import distance_to_goal, visible_goal_angle
from touchline.modeling.preprocessing import ShotRow
from touchline.sealed_scope import SEALED_SCOPES, SEALED_SET_NAMES, SealedScopeError

CSV_HEADER = "match_id,competition_id,season_id,match_date,split,fold"
SPLIT_NAMES = ("development", "calibration", "holdout")
N_FOLDS = 5

#: Locked full-cohort development anchors (WP2.3 evidence, WP2.4 contract).
LOCKED_DEVELOPMENT_SHOTS = 2872
LOCKED_DEVELOPMENT_MATCHES = 115
LOCKED_FOLD_SHOT_SIZES: Mapping[int, int] = {0: 570, 1: 552, 2: 602, 3: 576, 4: 572}

#: The exact cohort columns the loader consumes, selected explicitly (never ``SELECT *``) so a
#: future change to the pinned cohort query cannot silently reorder the loader's reads.
LOAD_COLUMNS = (
    "shot_id, match_id, competition_id, season_id, raw_location_x, raw_location_y, "
    "under_pressure, body_part_name, technique_name, play_pattern_name, first_time, is_goal"
)

# WP2.7 evaluation projection.  The extra shot-type field is a descriptive slice only and never
# enters the frozen model feature matrix.
EVALUATION_LOAD_COLUMNS = (
    "shot_id, match_id, competition_id, season_id, raw_location_x, raw_location_y, "
    "under_pressure, body_part_name, technique_name, play_pattern_name, first_time, "
    "shot_type_name, is_goal"
)


class ArtifactIntegrityError(ValueError):
    """A pinned artifact failed byte-level verification."""


class NonCanonicalArtifactError(ArtifactIntegrityError):
    """The checked-out artifact bytes are not canonical LF (e.g. a CRLF checkout)."""


class ArtifactHashMismatchError(ArtifactIntegrityError):
    """The canonical artifact bytes hash to a digest different from the pinned manifest value."""


class AssignmentDataError(ValueError):
    """A match assignment the loader's contract does not define or does not admit."""


class CohortSizeError(ValueError):
    """The returned development cohort deviates from the locked row/match/fold anchors."""


class DevelopmentLeakError(AssignmentDataError):
    """A row whose match id is not a development match reached the client: a structural leak."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_assignments_csv(data: bytes, expected_sha256: str) -> None:
    """Verify the pinned match-assignment CSV: canonical LF, byte-pinned, correct header.

    Fails loudly on a CRLF checkout, a digest mismatch, or a wrong header; it never normalizes the
    bytes. This is byte-pin integrity, not content-canonical integrity.
    """
    verify_canonical_lf(data, "wp2_3_match_assignments.csv")
    verify_artifact_sha256(data, expected_sha256, "wp2_3_match_assignments.csv")
    first = data.split(b"\n", 1)[0].decode("utf-8")
    if first != CSV_HEADER:
        raise ArtifactIntegrityError(
            f"assignment CSV header {first!r} does not match the pinned {CSV_HEADER!r}"
        )


def verify_cohort_sql(data: bytes, expected_sha256: str) -> str:
    """Verify the WP2.1 cohort query: canonical LF and byte-pinned; returns its SQL text."""
    verify_canonical_lf(data, "01_model_shot_cohort.sql")
    verify_artifact_sha256(data, expected_sha256, "01_model_shot_cohort.sql")
    return data.decode("utf-8")


def verify_canonical_lf(data: bytes, artifact: str) -> None:
    if b"\r" in data:
        raise NonCanonicalArtifactError(
            f"{artifact} is not canonical LF (CRLF bytes present). Re-materialize it from a "
            "canonical checkout (see `git add --renormalize` in the WP2.4 contract) and do not "
            "silently normalize inside the loader."
        )


def verify_artifact_sha256(data: bytes, expected_sha256: str, artifact: str) -> None:
    actual = _sha256(data)
    if actual != expected_sha256:
        raise ArtifactHashMismatchError(
            f"{artifact} SHA-256 is {actual}, expected {expected_sha256}; hash-before-load refuses"
        )


@dataclass(frozen=True)
class MatchAssignments:
    """Development match ids and their fold numbers, parsed from the pinned assignment CSV."""

    development_match_ids: frozenset[int]
    fold_of: Mapping[int, int]
    match_ids_by_split: Mapping[str, frozenset[int]] = field(default_factory=dict)

    def ids_for(self, split: Literal["development", "calibration", "holdout"]) -> frozenset[int]:
        if split == "development":
            return self.development_match_ids
        return self.match_ids_by_split.get(split, frozenset())

    def fold(self, match_id: int) -> int:
        try:
            return self.fold_of[match_id]
        except KeyError:
            raise AssignmentDataError(
                f"match {match_id} is not a development match; folds exist for development only"
            ) from None


def parse_match_assignments(csv_text: str) -> MatchAssignments:
    """Parse the assignment CSV into the development match set and fold map.

    Rows of calibration and holdout matches are read (the file is the full 230-match lock) but
    never admitted to the development set; a row with an unknown split or a malformed field
    raises so a corrupted lock cannot be silently tolerated. A row carrying a sealed
    competition-season pair raises regardless of its split column: no development command may
    read a sealed set, so even a regenerated assignment file cannot smuggle one in.
    """
    lines = [line for line in csv_text.splitlines() if line.strip()]
    if not lines or lines[0] != CSV_HEADER:
        raise ArtifactIntegrityError("assignment CSV header is missing or malformed")
    dev_ids: set[int] = set()
    split_ids: dict[str, set[int]] = {name: set() for name in SPLIT_NAMES}
    fold_of: dict[int, int] = {}
    for lineno, line in enumerate(lines[1:], start=2):
        parts = line.split(",")
        if len(parts) != 6:
            raise AssignmentDataError(
                f"assignment CSV line {lineno} has {len(parts)} fields, expected 6"
            )
        match_id, comp, season, _date, split, fold_raw = parts
        try:
            scope = (int(comp), int(season))
        except ValueError:
            raise AssignmentDataError(
                f"assignment CSV line {lineno} has non-integer competition/season "
                f"{comp!r}/{season!r}"
            ) from None
        if scope in SEALED_SCOPES:
            raise SealedScopeError(
                f"assignment CSV line {lineno} has scope {scope} "
                f"({SEALED_SET_NAMES[scope]}), a sealed external evaluation set; development "
                "loaders must never read it"
            )
        if split not in SPLIT_NAMES:
            raise AssignmentDataError(f"assignment CSV line {lineno} has unknown split {split!r}")
        try:
            match_id_int = int(match_id)
        except ValueError:
            raise AssignmentDataError(
                f"assignment CSV line {lineno} has non-integer match id {match_id!r}"
            ) from None
        split_ids[split].add(match_id_int)
        if split == "development":
            try:
                fold_int = int(fold_raw)
            except ValueError:
                raise AssignmentDataError(
                    f"development match {match_id} has non-integer fold {fold_raw!r}"
                ) from None
            if not 0 <= fold_int < N_FOLDS:
                raise AssignmentDataError(
                    f"development match {match_id} has out-of-range fold {fold_int}"
                )
            dev_ids.add(match_id_int)
            fold_of[match_id_int] = fold_int
        elif fold_raw != "":
            raise AssignmentDataError(
                f"non-development match {match_id} must carry an empty fold, got {fold_raw!r}"
            )
    if not dev_ids:
        raise AssignmentDataError("assignment CSV contains no development matches")
    return MatchAssignments(
        development_match_ids=frozenset(dev_ids),
        fold_of=fold_of,
        match_ids_by_split=MappingProxyType(
            {split: frozenset(ids) for split, ids in split_ids.items()}
        ),
    )


def load_partition_cohort(
    conn: psycopg.Connection,
    cohort_sql: str,
    assignments: MatchAssignments,
    split: Literal["calibration", "holdout"],
) -> list[ShotRow]:
    """Load one non-development partition for its single supervised WP2.7 phase.

    This function is intentionally not used by the development training commands.  The phase
    runner calls it exactly once for calibration and exactly once for the supervised holdout
    session, then keeps all real-row work in memory.
    """
    ids = assignments.ids_for(split)
    if not ids:
        raise AssignmentDataError(f"assignment CSV contains no {split} matches")
    body = cohort_sql.rstrip()
    if body.endswith(";"):
        body = body[:-1]
    sql = (
        f"SELECT {EVALUATION_LOAD_COLUMNS} FROM ({body}) AS cohort "
        "WHERE match_id = ANY(%s) ORDER BY shot_id"
    )
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute(sql, (sorted(ids),))
        raw_rows = cur.fetchall()
    allowed = set(ids)
    rows: list[ShotRow] = []
    seen_shots: set[str] = set()
    for raw in raw_rows:
        shot_id = str(raw[0])
        match_id = int(raw[1])
        if shot_id in seen_shots:
            raise AssignmentDataError(f"duplicate {split} shot id {shot_id}")
        seen_shots.add(shot_id)
        if match_id not in allowed:
            raise AssignmentDataError(
                f"row for match {match_id} is not in the locked {split} assignment"
            )
        rows.append(
            ShotRow(
                shot_id=shot_id,
                match_id=match_id,
                fold=None,
                competition_id=int(raw[2]),
                season_id=int(raw[3]),
                y=int(raw[12]),
                distance_to_goal=distance_to_goal(float(raw[4]), float(raw[5])),
                visible_goal_angle=visible_goal_angle(float(raw[4]), float(raw[5])),
                body_part_name=str(raw[7]),
                technique_name=str(raw[8]),
                play_pattern_name=str(raw[9]),
                first_time=_as_optional_bool(raw[10]),
                under_pressure=_as_optional_bool(raw[6]),
                shot_type_name=str(raw[11]),
            )
        )
    return rows


def load_development_cohort(
    conn: psycopg.Connection,
    cohort_sql: str,
    assignments: MatchAssignments,
) -> list[ShotRow]:
    """Load development rows only, computing the two geometry features.

    The cohort SQL is embedded as a subquery and the row set is restricted to development match ids
    server-side, inside a ``READ ONLY`` transaction (the repo's established pattern: the guard is
    per-transaction, so a caller reusing the connection for setup/teardown is unaffected). Every
    returned row is re-checked against the development set, so a leakage beyond the filter raises
    ``DevelopmentLeakError`` even if the parameterization ever broke. Callers that want an
    unavoidably read-only session additionally open their own connection with ``read_only`` set at
    connect time (the training entry point does this).
    """
    body = cohort_sql.rstrip()
    if body.endswith(";"):
        body = body[:-1]
    sql = f"SELECT {LOAD_COLUMNS} FROM ({body}) AS cohort WHERE match_id = ANY(%s) ORDER BY shot_id"
    # Sort the bound ids and order the result set explicitly: the loader's row order is part of
    # reproducibility and must never depend on PostgreSQL's unspecified default row order.
    development_ids = sorted(assignments.development_match_ids)
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute(sql, (development_ids,))
        raw_rows = cur.fetchall()
    rows: list[ShotRow] = []
    development_set = assignments.development_match_ids
    for raw in raw_rows:
        match_id = int(raw[1])
        if match_id not in development_set:
            raise DevelopmentLeakError(
                f"row for match {match_id} is not a development match and reached the client; "
                "the development-only filter is broken"
            )
        location_x = float(raw[4])
        location_y = float(raw[5])
        rows.append(
            ShotRow(
                shot_id=str(raw[0]),
                match_id=match_id,
                fold=assignments.fold(match_id),
                competition_id=int(raw[2]),
                season_id=int(raw[3]),
                y=int(raw[11]),
                distance_to_goal=distance_to_goal(location_x, location_y),
                visible_goal_angle=visible_goal_angle(location_x, location_y),
                body_part_name=str(raw[7]),
                technique_name=str(raw[8]),
                play_pattern_name=str(raw[9]),
                first_time=_as_optional_bool(raw[10]),
                under_pressure=_as_optional_bool(raw[6]),
            )
        )
    return rows


def _as_optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def verify_development_anchor(
    rows: Sequence[ShotRow],
    expected_shots: int = LOCKED_DEVELOPMENT_SHOTS,
    expected_matches: int = LOCKED_DEVELOPMENT_MATCHES,
    expected_fold_sizes: Mapping[int, int] = LOCKED_FOLD_SHOT_SIZES,
) -> None:
    """Assert the locked development anchors, naming any deviation.

    Called by the training entry point (and the full-cohort evidence) with the locked constants;
    integration tests that run on synthetic data pass their own expected sizes through so the
    structural development-only lock is still exercised on small populations.
    """
    if len(rows) != expected_shots:
        raise CohortSizeError(
            f"development cohort has {len(rows)} shots, expected {expected_shots}"
        )
    match_count = len({row.match_id for row in rows})
    if match_count != expected_matches:
        raise CohortSizeError(
            f"development cohort spans {match_count} matches, expected {expected_matches}"
        )
    fold_sizes: dict[int, int] = {}
    for row in rows:
        if row.fold is None:
            raise CohortSizeError(
                f"development row for match {row.match_id} has no fold assignment"
            )
        fold_sizes[row.fold] = fold_sizes.get(row.fold, 0) + 1
    for fold, expected in expected_fold_sizes.items():
        actual = fold_sizes.get(fold, 0)
        if actual != expected:
            raise CohortSizeError(
                f"development fold {fold} has {actual} shots, expected {expected}"
            )
