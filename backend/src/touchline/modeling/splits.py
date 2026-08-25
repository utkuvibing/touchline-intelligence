"""Deterministic three-way split of the WP2.1 model-development cohort.

WP2.3 locks the named split before any model exists:

- development — World Cup 2018 `(43,3)` + Euro 2020 `(55,43)` — 115 matches;
- calibration — World Cup 2022 `(43,106)` — 64 matches;
- tournament holdout — Euro 2024 `(55,282)` — 51 matches.

**The holdout is a tournament holdout, not a temporal one.** Holding out Euro 2024 changes time
and competition composition together (ADR 0004), and that confounding is stated wherever the
holdout is evaluated rather than glossed over. It is locked from WP2.3 onward and is prohibited
from model, feature, calibration, threshold, and selection decisions. It is *locked, not blind*:
WP2.1's published full-cohort reconciliation already exposed descriptive per-tournament goal
counts, so this module makes no blindness claim. The single remaining permitted outcome use is
the pre-registered final evaluation after model selection.

**The five development folds are deterministic match-grouped folds**: a partition of development
matches that protects shared match context. They are NOT temporal folds and NOT forward-chaining
folds; no chronological claim is made within development or between folds. Chronological
separation applies only between the top-level splits (development < calibration < holdout).

**The assignment is target-free by construction.** `MatchRecord` carries exactly match identity,
scope and date — no outcome field exists to leak — and the module never reads a target: no goal,
label, provider xG, or outcome-derived statistic can enter the assignment or the fold balancing.

Match counts above are the measured four-tournament population (recorded in the WP2.3 split
contract and evidence report under `reports/`); the module itself is a pure function and
recomputes the assignment from whatever match records it is given.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from touchline.sealed_scope import SEALED_SCOPES, SEALED_SET_NAMES, SealedScopeError

SplitName = Literal["development", "calibration", "holdout"]

#: Locked scope pairs, from ADR 0004 and the WP2.1 cohort contract.
DEVELOPMENT_SCOPE = frozenset({(43, 3), (55, 43)})
CALIBRATION_SCOPE = (43, 106)
HOLDOUT_SCOPE = (55, 282)

ALL_SCOPES = DEVELOPMENT_SCOPE | {CALIBRATION_SCOPE, HOLDOUT_SCOPE}

#: Development folds. Locked by WP2.3: index % N_FOLDS over development matches sorted by
#: (match_date, match_id). Not temporal, not forward-chaining — see the module docstring.
N_FOLDS = 5

#: Canonical CSV header for the pinned match-assignment artifact.
CSV_HEADER = "match_id,competition_id,season_id,match_date,split,fold"

SPLIT_NAMES: tuple[SplitName, ...] = ("development", "calibration", "holdout")


class SplitAssignmentError(ValueError):
    """A match or match set the split contract does not define an assignment for.

    A ValueError subclass so callers can catch it precisely without the contract having to invent
    a sentinel. Every raise site names the offending match and the rule it violated: a match the
    split cannot assign is a fact about the data worth surfacing, not something to paper over.
    """


@dataclass(frozen=True, slots=True)
class MatchRecord:
    """One ingested match, with exactly the facts the split is defined over.

    The field set is part of the contract: it deliberately carries no outcome, no player and no
    shot-level information, so a target cannot structurally leak into the assignment. A unit test
    pins the field names.
    """

    match_id: int
    competition_id: int
    season_id: int
    match_date: dt.date | None


@dataclass(frozen=True)
class SplitPlan:
    """A complete match-level assignment.

    ``match_split`` maps every assigned match id to its top-level split and ``match_fold`` maps
    every development match id to its fold index in ``0..N_FOLDS-1``. Both are immutable views.
    """

    match_split: Mapping[int, SplitName]
    match_fold: Mapping[int, int]

    def split_of(self, match_id: int) -> SplitName:
        try:
            return self.match_split[match_id]
        except KeyError:
            raise SplitAssignmentError(f"match {match_id} has no split assignment") from None

    def fold_of(self, match_id: int) -> int:
        try:
            return self.match_fold[match_id]
        except KeyError:
            raise SplitAssignmentError(
                f"match {match_id} is not a development match; folds exist for development only"
            ) from None

    def matches_in(self, split: SplitName) -> tuple[int, ...]:
        return tuple(sorted(m for m, s in self.match_split.items() if s == split))


def _required_date(record: MatchRecord) -> dt.date:
    """Return the match date, raising on NULL.

    The split is a chronological object at the top level: development must precede calibration and
    calibration must precede the holdout, so a match without a date cannot be assigned. This is
    distinct from the fold sort guard below only in message, so mutation anchors stay unique.
    """
    if record.match_date is None:
        raise SplitAssignmentError(f"match {record.match_id} has no match_date")
    return record.match_date


def assign_tournament_split(matches: Iterable[MatchRecord]) -> SplitPlan:
    """Assign every match to one top-level split and every development match to one fold.

    The function is deterministic under input row order: the fold order is computed from an
    internal sort by ``(match_date, match_id)``, never from the order of the input.

    Raises:
        SplitAssignmentError: on an empty input, a duplicate match id, a competition/season pair
            outside the locked four-tournament core scope, a missing match date, or an empty
            development set.
    """
    records = list(matches)
    if not records:
        raise SplitAssignmentError("no matches provided; the split is undefined on an empty input")

    seen: set[int] = set()
    validated: list[tuple[int, int, int, dt.date]] = []
    for record in records:
        if record.match_id in seen:
            raise SplitAssignmentError(f"duplicate match_id {record.match_id}")
        seen.add(record.match_id)
        scope = (record.competition_id, record.season_id)
        if scope in SEALED_SCOPES:
            raise SealedScopeError(
                f"match {record.match_id} has scope {scope} "
                f"({SEALED_SET_NAMES[scope]}), a sealed external evaluation set; the split "
                "contract must never assign it"
            )
        if scope not in ALL_SCOPES:
            raise SplitAssignmentError(
                f"match {record.match_id} has scope {scope}, outside the locked "
                "four-tournament core cohort"
            )
        match_date = _required_date(record)
        validated.append((record.match_id, record.competition_id, record.season_id, match_date))

    match_split: dict[int, SplitName] = {}
    development: list[tuple[int, dt.date]] = []
    for match_id, competition_id, season_id, match_date in validated:
        scope = (competition_id, season_id)
        if scope == HOLDOUT_SCOPE:
            split: SplitName = "holdout"
        elif scope == CALIBRATION_SCOPE:
            split = "calibration"
        elif scope in DEVELOPMENT_SCOPE:
            split = "development"
        else:
            raise SplitAssignmentError(
                f"match {match_id} has scope {scope}, outside the locked four-tournament core "
                "cohort"
            )
        match_split[match_id] = split
        if split == "development":
            development.append((match_id, match_date))

    if not development:
        raise SplitAssignmentError("no development matches; the folds are undefined")

    development.sort(key=lambda pair: (pair[1], pair[0]))
    match_fold = {
        match_id: index % N_FOLDS for index, (match_id, _match_date) in enumerate(development)
    }

    return SplitPlan(
        match_split=MappingProxyType(match_split),
        match_fold=MappingProxyType(match_fold),
    )


def render_match_assignments_csv(plan: SplitPlan, matches: Iterable[MatchRecord]) -> str:
    """Render the canonical match-level assignment CSV.

    Rows are ordered by match_id and use LF line endings, so the rendering is byte-stable and can
    be pinned against a committed artifact. ``fold`` is empty for calibration and holdout matches.
    A match in the input that the plan does not assign raises, so an unassigned match cannot be
    rendered away.
    """
    by_id = {record.match_id: record for record in matches}
    lines = [CSV_HEADER]
    for match_id in sorted(by_id):
        split = plan.split_of(match_id)
        fold = plan.fold_of(match_id) if split == "development" else ""
        date = _required_date(by_id[match_id]).isoformat()
        lines.append(
            f"{match_id},{by_id[match_id].competition_id},"
            f"{by_id[match_id].season_id},{date},{split},{fold}"
        )
    return "\n".join(lines) + "\n"


def manifest_summaries(
    plan: SplitPlan,
    matches: Iterable[MatchRecord],
    eligible_shots: Mapping[int, int],
) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, object]]]:
    """Per-split and per-fold label-free summaries for the locked split manifest.

    ``eligible_shots`` maps a match id to its eligible-shot count, a label-free cohort count from
    ``backend/sql/wp2_3/01_split_match_population.sql``. Goal counts are deliberately absent from
    both returned structures: holdout outcomes belong to the final evaluation evidence, and the
    manifest schema is validated against these exact keys by the full-cohort tests.

    Returns ``(splits, folds)`` where each split entry has keys ``matches``, ``eligible_shots``,
    ``date_first``, ``date_last`` and each fold entry has keys ``matches``, ``date_first``,
    ``date_last``.
    """
    by_id = {record.match_id: record for record in matches}
    splits: dict[str, dict[str, object]] = {}
    folds: dict[str, dict[str, object]] = {}
    for split in SPLIT_NAMES:
        ids = plan.matches_in(split)
        dates = [_required_date(by_id[match_id]) for match_id in ids]
        splits[split] = {
            "matches": len(ids),
            "eligible_shots": sum(eligible_shots.get(match_id, 0) for match_id in ids),
            "date_first": min(dates).isoformat(),
            "date_last": max(dates).isoformat(),
        }
    for fold in range(N_FOLDS):
        fold_ids = sorted(m for m, f in plan.match_fold.items() if f == fold)
        dates = [_required_date(by_id[match_id]) for match_id in fold_ids]
        folds[str(fold)] = {
            "matches": len(fold_ids),
            "date_first": min(dates).isoformat(),
            "date_last": max(dates).isoformat(),
        }
    return splits, folds
