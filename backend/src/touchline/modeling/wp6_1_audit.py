"""Target-free coverage reporting for M6 WP6.1.

The audit depends only on ``wp6_1_context``.  It deliberately has no training-example or label
dependency: adding one is a boundary violation, not a convenient shortcut for a coverage count.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import psycopg

from touchline.config import MissingConfigurationError
from touchline.modeling.v2_folds import PROTOCOL_CONFIG_PATH, load_gate_config
from touchline.modeling.wp6_1_context import (
    CONTEXT_SCHEMA_VERSION,
    WP6_1_DEVELOPMENT_SCOPE_NAMES,
    ContextBoundaryError,
    V2ContextObservation,
    V2ShotContext,
    assert_context_boundary,
    contains_provider_xg_name,
    contexts_for_audit,
    load_v2_contexts,
)
from touchline.validation_tiers import is_local_postgres_url

FEATURE_DICTIONARY_PATH = Path("data/model/v2_feature_dictionary.json")
FEATURE_DICTIONARY_SCHEMA_VERSION = "1.0"
ALLOWED_SOURCE_STATUSES = frozenset({"confirmed", "requires_normalization", "unsupported"})
ADMISSION_DISCLAIMER = (
    "Statuses describe source-observation readiness only. They do not admit a feature or bundle "
    "into a model; bundle admission and evaluation are WP6.2+ work."
)
_COVERAGE_STATES = ("available", "absent", "invalid", "unsupported")


class FeatureDictionaryError(ValueError):
    """The versioned WP6.1 dictionary is malformed or crosses a forbidden boundary."""


@dataclass(frozen=True, slots=True)
class CoverageReport:
    """A deterministic target-free audit report.

    Counts are availability facts only.  The report intentionally offers no outcome, prediction,
    prevalence, rate, or model-metric field.
    """

    schema_version: str
    context_schema_version: str
    total_contexts: int
    contexts_by_tournament: Mapping[str, int]
    availability_by_field: Mapping[str, Mapping[str, int]]
    availability_by_feature_and_tournament: Mapping[str, Mapping[str, Mapping[str, int]]]
    freeze_frame: Mapping[str, int]
    freeze_frame_by_tournament: Mapping[str, Mapping[str, int]]
    invalid_structure_count: int
    missingness_signatures: Mapping[str, int]
    missingness_signatures_by_tournament: Mapping[str, Mapping[str, int]]
    source_observation_statuses: Mapping[str, int]
    attribution: str = "Data provided by StatsBomb."

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, indent=2) + "\n"


def load_feature_dictionary(path: Path = FEATURE_DICTIONARY_PATH) -> Mapping[str, Any]:
    """Load and validate the frozen dictionary without treating it as a feature admission list.

    The contract writer owns the exact human-facing layout, so this accepts either a top-level
    ``features`` list or a top-level ``entries`` list.  Every entry must still carry the mandatory
    source-observation facts and one of the three status values.  It never admits a bundle.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise FeatureDictionaryError("feature dictionary must be a JSON object")
    return _validate_dictionary(payload)


