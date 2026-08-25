"""The single target-free fold primitive for the preregistered v2 nested protocol (M5 WP5.2).

The WP5.2 contract freezes the executable fold semantics; this module *is* that freeze. M6 and
M7 must consume exactly these functions, driven only by ``data/model/v2_protocol.json`` —
reimplementing fold logic elsewhere is prohibited by the contract. Only the materialized
fold-manifest artifact remains deferred to M7's evaluation harness.

Semantics frozen here:

- **Outer** — exactly four leave-one-tournament-out scopes named in the config, iterated in the
  fixed order they are listed; each development tournament is the untouched outer holdout exactly
  once.
- **Inner** — match-grouped CV inside each outer training partition: matches sorted by
  ``(match_date, match_id)``, assigned ``inner_fold = index % k`` with ``k = 5``; no shuffling and
  no seed, because assignment is fully deterministic (the only preregistered random seed in v2 is
  the bootstrap seed).
- **Target-free by construction** — inputs carry match identity, scope and date only. A NULL date,
  a duplicate match id, an out-of-cohort scope or a sealed external set fails loudly before any
  partition exists.

Like ``splits.py``, the fold objects are deterministic match-grouped partitions: not temporal,
not forward-chaining; no chronological claim is made within development.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from touchline.modeling.splits import MatchRecord
from touchline.sealed_scope import SEALED_SCOPES, SEALED_SET_NAMES, SealedScopeError

#: Default location of the machine-readable protocol config, relative to the repository root.
PROTOCOL_CONFIG_PATH = Path("data/model/v2_protocol.json")

#: The frozen inner split count. Locked by WP5.2; changing it is a protocol change, not a tune.
INNER_SPLIT_COUNT = 5


class FoldConstructionError(ValueError):
    """A match set or config the frozen fold semantics cannot partition.

    A ValueError subclass so callers can catch it precisely. Every raise site names the offending
    match, scope or config key and the rule it violated: an ambiguous partition is a fact worth
    surfacing, never something to paper over.
    """


@dataclass(frozen=True, slots=True)
class TournamentScope:
    """One competition-season pair, the identity a LOTO fold holds out."""

    competition_id: int
    season_id: int

    @property
    def pair(self) -> tuple[int, int]:
        return (self.competition_id, self.season_id)


@dataclass(frozen=True, slots=True)
class OuterFoldSpec:
    """One outer leave-one-tournament-out fold, in the config's fixed iteration order."""

    outer_fold: str
    holdout_tournament: str
    scope: TournamentScope


