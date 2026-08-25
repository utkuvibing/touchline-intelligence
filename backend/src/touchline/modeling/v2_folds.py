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
  ``(match_date, match_id)``, assigned ``inner_fold = index % k`` with ``k`` read from the frozen
  config; no shuffling and no seed, because assignment is fully deterministic (the only
  preregistered random seed in v2 is the bootstrap seed). The primitive exposes no split-count
  override: caller code cannot make ``k`` silently differ from the preregistered value.
- **Scope-closed construction** — inputs carry match identity, scope and date only, and every
  match scope must lie inside the v2 development pool — or inside the declared outer-training
  partition when one is supplied — so a NULL date, duplicate id, foreign competition, sealed
  external set or another outer fold's held-out tournament fails loudly before any partition
  exists.

Like ``splits.py``, the fold objects are deterministic match-grouped partitions: not temporal,
not forward-chaining; no chronological claim is made within development.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from touchline.modeling.splits import MatchRecord
from touchline.sealed_scope import SEALED_SCOPES, SEALED_SET_NAMES, SealedScopeError

#: Default location of the machine-readable protocol config, relative to the repository root.
PROTOCOL_CONFIG_PATH = Path("data/model/v2_protocol.json")

#: The preregistered inner split count. Not a default and not an override: it is the tamper
#: anchor that the config's ``split_count`` must equal, so the two cannot silently diverge.
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


def inner_split_count(config: Mapping[str, Any]) -> int:
    """The preregistered inner split count, read from the frozen protocol config.

    There is deliberately no caller override anywhere in the primitive: ``k`` lives in
    ``data/model/v2_protocol.json``, and this validator makes silent divergence impossible by
    requiring the configured value to equal :data:`INNER_SPLIT_COUNT`.

    Raises:
        FoldConstructionError: if the value is missing, not an integer, below 2, or different
            from the preregistered count.
    """
    fold_rules = config.get("fold_rules")
    if not isinstance(fold_rules, dict):
        raise FoldConstructionError("protocol config: fold_rules must be an object")
    inner = fold_rules.get("inner")
    if not isinstance(inner, dict):
        raise FoldConstructionError("protocol config: fold_rules.inner must be an object")
    raw = inner.get("split_count")
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise FoldConstructionError(
            f"protocol config: inner split_count must be an integer, got {raw!r}"
        )
    if raw < 2:
        raise FoldConstructionError(
            f"protocol config: inner split_count {raw} is below 2; grouped cross-validation "
            "is undefined"
        )
    if raw != INNER_SPLIT_COUNT:
        raise FoldConstructionError(
            f"protocol config: inner split_count {raw} differs from the preregistered "
            f"{INNER_SPLIT_COUNT}; changing it is a protocol change that requires a new ADR"
        )
    return raw


def _sorted_validated(
    matches: Iterable[MatchRecord],
    *,
    allowed_scopes: frozenset[tuple[int, int]],
    scope_rule: str,
) -> list[MatchRecord]:
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
        if scope_pair not in allowed_scopes:
            raise FoldConstructionError(
                f"match {record.match_id} has scope {scope_pair}, outside {scope_rule}"
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
    matches: Iterable[MatchRecord],
    config: Mapping[str, Any],
    *,
    training_scopes: Collection[tuple[int, int]] | None = None,
) -> Mapping[int, int]:
    """Assign every match to one deterministic match-grouped inner fold.

    The split count is read from the frozen protocol config; there is no caller override. Matches
    are sorted by ``(match_date, match_id)`` and assigned ``inner_fold = index % k``, so the
    result is identical under any input row order. Each match maps to exactly one fold through
    its identity; a match cannot be split across folds because folds are keyed by ``match_id``.

    Every match scope must lie inside the v2 development pool — and inside the declared
    outer-training partition when ``training_scopes`` is given — so neither a foreign competition
    nor another outer fold's held-out tournament can enter inner CV. ``training_scopes`` may only
    narrow the development pool; a scope outside the pool is itself rejected.

    Raises:
        FoldConstructionError: on an empty input, a duplicate match id, a missing match date, a
            scope outside the permitted set, a ``training_scopes`` entry outside the development
            pool, or a config whose split count differs from the preregistered value.
        SealedScopeError: on any sealed external evaluation set.
    """
    pool = development_pool_scopes(config)
    if training_scopes is None:
        allowed = pool
        scope_rule = "the v2 development pool"
    else:
        requested = frozenset(training_scopes)
        if not requested:
            raise FoldConstructionError("declared outer-training partition is empty")
        outside = sorted(requested - pool)
        if outside:
            raise FoldConstructionError(
                f"declared outer-training partition contains scope(s) {outside} outside the "
                "v2 development pool; the primitive cannot widen beyond the frozen pool"
            )
        allowed = requested
        scope_rule = "the declared outer-training partition"
    ordered = _sorted_validated(matches, allowed_scopes=allowed, scope_rule=scope_rule)
    split_count = inner_split_count(config)
    assignment: dict[int, int] = {
        record.match_id: index % split_count for index, record in enumerate(ordered)
    }
    return cast(Mapping[int, int], MappingProxyType(assignment))


def inner_partition(
    assignment: Mapping[int, int],
    validation_fold: int,
    config: Mapping[str, Any],
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Split a completed inner-fold assignment into one disjoint (training, validation) pair.

    The split count is read from the frozen protocol config; there is no caller override. Both
    sides are returned sorted by match id. Together they cover every assigned match exactly once;
    neither side may be empty, so a degenerate partition fails loudly instead of producing a
    silent mis-evaluation.

    Raises:
        FoldConstructionError: if ``validation_fold`` is outside the configured range, any
            assignment value lies outside the same range, either side of the partition is empty,
            or the config's split count differs from the preregistered value.
    """
    split_count = inner_split_count(config)
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
            scope outside the supplied specs, a spec not among ``specs``, or an empty side.
    """
    known = {other.scope.pair for other in specs}
    if spec.scope.pair not in known:
        raise FoldConstructionError(
            f"spec {spec.outer_fold!r} is not among the supplied outer fold specifications"
        )
    ordered = _sorted_validated(
        matches,
        allowed_scopes=frozenset(known),
        scope_rule="the supplied outer fold specifications",
    )
    held_out = [
        record for record in ordered if (record.competition_id, record.season_id) == spec.scope.pair
    ]
    training = [
        record for record in ordered if (record.competition_id, record.season_id) != spec.scope.pair
    ]
    if not held_out:
        raise FoldConstructionError(
            f"outer fold {spec.outer_fold!r} holds out no matches for scope {spec.scope.pair}"
        )
    if not training:
        raise FoldConstructionError(f"outer fold {spec.outer_fold!r} leaves no training matches")
    return tuple(training), tuple(held_out)