def _validate_dictionary(payload: dict[str, Any]) -> Mapping[str, Any]:
    _reject_provider_xg(payload, "feature dictionary")
    schema_version = payload.get("schema_version")
    if schema_version != FEATURE_DICTIONARY_SCHEMA_VERSION:
        raise FeatureDictionaryError(
            f"feature dictionary schema_version must be {FEATURE_DICTIONARY_SCHEMA_VERSION!r}"
        )
    statuses = payload.get("source_observation_statuses")
    if (
        not isinstance(statuses, list)
        or len(statuses) != len(ALLOWED_SOURCE_STATUSES)
        or set(statuses) != ALLOWED_SOURCE_STATUSES
    ):
        raise FeatureDictionaryError(
            "feature dictionary must declare exactly the three source-observation statuses"
        )
    entries = payload.get("features")
    if not isinstance(entries, list) or not entries:
        raise FeatureDictionaryError("feature dictionary needs a non-empty features list")
    if payload.get("admission_disclaimer") != ADMISSION_DISCLAIMER:
        raise FeatureDictionaryError("feature dictionary admission disclaimer changed")
    required = {
        "bundle",
        "source_fields",
        "availability_time",
        "football_meaning",
        "derivation",
        "units",
        "missingness",
        "leakage_risk",
        "serving_requirement",
    }
    seen: set[str] = set()
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise FeatureDictionaryError(f"dictionary entry {position} is not an object")
        missing = required - set(entry)
        if missing:
            raise FeatureDictionaryError(
                f"dictionary entry {position} lacks required keys {sorted(missing)}"
            )
        status = entry.get("source_observation_status", entry.get("status"))
        if status not in ALLOWED_SOURCE_STATUSES:
            raise FeatureDictionaryError(
                f"dictionary entry {position} has invalid source-observation status {status!r}"
            )
        name = str(entry.get("name", entry.get("source_fields")))
        if name in seen:
            raise FeatureDictionaryError(f"dictionary repeats entry {name!r}")
        seen.add(name)
        if entry.get("bundle") not in {"F0", "F1", "F2", "F3"}:
            raise FeatureDictionaryError(
                f"dictionary entry {position} has invalid bundle {entry.get('bundle')!r}"
            )
    return payload


def _reject_provider_xg(value: object, location: str) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if contains_provider_xg_name(str(key)):
                raise FeatureDictionaryError(f"provider xG is forbidden in {location} via {key!r}")
            _reject_provider_xg(child, location)
    elif isinstance(value, list):
        for child in value:
            _reject_provider_xg(child, location)
    elif isinstance(value, str) and contains_provider_xg_name(value):
        raise FeatureDictionaryError(f"provider xG is forbidden in {location}")