def load_gate_config(path: Path = PROTOCOL_CONFIG_PATH) -> Mapping[str, Any]:
    """Load the machine-readable protocol config as an immutable mapping."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise FoldConstructionError(
            f"{path}: protocol config must be a JSON object, got {type(payload).__name__}"
        )
    return cast(Mapping[str, Any], MappingProxyType(payload))


def development_pool_scopes(config: Mapping[str, Any]) -> frozenset[tuple[int, int]]:
    """The competition-season pairs of the v2 development pool, from the config."""
    pool = config.get("development_pool")
    if not isinstance(pool, list) or not pool:
        raise FoldConstructionError("protocol config: development_pool must be a non-empty list")
    scopes: set[tuple[int, int]] = set()
    for entry in pool:
        if not isinstance(entry, dict):
            raise FoldConstructionError("protocol config: development_pool entries must be objects")
        try:
            scopes.add((entry["competition_id"], entry["season_id"]))
        except (KeyError, TypeError) as error:
            raise FoldConstructionError(
                f"protocol config: development_pool entry lacks a valid scope: {error}"
            ) from None
    return frozenset(scopes)


def outer_fold_specs(config: Mapping[str, Any]) -> tuple[OuterFoldSpec, ...]:
    """The outer LOTO fold specifications, in the config's fixed iteration order.

    Raises:
        FoldConstructionError: if the scheme is not leave-one-tournament-out, the iteration order
            is not declared fixed, scopes repeat or fall outside the config's development pool,
            or a scope collides with a sealed external evaluation set.
    """
    fold_rules = config.get("fold_rules")
    if not isinstance(fold_rules, dict):
        raise FoldConstructionError("protocol config: fold_rules must be an object")
    outer = fold_rules.get("outer")
    if not isinstance(outer, dict):
        raise FoldConstructionError("protocol config: fold_rules.outer must be an object")
    if outer.get("scheme") != "leave_one_tournament_out":
        raise FoldConstructionError(
            f"protocol config: outer fold scheme {outer.get('scheme')!r} is not "
            "'leave_one_tournament_out'"
        )
    if outer.get("iteration_order_fixed") is not True:
        raise FoldConstructionError(
            "protocol config: outer iteration_order_fixed must be true; the LOTO order is "
            "preregistered"
        )
    raw_scopes = outer.get("scopes")
    if not isinstance(raw_scopes, list) or len(raw_scopes) != 4:
        raise FoldConstructionError(
            "protocol config: fold_rules.outer.scopes must list exactly four LOTO scopes"
        )
    pool = development_pool_scopes(config)
    specs: list[OuterFoldSpec] = []
    seen_pairs: set[tuple[int, int]] = set()
    seen_names: set[str] = set()
    for entry in raw_scopes:
        if not isinstance(entry, dict):
            raise FoldConstructionError("protocol config: outer scope entries must be objects")
        try:
            name = entry["outer_fold"]
            tournament = entry["holdout_tournament"]
            pair = (entry["competition_id"], entry["season_id"])
        except (KeyError, TypeError) as error:
            raise FoldConstructionError(
                f"protocol config: outer scope entry lacks required fields: {error}"
            ) from None
        if name in seen_names:
            raise FoldConstructionError(f"protocol config: duplicate outer fold name {name!r}")
        seen_names.add(name)
        if pair in seen_pairs:
            raise FoldConstructionError(
                f"protocol config: scope {pair} is held out by more than one outer fold"
            )
        seen_pairs.add(pair)
        if pair in SEALED_SCOPES:
            raise SealedScopeError(
                f"outer fold {name!r} holds out {pair} ({SEALED_SET_NAMES[pair]}), a sealed "
                "external evaluation set; sealed sets have no outer fold before M7 opens them"
            )
        if pair not in pool:
            raise FoldConstructionError(
                f"protocol config: outer fold {name!r} holds out {pair}, outside the "
                "development pool"
            )
        specs.append(
            OuterFoldSpec(
                outer_fold=name,
                holdout_tournament=tournament,
                scope=TournamentScope(pair[0], pair[1]),
            )
        )
    return tuple(specs)


def _sorted_validated(matches: Iterable[MatchRecord]) -> list[MatchRecord]:
    """Validate the shared loud guards and return matches sorted by ``(match_date, match_id)``."""
    records = list(matches)
    if not records:
        raise FoldConstructionError("no matches provided; the fold partition is undefined")
    seen: set[int] = set()
    for record in records:
        if record.match_id in seen:
            raise FoldConstructionError(f"duplicate match_id {record.match_id}")
        seen.add(record.match_id)
        scope_pair = (record.competition_id, record.season_id)
        if scope_pair in SEALED_SCOPES:
            raise SealedScopeError(
                f"match {record.match_id} has scope {scope_pair} "
                f"({SEALED_SET_NAMES[scope_pair]}), a sealed external evaluation set; fold "
                "construction must never touch it"
            )
    validated: list[tuple[dt.date, int, MatchRecord]] = []
    for record in records:
        if record.match_date is None:
            raise FoldConstructionError(
                f"match {record.match_id} has no match_date; the inner rule sorts by "
                "(match_date, match_id) and cannot assign it"
            )
        validated.append((record.match_date, record.match_id, record))
    validated.sort()
    return [record for _, _, record in validated]


def assign_inner_folds(
    matches: Iterable[MatchRecord], *, split_count: int = INNER_SPLIT_COUNT
) -> Mapping[int, int]:
    """Assign every match to one deterministic match-grouped inner fold.

    Matches are sorted by ``(match_date, match_id)`` and assigned ``inner_fold =
    index % split_count``, so the result is identical under any input row order. Each match maps
    to exactly one fold through its identity; a match cannot be split across folds because folds
    are keyed by ``match_id``.

    Raises:
        FoldConstructionError: on an empty input, a duplicate match id, a missing match date, a
            sealed external scope, or a ``split_count`` below 2.
    """
    if split_count < 2:
        raise FoldConstructionError(
            f"split_count {split_count} is below 2; grouped cross-validation is undefined"
        )
    ordered = _sorted_validated(matches)
    assignment: dict[int, int] = {
        record.match_id: index % split_count for index, record in enumerate(ordered)
    }
    return cast(Mapping[int, int], MappingProxyType(assignment))


def inner_partition(
    assignment: Mapping[int, int], validation_fold: int, *, split_count: int = INNER_SPLIT_COUNT
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Split a completed inner-fold assignment into one disjoint (training, validation) pair.

    Both sides are returned sorted by match id. Together they cover every assigned match exactly
    once; neither side may be empty, so a degenerate partition fails loudly instead of producing
    a silent mis-evaluation.

    Raises:
        FoldConstructionError: if ``validation_fold`` is outside ``0..split_count-1``, any
            assignment value lies outside the same range, or either side of the partition is
            empty.
    """
    if not 0 <= validation_fold < split_count:
        raise FoldConstructionError(
            f"validation_fold {validation_fold} is outside 0..{split_count - 1}"
        )
    folds = set(assignment.values())
    if folds and max(folds) >= split_count:
        raise FoldConstructionError(
            f"assignment contains fold {max(folds)}, outside 0..{split_count - 1}"
        )
    training = sorted(m for m, f in assignment.items() if f != validation_fold)
    validation = sorted(m for m, f in assignment.items() if f == validation_fold)
    if not training or not validation:
        raise FoldConstructionError(
            f"inner partition for validation fold {validation_fold} is degenerate "
            f"({len(training)} training / {len(validation)} validation matches)"
        )
    return tuple(training), tuple(validation)


def outer_partition(
    matches: Iterable[MatchRecord],
    specs: Sequence[OuterFoldSpec],
    spec: OuterFoldSpec,
) -> tuple[tuple[MatchRecord, ...], tuple[MatchRecord, ...]]:
    """Partition matches into one outer fold's (training, untouched-holdout) record tuples.

    Both sides are sorted by ``(match_date, match_id)`` for determinism. Every input match must
    belong to one of the given specs' scopes, so a foreign tournament cannot silently join a
    training partition; the held-out side must contain at least one match and so must the
    training side.

    Raises:
        FoldConstructionError: on an empty input, a duplicate match id, a missing match date, a
            scope outside the given specs, a spec not among ``specs``, or an empty side.
    """
    known = {other.scope.pair for other in specs}
    if spec.scope.pair not in known:
        raise FoldConstructionError(
            f"spec {spec.outer_fold!r} is not among the supplied outer fold specifications"
        )
    ordered = _sorted_validated(matches)
    held_out: list[MatchRecord] = []
    training: list[MatchRecord] = []
    for record in ordered:
        scope_pair = (record.competition_id, record.season_id)
        if scope_pair not in known:
            raise FoldConstructionError(
                f"match {record.match_id} has scope {scope_pair}, outside every supplied outer "
                "fold specification"
            )
        (held_out if scope_pair == spec.scope.pair else training).append(record)
    if not held_out:
        raise FoldConstructionError(
            f"outer fold {spec.outer_fold!r} holds out no matches for scope {spec.scope.pair}"
        )
    if not training:
        raise FoldConstructionError(f"outer fold {spec.outer_fold!r} leaves no training matches")
    return tuple(training), tuple(held_out)