def build_coverage_report(
    observations: Iterable[V2ContextObservation], feature_dictionary: Mapping[str, Any]
) -> CoverageReport:
    """Count coverage from metadata and canonical contexts only.

    There is no overload accepting arbitrary rows: callers must cross the typed context boundary
    before audit, where provider xG and all outcome-bearing fields have already been excluded.
    """
    ordered = contexts_for_audit(observations)
    if not ordered:
        raise ValueError("WP6.1 coverage audit requires at least one context")
    assert_context_boundary(ordered)
    dictionary = _validated_dictionary_mapping(feature_dictionary)
    entries = dictionary.get("features", dictionary.get("entries"))
    assert isinstance(entries, list)  # checked above, retains the type narrow for mypy
    tournament_names = tuple(WP6_1_DEVELOPMENT_SCOPE_NAMES.values())
    by_tournament: Counter[str] = Counter({name: 0 for name in tournament_names})
    availability: dict[str, Counter[str]] = defaultdict(Counter)
    feature_tournament: dict[str, dict[str, Counter[str]]] = defaultdict(
        lambda: defaultdict(Counter)
    )
    signatures: Counter[str] = Counter()
    signatures_by_tournament: dict[str, Counter[str]] = defaultdict(Counter)
    freeze: Counter[str] = Counter()
    freeze_by_tournament: dict[str, Counter[str]] = defaultdict(Counter)
    statuses: Counter[str] = Counter()
    for entry in entries:
        assert isinstance(entry, Mapping)
        status = str(entry.get("source_observation_status", entry.get("status")))
        statuses[status] += 1
    for observation in ordered:
        metadata, context = observation.metadata, observation.context
        by_tournament[metadata.tournament] += 1
        field_values = {
            "location": context.location_x is not None and context.location_y is not None,
            "match_clock": context.match_clock_seconds is not None,
            "possession": context.possession_id is not None,
            "possession_duration": context.possession_duration_seconds is not None,
            "preceding_action": context.preceding_action is not None,
            "key_pass": context.key_pass_event_type is not None,
            "freeze_frame": bool(context.freeze_frame),
        }
        feature_values = _feature_availability(context)
        for entry in entries:
            assert isinstance(entry, Mapping)
            name = str(entry.get("name", entry.get("source_fields")))
            status = str(entry.get("source_observation_status", entry.get("status")))
            state = (
                "unsupported"
                if status == "unsupported"
                else "available"
                if feature_values.get(name, False)
                else "absent"
            )
            feature_tournament[name][metadata.tournament][state] += 1
        missing = []
        for field, available in field_values.items():
            availability[field]["available" if available else "missing"] += 1
            if not available:
                missing.append(field)
        signature = ",".join(missing) if missing else "complete"
        signatures[signature] += 1
        signatures_by_tournament[metadata.tournament][signature] += 1
        frame_presence = (
            "shots_with_freeze_frame" if context.freeze_frame else "shots_without_freeze_frame"
        )
        freeze[frame_presence] += 1
        freeze_by_tournament[metadata.tournament][frame_presence] += 1
        freeze["freeze_frame_actors"] += len(context.freeze_frame)
        freeze_by_tournament[metadata.tournament]["freeze_frame_actors"] += len(
            context.freeze_frame
        )
        usable_frame = (
            bool(context.freeze_frame)
            and all(
                actor.location_x is not None and actor.location_y is not None
                for actor in context.freeze_frame
            )
            and any(not actor.teammate for actor in context.freeze_frame)
        )
        usability = "usable_freeze_frames" if usable_frame else "unusable_freeze_frames"
        freeze[usability] += 1
        freeze_by_tournament[metadata.tournament][usability] += 1
        identified_goalkeeper = any(
            not actor.teammate
            and actor.position_name == "Goalkeeper"
            and actor.location_x is not None
            and actor.location_y is not None
            for actor in context.freeze_frame
        )
        goalkeeper_coverage = (
            "shots_with_identified_goalkeeper"
            if identified_goalkeeper
            else "shots_without_identified_goalkeeper"
        )
        freeze[goalkeeper_coverage] += 1
        freeze_by_tournament[metadata.tournament][goalkeeper_coverage] += 1
    return CoverageReport(
        schema_version=str(dictionary["schema_version"]),
        context_schema_version=CONTEXT_SCHEMA_VERSION,
        total_contexts=len(ordered),
        contexts_by_tournament=dict(sorted(by_tournament.items())),
        availability_by_field={
            key: dict(sorted(value.items())) for key, value in sorted(availability.items())
        },
        availability_by_feature_and_tournament=_complete_feature_coverage(
            entries, feature_tournament, tournament_names
        ),
        freeze_frame=dict(sorted(freeze.items())),
        freeze_frame_by_tournament={
            tournament: dict(sorted(counts.items()))
            for tournament, counts in sorted(freeze_by_tournament.items())
        },
        invalid_structure_count=0,
        missingness_signatures=dict(sorted(signatures.items())),
        missingness_signatures_by_tournament={
            tournament: dict(sorted(counts.items()))
            for tournament, counts in sorted(signatures_by_tournament.items())
        },
        source_observation_statuses=dict(sorted(statuses.items())),
    )


def _complete_feature_coverage(
    entries: list[Any],
    measured: Mapping[str, Mapping[str, Counter[str]]],
    tournaments: Sequence[str],
) -> Mapping[str, Mapping[str, Mapping[str, int]]]:
    """Emit every documented state, including explicit zeroes, in stable order."""
    completed: dict[str, dict[str, dict[str, int]]] = {}
    for entry in entries:
        assert isinstance(entry, Mapping)
        feature = str(entry.get("name", entry.get("source_fields")))
        completed[feature] = {}
        for tournament in tournaments:
            counts = measured.get(feature, {}).get(tournament, Counter())
            completed[feature][tournament] = {state: counts[state] for state in _COVERAGE_STATES}
    return dict(sorted(completed.items()))


def _validated_dictionary_mapping(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    encoded = json.dumps(dict(payload))
    try:
        parsed = json.loads(encoded)
    except TypeError as exc:
        raise FeatureDictionaryError("feature dictionary must be JSON-serializable") from exc
    if not isinstance(parsed, dict):
        raise FeatureDictionaryError("feature dictionary must be a JSON object")
    return _validate_dictionary(parsed)


def _feature_availability(context: V2ShotContext) -> Mapping[str, bool]:
    preceding = context.preceding_action
    opponents_with_locations = any(
        not actor.teammate and actor.location_x is not None and actor.location_y is not None
        for actor in context.freeze_frame
    )
    goalkeeper_with_location = any(
        not actor.teammate
        and actor.position_name == "Goalkeeper"
        and actor.location_x is not None
        and actor.location_y is not None
        for actor in context.freeze_frame
    )
    return {
        "distance_to_goal": True,
        "visible_goal_angle": True,
        "body_part": bool(context.body_part_name),
        "technique": bool(context.technique_name),
        "play_pattern": context.play_pattern_name is not None,
        "first_time": context.first_time is not None,
        "under_pressure": context.under_pressure is not None,
        "distance_spline_basis": True,
        "angle_spline_basis": True,
        "distance_angle_interaction": True,
        "shot_type": bool(context.shot_type_name),
        "pre_shot_score_differential": True,
        "match_clock": context.match_clock_seconds is not None,
        "possession_duration": context.possession_duration_seconds is not None,
        "possession_action_count": context.possession_action_count_before is not None,
        "preceding_event_type": preceding is not None,
        "preceding_event_displacement": preceding is not None
        and preceding.displacement is not None,
        "preceding_event_end_zone": False,
        "pass_carry_dribble_context": preceding is not None and preceding.is_supported_action,
        "set_piece_context": context.play_pattern_name is not None and bool(context.shot_type_name),
        "key_pass_attributes": context.key_pass_event_type is not None,
        "goalkeeper_displacement": goalkeeper_with_location,
        "goalkeeper_distance_to_shot_goal_line": goalkeeper_with_location,
        "nearest_defender_distance": opponents_with_locations,
        "opponents_within_fixed_radii": opponents_with_locations,
        "defenders_inside_visible_goal_cone": opponents_with_locations,
        "local_obstruction_density": opponents_with_locations,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="touchline.modeling.wp6_1_audit")
    parser.add_argument("--dictionary", type=Path, default=FEATURE_DICTIONARY_PATH)
    parser.add_argument("--protocol", type=Path, default=PROTOCOL_CONFIG_PATH)
    parser.add_argument("--json-out", type=Path, default=Path("reports/wp6.1-coverage.json"))
    args = parser.parse_args(argv)
    try:
        dictionary = load_feature_dictionary(args.dictionary)
        protocol = load_gate_config(args.protocol)
        db_url = os.environ.get("TOUCHLINE_FULL_COHORT_DB_URL")
        if not db_url:
            raise MissingConfigurationError("TOUCHLINE_FULL_COHORT_DB_URL is required for WP6.1")
        if not is_local_postgres_url(db_url):
            raise ValueError("TOUCHLINE_FULL_COHORT_DB_URL must be a loopback PostgreSQL URL")
        with psycopg.connect(db_url) as conn:
            conn.read_only = True
            report = build_coverage_report(load_v2_contexts(conn, protocol), dictionary)
    except (
        ContextBoundaryError,
        FeatureDictionaryError,
        MissingConfigurationError,
        OSError,
        psycopg.Error,
        ValueError,
    ) as exc:
        print(f"WP6.1 audit could not run: {exc}", file=sys.stderr)
        return 1
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    with args.json_out.open("w", encoding="utf-8", newline="\n") as output:
        output.write(report.to_json())
    print(report.to_json(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
