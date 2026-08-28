"""Fold-local, target-free F0/F1 feature transformer for WP6.2."""

from __future__ import annotations

import hashlib
import json
import pickle
import pickletools
import platform
import string
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal, cast

import numpy as np
import numpy.typing as npt
import scipy  # type: ignore[import-untyped]
import sklearn  # type: ignore[import-untyped]
from sklearn.preprocessing import SplineTransformer  # type: ignore[import-untyped]

from touchline.features.geometry import distance_to_goal, visible_goal_angle
from touchline.modeling.preprocessing import (
    CATEGORICAL_FIELDS,
    RARE_LEVEL,
    RARE_MIN_DEV_ROWS,
    REFERENCE_LEVELS,
)
from touchline.modeling.v2_folds import PROTOCOL_CONFIG_PATH
from touchline.modeling.wp6_1_context import (
    WP6_1_DEVELOPMENT_SCOPE_NAMES,
    V2ContextObservation,
    V2ShotContext,
    V2ShotMetadata,
    assert_context_boundary,
)

ROOT = Path(__file__).resolve().parents[4]
PIPELINE_CONFIG_PATH = ROOT / "data/model/v2_wp6_2_pipeline.json"
DICTIONARY_PATH = ROOT / "data/model/v2_feature_dictionary.json"
COHORT_SQL_PATH = ROOT / "backend/sql/wp2_1/01_model_shot_cohort.sql"
COHORT_SQL_SHA256 = "301d8a620b60d8da6011c7c4d12ef8108c658df4d923f612c3e3bf9e0427978e"
SCHEMA_VERSION = "1.0"
TRANSFORMER_SCHEMA = "FittedV2Transformer"
PICKLE_PROTOCOL = 5
MISSING_PLAY_PATTERN = "__MISSING_PLAY_PATTERN__"
FloatArray = npt.NDArray[np.float64]


class V2FeatureError(ValueError):
    """The supplied observations cannot be represented by the frozen transformer."""


class DegenerateNumericStateError(V2FeatureError):
    """A learned numeric scaling state has no usable variation."""


class DegenerateKnotError(V2FeatureError):
    """Explicit quantile knots are duplicate or too close to distinguish safely."""


class ArtifactCompatibilityError(V2FeatureError):
    """A local transformer artifact does not satisfy its recorded compatibility contract."""


@dataclass(frozen=True, slots=True)
class V2FeatureMatrix:
    values: FloatArray
    columns: tuple[str, ...]
    shot_ids: tuple[str, ...]


_QUANTILES = (0.0, 0.25, 0.5, 0.75, 1.0)
_KNOT_TOLERANCE_MULTIPLIER = 64.0
_NUMERIC_TOLERANCE_MULTIPLIER = 64.0
_F1_BASIS_COLUMNS = 6


def _expected_pipeline_config() -> dict[str, object]:
    """Return the exact, outcome-free WP6.2 configuration contract."""
    return {
        "schema_version": SCHEMA_VERSION,
        "missing_play_pattern": MISSING_PLAY_PATTERN,
        "numeric_tolerance_multiplier": 64,
        "v1_form": {
            "categorical_fields": list(CATEGORICAL_FIELDS),
            "reference_levels": dict(REFERENCE_LEVELS),
            "rare_min_rows": RARE_MIN_DEV_ROWS,
            "presence_fields": ["first_time", "under_pressure"],
        },
        "bundles": {
            "F0": {"scaling": "population_ddof_0"},
            "F1": {
                "quantiles": list(_QUANTILES),
                "degree": 3,
                "extrapolation": "linear",
                "include_bias": False,
                "order": "C",
                "handle_missing": "error",
                "sparse_output": False,
                "basis_columns_per_feature": _F1_BASIS_COLUMNS,
                "interaction": "standardized_raw_distance_times_standardized_raw_angle",
            },
        },
    }


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact_sha(path: Path, name: str) -> str:
    try:
        return _sha(path)
    except OSError as exc:
        raise ArtifactCompatibilityError(f"artifact dependency {name} cannot be read") from exc


def _verified_cohort_sha() -> str:
    digest = _artifact_sha(COHORT_SQL_PATH, "cohort query")
    if digest != COHORT_SQL_SHA256:
        raise ArtifactCompatibilityError("WP2.1 cohort query byte verification failed")
    return digest


def _tolerance(values: FloatArray) -> float:
    maximum = float(np.max(np.abs(values)))
    return _NUMERIC_TOLERANCE_MULTIPLIER * np.finfo(np.float64).eps * max(1.0, maximum)


def _numeric_state(values: FloatArray, name: str) -> tuple[float, float]:
    if values.size == 0 or not np.all(np.isfinite(values)):
        raise DegenerateNumericStateError(f"{name} fitted values must be finite and non-empty")
    mean, std = float(values.mean()), float(values.std(ddof=0))
    if not np.isfinite(std) or std <= _tolerance(values):
        raise DegenerateNumericStateError(f"{name} has degenerate fitted numeric state")
    return mean, std


def _pipeline_config() -> dict[str, object]:
    """Load and validate the separately versioned WP6.2 configuration."""
    try:
        payload = json.loads(PIPELINE_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise V2FeatureError("WP6.2 pipeline configuration cannot be read") from exc
    if payload != _expected_pipeline_config():
        raise V2FeatureError("WP6.2 pipeline configuration differs from the frozen contract")
    return cast(dict[str, object], payload)


def _play(value: str | None) -> str:
    return MISSING_PLAY_PATTERN if value is None else value


def _field_value(observation: V2ContextObservation, field: str) -> str:
    value = getattr(observation.context, field)
    return _play(value) if field == "play_pattern_name" else str(value)


def _validate_observations(observations: Sequence[V2ContextObservation]) -> None:
    if len(observations) == 0:
        raise V2FeatureError("cannot fit or transform an empty observation sequence")
    ids: set[str] = set()
    for observation in observations:
        if not isinstance(observation, V2ContextObservation):
            raise TypeError("WP6.2 requires V2ContextObservation values")
        if not isinstance(observation.context, V2ShotContext):
            raise TypeError("WP6.2 observation context must be V2ShotContext")
        assert_context_boundary(observation.context)
        context = observation.context
        if (
            not isinstance(context.body_part_name, str)
            or not context.body_part_name
            or not isinstance(context.technique_name, str)
            or not context.technique_name
            or not isinstance(context.shot_type_name, str)
            or not context.shot_type_name
            or (
                context.play_pattern_name is not None
                and not isinstance(context.play_pattern_name, str)
            )
            or (context.under_pressure is not None and not isinstance(context.under_pressure, bool))
            or (context.first_time is not None and not isinstance(context.first_time, bool))
        ):
            raise V2FeatureError("observation context categories or indicators are malformed")
        metadata = observation.metadata
        if not isinstance(metadata, V2ShotMetadata):
            raise TypeError("WP6.2 observation metadata must be V2ShotMetadata")
        if (
            not isinstance(metadata.shot_id, str)
            or not metadata.shot_id
            or isinstance(metadata.match_id, bool)
            or not isinstance(metadata.match_id, int)
            or isinstance(metadata.competition_id, bool)
            or not isinstance(metadata.competition_id, int)
            or isinstance(metadata.season_id, bool)
            or not isinstance(metadata.season_id, int)
            or not isinstance(metadata.tournament, str)
            or not metadata.tournament
            or not isinstance(metadata.match_date, date)
            or isinstance(metadata.event_index, bool)
            or not isinstance(metadata.event_index, int)
        ):
            raise V2FeatureError("observation metadata is malformed")
        scope = (metadata.competition_id, metadata.season_id)
        if scope not in WP6_1_DEVELOPMENT_SCOPE_NAMES:
            raise V2FeatureError("WP6.2 accepts development scopes only")
        if metadata.tournament != WP6_1_DEVELOPMENT_SCOPE_NAMES[scope]:
            raise V2FeatureError("observation tournament does not match its development scope")
        if observation.metadata.shot_id in ids:
            raise V2FeatureError(f"duplicate shot {observation.metadata.shot_id}")
        ids.add(observation.metadata.shot_id)
        numeric = np.asarray(
            [observation.context.distance_to_goal, observation.context.visible_goal_angle],
            dtype=np.float64,
        )
        if not np.all(np.isfinite(numeric)):
            raise V2FeatureError("distance_to_goal and visible_goal_angle must be finite")


def _vocabulary(
    observations: Sequence[V2ContextObservation],
) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    levels: dict[str, tuple[str, ...]] = {}
    rare: dict[str, tuple[str, ...]] = {}
    for field in CATEGORICAL_FIELDS:
        counts = Counter(_field_value(item, field) for item in observations)
        reference = REFERENCE_LEVELS[field]
        retained = {name for name, count in counts.items() if count >= RARE_MIN_DEV_ROWS}
        retained.add(reference)
        merged = tuple(
            sorted(name for name in counts if name not in retained and name != RARE_LEVEL)
        )
        columns = sorted(retained - {reference})
        if merged:
            columns.append(RARE_LEVEL)
        levels[field] = tuple(columns)
        rare[field] = merged
    return levels, rare


def _spline(
    values: FloatArray, name: str
) -> tuple[SplineTransformer, FloatArray, tuple[float, ...]]:
    values = np.asarray(values, dtype=np.float64)
    if values.size == 0 or not np.all(np.isfinite(values)):
        raise DegenerateKnotError(f"{name} cannot fit knots from empty or non-finite values")
    knots = np.quantile(values, _QUANTILES, method="linear").astype(np.float64)
    threshold = (
        _KNOT_TOLERANCE_MULTIPLIER
        * np.finfo(np.float64).eps
        * max(1.0, float(np.max(np.abs(knots))))
    )
    if not np.all(np.isfinite(knots)) or np.any(np.diff(knots) <= threshold):
        raise DegenerateKnotError(f"{name} has duplicate or degenerate quantile knots")
    transformer = SplineTransformer(
        degree=3,
        knots=knots.reshape(-1, 1),
        extrapolation="linear",
        include_bias=False,
        order="C",
        handle_missing="error",
        sparse_output=False,
    ).fit(values.reshape(-1, 1))
    basis = np.asarray(transformer.transform(values.reshape(-1, 1)), dtype=np.float64)
    if basis.shape[1] != 6:
        raise V2FeatureError(f"{name} spline must produce six columns")
    return transformer, basis, tuple(float(item) for item in knots)


@dataclass(slots=True)
class FittedV2Transformer:
    bundle: Literal["F0", "F1"]
    numeric_mean: dict[str, float]
    numeric_std: dict[str, float]
    levels: dict[str, tuple[str, ...]]
    rare_members: dict[str, tuple[str, ...]]
    columns: tuple[str, ...]
    distance_spline: SplineTransformer | None = None
    angle_spline: SplineTransformer | None = None
    spline_mean: dict[str, FloatArray] | None = None
    spline_std: dict[str, FloatArray] | None = None
    knots: dict[str, tuple[float, ...]] | None = None
    fit_identity_digest: str = ""
    fit_counts: dict[str, int] | None = None
    numeric_max_abs: dict[str, float] | None = None
    spline_max_abs: dict[str, FloatArray] | None = None

    def transform(self, observations: Sequence[V2ContextObservation]) -> V2FeatureMatrix:
        _validate_fitted_transformer(self)
        _validate_observations(observations)
        raw = {
            name: np.asarray([getattr(x.context, name) for x in observations], dtype=np.float64)
            for name in ("distance_to_goal", "visible_goal_angle")
        }
        pieces: list[FloatArray] = [
            ((raw[name] - self.numeric_mean[name]) / self.numeric_std[name]).reshape(-1, 1)
            for name in ("distance_to_goal", "visible_goal_angle")
        ]
        pieces.append(
            np.asarray(
                [
                    [float(x.context.first_time is True), float(x.context.under_pressure is True)]
                    for x in observations
                ],
                dtype=np.float64,
            )
        )
        for field in CATEGORICAL_FIELDS:
            result = np.zeros((len(observations), len(self.levels[field])), dtype=np.float64)
            for index, observation in enumerate(observations):
                value = _field_value(observation, field)
                if value in self.levels[field]:
                    result[index, self.levels[field].index(value)] = 1.0
                elif value in self.rare_members[field] and RARE_LEVEL in self.levels[field]:
                    result[index, self.levels[field].index(RARE_LEVEL)] = 1.0
            pieces.append(result)
        if self.bundle == "F1":
            if (
                self.distance_spline is None
                or self.angle_spline is None
                or self.spline_mean is None
                or self.spline_std is None
            ):
                raise V2FeatureError("F1 transformer is missing its fitted spline state")
            for name, spline in (("distance", self.distance_spline), ("angle", self.angle_spline)):
                values = raw[f"{name}_to_goal"] if name == "distance" else raw["visible_goal_angle"]
                basis = np.asarray(spline.transform(values.reshape(-1, 1)), dtype=np.float64)
                pieces.append((basis - self.spline_mean[name]) / self.spline_std[name])
            pieces.append(pieces[0] * pieces[1])
        matrix = np.ascontiguousarray(np.hstack(pieces), dtype=np.float64)
        if matrix.shape[1] != len(self.columns) or not np.all(np.isfinite(matrix)):
            raise V2FeatureError("transformed matrix violates the frozen finite column contract")
        return V2FeatureMatrix(
            matrix, self.columns, tuple(x.metadata.shot_id for x in observations)
        )


def _validate_fitted_transformer(transformer: FittedV2Transformer) -> None:
    """Validate the state needed by the single offline/serving transformation path."""
    if transformer.bundle not in {"F0", "F1"}:
        raise V2FeatureError("transformer bundle must be exactly F0 or F1")
    if set(transformer.numeric_mean) != {"distance_to_goal", "visible_goal_angle"} or set(
        transformer.numeric_std
    ) != {"distance_to_goal", "visible_goal_angle"}:
        raise V2FeatureError("transformer raw numeric state is incomplete")
    if transformer.numeric_max_abs is None or set(transformer.numeric_max_abs) != {
        "distance_to_goal",
        "visible_goal_angle",
    }:
        raise V2FeatureError("transformer raw numeric maxima are incomplete")
    for name in ("distance_to_goal", "visible_goal_angle"):
        mean, std = transformer.numeric_mean[name], transformer.numeric_std[name]
        maximum = transformer.numeric_max_abs[name]
        tolerance = _NUMERIC_TOLERANCE_MULTIPLIER * np.finfo(np.float64).eps * max(1.0, maximum)
        if (
            not np.isfinite(mean)
            or not np.isfinite(std)
            or not np.isfinite(maximum)
            or maximum < 0.0
            or std <= tolerance
        ):
            raise V2FeatureError(f"{name} transformer numeric state is invalid")
    expected_fields = set(CATEGORICAL_FIELDS)
    if (
        set(transformer.levels) != expected_fields
        or set(transformer.rare_members) != expected_fields
    ):
        raise V2FeatureError("transformer categorical state is incomplete")
    if transformer.columns != _columns(transformer.levels, transformer.bundle):
        raise V2FeatureError("transformer column contract is invalid")
    if (
        not isinstance(transformer.fit_identity_digest, str)
        or len(transformer.fit_identity_digest) != 64
        or any(character not in string.hexdigits for character in transformer.fit_identity_digest)
    ):
        raise V2FeatureError("transformer fit-identity digest is invalid")
    if transformer.fit_counts is None or set(transformer.fit_counts) != {
        "rows",
        "matches",
        "scopes",
    }:
        raise V2FeatureError("transformer fit counts are incomplete")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value <= 0
        for value in transformer.fit_counts.values()
    ):
        raise V2FeatureError("transformer fit counts are invalid")
    if transformer.bundle == "F0":
        if any(
            value is not None
            for value in (
                transformer.distance_spline,
                transformer.angle_spline,
                transformer.spline_mean,
                transformer.spline_std,
                transformer.knots,
                transformer.spline_max_abs,
            )
        ):
            raise V2FeatureError("F0 transformer contains unexpected spline state")
        return
    if (
        transformer.distance_spline is None
        or transformer.angle_spline is None
        or transformer.spline_mean is None
        or transformer.spline_std is None
        or transformer.knots is None
        or transformer.spline_max_abs is None
    ):
        raise V2FeatureError("F1 transformer is missing its fitted spline state")
    if set(transformer.knots) != {"distance", "angle"}:
        raise V2FeatureError("F1 transformer knot state is incomplete")
    if set(transformer.spline_mean) != {"distance", "angle"} or set(transformer.spline_std) != {
        "distance",
        "angle",
    }:
        raise V2FeatureError("F1 transformer spline scaling state is incomplete")
    if set(transformer.spline_max_abs) != {"distance", "angle"}:
        raise V2FeatureError("F1 transformer spline maxima are incomplete")
    expected_knots = {
        "distance": transformer.knots["distance"],
        "angle": transformer.knots["angle"],
    }
    for name, spline in (
        ("distance", transformer.distance_spline),
        ("angle", transformer.angle_spline),
    ):
        knots = np.asarray(expected_knots[name], dtype=np.float64)
        if knots.shape != (5,) or not np.all(np.isfinite(knots)):
            raise V2FeatureError(f"{name} transformer knot state is invalid")
        gap = np.diff(knots)
        threshold = (
            _KNOT_TOLERANCE_MULTIPLIER
            * np.finfo(np.float64).eps
            * max(1.0, float(np.max(np.abs(knots))))
        )
        if np.any(gap <= threshold):
            raise DegenerateKnotError(f"{name} has duplicate or degenerate quantile knots")
        params = spline.get_params(deep=False)
        if (
            params.get("degree") != 3
            or params.get("n_knots") != 5
            or params.get("extrapolation") != "linear"
            or params.get("include_bias") is not False
            or params.get("order") != "C"
            or params.get("handle_missing") != "error"
            or params.get("sparse_output") is not False
        ):
            raise V2FeatureError(f"{name} spline parameters differ from the frozen contract")
        configured_knots = np.asarray(params.get("knots"), dtype=np.float64)
        if configured_knots.shape != (5, 1) or not np.array_equal(configured_knots[:, 0], knots):
            raise V2FeatureError(f"{name} spline knots differ from the manifest state")
        spline_mean_values = np.asarray(transformer.spline_mean[name], dtype=np.float64)
        spline_std_values = np.asarray(transformer.spline_std[name], dtype=np.float64)
        spline_max_values = np.asarray(transformer.spline_max_abs[name], dtype=np.float64)
        if (
            spline_mean_values.shape != (_F1_BASIS_COLUMNS,)
            or spline_std_values.shape != (_F1_BASIS_COLUMNS,)
            or spline_max_values.shape != (_F1_BASIS_COLUMNS,)
            or not np.all(np.isfinite(spline_mean_values))
            or not np.all(np.isfinite(spline_std_values))
            or not np.all(np.isfinite(spline_max_values))
            or np.any(spline_max_values < 0.0)
            or np.any(spline_std_values <= 0.0)
            or np.any(
                spline_std_values
                <= _NUMERIC_TOLERANCE_MULTIPLIER
                * np.finfo(np.float64).eps
                * np.maximum(1.0, spline_max_values)
            )
        ):
            raise DegenerateNumericStateError(f"{name} spline basis scaling state is invalid")


def _columns(levels: Mapping[str, tuple[str, ...]], bundle: str) -> tuple[str, ...]:
    names = [
        "distance_to_goal",
        "visible_goal_angle",
        "first_time_presence",
        "under_pressure_presence",
    ]
    for field in CATEGORICAL_FIELDS:
        names.extend(f"{field}::{level}" for level in levels[field])
    if bundle == "F1":
        names.extend(f"distance_spline_{index}" for index in range(6))
        names.extend(f"angle_spline_{index}" for index in range(6))
        names.append("distance_angle_z_product")
    return tuple(names)


def _identity(observations: Sequence[V2ContextObservation]) -> str:
    # Deliberately metadata-only: no targets, values, predictions, or model state.
    rows = [
        {
            "shot_id": x.metadata.shot_id,
            "match_id": x.metadata.match_id,
            "competition_id": x.metadata.competition_id,
            "season_id": x.metadata.season_id,
            "match_date": x.metadata.match_date.isoformat(),
            "event_index": x.metadata.event_index,
        }
        for x in sorted(observations, key=lambda item: item.metadata.shot_id)
    ]
    return hashlib.sha256(_canonical(rows)).hexdigest()


def fit_v2_transformer(
    observations: Sequence[V2ContextObservation], bundle: str
) -> FittedV2Transformer:
    if bundle not in {"F0", "F1"}:
        raise V2FeatureError("bundle must be exactly F0 or F1")
    _pipeline_config()
    _validate_observations(observations)
    levels, rare = _vocabulary(observations)
    raw = {
        name: np.asarray([getattr(x.context, name) for x in observations], dtype=np.float64)
        for name in ("distance_to_goal", "visible_goal_angle")
    }
    means, stds = {}, {}
    for name, values in raw.items():
        means[name], stds[name] = _numeric_state(values, name)
    result = FittedV2Transformer(
        cast(Literal["F0", "F1"], bundle),
        means,
        stds,
        levels,
        rare,
        _columns(levels, bundle),
        fit_identity_digest=_identity(observations),
        fit_counts={
            "rows": len(observations),
            "matches": len({x.metadata.match_id for x in observations}),
            "scopes": len(
                {(x.metadata.competition_id, x.metadata.season_id) for x in observations}
            ),
        },
        numeric_max_abs={name: float(np.max(np.abs(values))) for name, values in raw.items()},
    )
    if bundle == "F1":
        ds, db, dk = _spline(raw["distance_to_goal"], "distance")
        ars, ab, ak = _spline(raw["visible_goal_angle"], "angle")
        result.distance_spline, result.angle_spline = ds, ars
        result.knots = {"distance": dk, "angle": ak}
        result.spline_mean, result.spline_std = {}, {}
        result.spline_max_abs = {}
        for name, basis in (("distance", db), ("angle", ab)):
            mean = basis.mean(axis=0)
            std = basis.std(axis=0, ddof=0)
            for index in range(basis.shape[1]):
                _numeric_state(basis[:, index], f"{name}_spline_{index}")
            result.spline_mean[name], result.spline_std[name] = mean, std
            result.spline_max_abs[name] = np.max(np.abs(basis), axis=0).astype(np.float64)
    # execute the same public transform path used after load.
    result.transform(observations)
    return result


def _versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "sklearn": sklearn.__version__,
    }


def compatibility_probe_observations() -> tuple[V2ContextObservation, ...]:
    """Return the fixed, label-free inputs used to prove artifact compatibility."""
    specifications = (
        ("wp6.2-probe-0", 80.0, 20.0, "Right Foot", "Normal", "Regular Play", True, False),
        ("wp6.2-probe-1", 96.0, 40.0, "Left Foot", "Volley", "From Corner", False, None),
        ("wp6.2-probe-2", 112.0, 60.0, "Head", "Backheel", None, None, True),
    )
    observations: list[V2ContextObservation] = []
    for index, (shot_id, x, y, body, technique, play, first, pressure) in enumerate(specifications):
        context = V2ShotContext(
            schema_version="1.0",
            location_x=x,
            location_y=y,
            distance_to_goal=distance_to_goal(x, y),
            visible_goal_angle=visible_goal_angle(x, y),
            body_part_name=body,
            technique_name=technique,
            shot_type_name="Open Play",
            play_pattern_name=play,
            under_pressure=pressure,
            first_time=first,
            period=1,
            minute=index + 1,
            second=0,
            match_clock_seconds=(index + 1) * 60,
            team_score_before=0,
            opponent_score_before=0,
            possession_id=None,
            possession_duration_seconds=None,
            possession_action_count_before=None,
            preceding_action=None,
            key_pass_event_type=None,
            key_pass_length=None,
            freeze_frame=(),
        )
        observations.append(
            V2ContextObservation(
                metadata=V2ShotMetadata(
                    shot_id=shot_id,
                    match_id=9000 + index,
                    competition_id=43,
                    season_id=3,
                    tournament="WC2018",
                    match_date=date(2018, 1, 1),
                    event_index=index,
                ),
                context=context,
            )
        )
    return tuple(observations)


def _probe_payload(observations: Sequence[V2ContextObservation]) -> list[dict[str, object]]:
    """Serialize only label-free feature inputs for the compatibility probe."""
    return [
        {
            "shot_id": item.metadata.shot_id,
            "location_x": float(item.context.location_x),
            "location_y": float(item.context.location_y),
            "distance_to_goal": float(item.context.distance_to_goal),
            "visible_goal_angle": float(item.context.visible_goal_angle),
            "body_part_name": item.context.body_part_name,
            "technique_name": item.context.technique_name,
            "play_pattern_name": item.context.play_pattern_name,
            "first_time": item.context.first_time,
            "under_pressure": item.context.under_pressure,
        }
        for item in observations
    ]


def _probe_sequence() -> tuple[V2ContextObservation, ...]:
    """Return the non-overridable, label-free compatibility probe."""
    probe = compatibility_probe_observations()
    _validate_observations(probe)
    return probe


def save_v2_transformer(
    transformer: FittedV2Transformer,
    pickle_path: Path,
    manifest_path: Path,
) -> None:
    try:
        config = _pipeline_config()
    except V2FeatureError as exc:
        raise ArtifactCompatibilityError(str(exc)) from exc
    _validate_fitted_transformer(transformer)
    probe_inputs = _probe_sequence()
    probe = transformer.transform(probe_inputs)
    pickle_path.parent.mkdir(parents=True, exist_ok=True)
    with pickle_path.open("wb") as handle:
        pickle.dump(transformer, handle, protocol=PICKLE_PROTOCOL)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "transformer_schema": TRANSFORMER_SCHEMA,
        "pickle_protocol": PICKLE_PROTOCOL,
        "bundle": transformer.bundle,
        "columns": list(transformer.columns),
        "numeric_mean": transformer.numeric_mean,
        "numeric_std": transformer.numeric_std,
        "numeric_max_abs": transformer.numeric_max_abs,
        "levels": {k: list(v) for k, v in transformer.levels.items()},
        "rare_members": {k: list(v) for k, v in transformer.rare_members.items()},
        "pipeline_config": config,
        "knots": transformer.knots,
        "spline_mean": (
            {key: value.tolist() for key, value in transformer.spline_mean.items()}
            if transformer.spline_mean is not None
            else None
        ),
        "spline_std": (
            {key: value.tolist() for key, value in transformer.spline_std.items()}
            if transformer.spline_std is not None
            else None
        ),
        "spline_max_abs": (
            {key: value.tolist() for key, value in transformer.spline_max_abs.items()}
            if transformer.spline_max_abs is not None
            else None
        ),
        "pipeline_config_sha256": _sha(PIPELINE_CONFIG_PATH),
        "dictionary_sha256": _sha(DICTIONARY_PATH),
        "protocol_sha256": _sha(ROOT / PROTOCOL_CONFIG_PATH),
        "cohort_sql_sha256": _verified_cohort_sha(),
        "verified_cohort_query_sha256": COHORT_SQL_SHA256,
        "versions": _versions(),
        "pickle_sha256": _sha(pickle_path),
        "fit_counts": transformer.fit_counts,
        "fit_identity_digest": transformer.fit_identity_digest,
        "probe_inputs": _probe_payload(probe_inputs),
        "probe_columns": list(probe.columns),
        "probe_shot_ids": list(probe.shot_ids),
        "probe_values": probe.values.tolist(),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(_canonical(manifest) + b"\n")


def _compatible(recorded: str, current: str, positions: int) -> bool:
    def parts(value: str) -> tuple[int, ...]:
        pieces = value.split(".")
        if len(pieces) < 3 or any(not piece.isdigit() for piece in pieces):
            raise ArtifactCompatibilityError(f"malformed dependency version {value!r}")
        return tuple(int(piece) for piece in pieces)

    return parts(recorded)[:positions] == parts(current)[:positions]


def _read_verified_pickle(path: Path, expected_sha256: object) -> bytes:
    """Read, hash, and inspect the pickle stream before any unpickling occurs."""
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ArtifactCompatibilityError("transformer pickle cannot be read") from exc
    if (
        not isinstance(expected_sha256, str)
        or hashlib.sha256(payload).hexdigest() != expected_sha256
    ):
        raise ArtifactCompatibilityError("transformer schema or pickle digest mismatch")
    try:
        opcode, argument, _ = next(pickletools.genops(payload))
    except (IndexError, StopIteration, TypeError, ValueError) as exc:
        raise ArtifactCompatibilityError("transformer pickle protocol cannot be inspected") from exc
    if opcode.name != "PROTO" or argument != PICKLE_PROTOCOL:
        raise ArtifactCompatibilityError("transformer pickle protocol mismatch")
    return payload


def load_v2_transformer(
    pickle_path: Path,
    manifest_path: Path,
) -> FittedV2Transformer:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ArtifactCompatibilityError("transformer manifest cannot be read") from exc
    if not isinstance(manifest, dict):
        raise ArtifactCompatibilityError("transformer manifest must be a JSON object")
    try:
        config = _pipeline_config()
    except V2FeatureError as exc:
        raise ArtifactCompatibilityError(str(exc)) from exc
    if (
        manifest.get("schema_version") != SCHEMA_VERSION
        or manifest.get("transformer_schema") != TRANSFORMER_SCHEMA
        or manifest.get("pickle_protocol") != PICKLE_PROTOCOL
    ):
        raise ArtifactCompatibilityError("transformer schema or pickle digest mismatch")
    for name, path in (
        ("pipeline_config_sha256", PIPELINE_CONFIG_PATH),
        ("dictionary_sha256", DICTIONARY_PATH),
        ("protocol_sha256", ROOT / PROTOCOL_CONFIG_PATH),
        ("cohort_sql_sha256", COHORT_SQL_PATH),
        ("verified_cohort_query_sha256", COHORT_SQL_PATH),
    ):
        if manifest.get(name) != _artifact_sha(path, name):
            raise ArtifactCompatibilityError(f"{name} mismatch")
    if manifest.get("cohort_sql_sha256") != COHORT_SQL_SHA256:
        raise ArtifactCompatibilityError("WP2.1 cohort query byte verification failed")
    if manifest.get("verified_cohort_query_sha256") != COHORT_SQL_SHA256:
        raise ArtifactCompatibilityError("verified cohort-query hash mismatch")
    if manifest.get("pipeline_config") != config:
        raise ArtifactCompatibilityError("pipeline configuration mismatch")
    versions = manifest.get("versions", {})
    if not isinstance(versions, dict):
        raise ArtifactCompatibilityError("artifact dependency versions are missing")
    current = _versions()
    for name, parts in (("python", 2), ("sklearn", 2), ("numpy", 1), ("scipy", 1)):
        recorded = versions.get(name)
        if not isinstance(recorded, str) or not _compatible(recorded, current[name], parts):
            raise ArtifactCompatibilityError(f"unsupported {name} artifact version")
    pickle_payload = _read_verified_pickle(pickle_path, manifest.get("pickle_sha256"))
    try:
        transformer = pickle.loads(pickle_payload)  # trusted local artifacts only
    except (OSError, pickle.PickleError, EOFError, ImportError, AttributeError, ValueError) as exc:
        raise ArtifactCompatibilityError("transformer pickle cannot be loaded") from exc
    if not isinstance(transformer, FittedV2Transformer):
        raise ArtifactCompatibilityError("pickle is not the declared WP6.2 transformer")
    try:
        _validate_fitted_transformer(transformer)
    except (V2FeatureError, TypeError, KeyError, AttributeError) as exc:
        raise ArtifactCompatibilityError(str(exc)) from exc
    if (
        manifest.get("bundle") != transformer.bundle
        or tuple(manifest.get("columns", ())) != transformer.columns
    ):
        raise ArtifactCompatibilityError("manifest bundle or column contract mismatch")
    if (
        manifest.get("numeric_mean") != transformer.numeric_mean
        or manifest.get("numeric_std") != transformer.numeric_std
        or manifest.get("numeric_max_abs") != transformer.numeric_max_abs
    ):
        raise ArtifactCompatibilityError("manifest raw numeric state mismatch")
    if manifest.get("levels") != {key: list(value) for key, value in transformer.levels.items()}:
        raise ArtifactCompatibilityError("manifest categorical vocabulary mismatch")
    if manifest.get("rare_members") != {
        key: list(value) for key, value in transformer.rare_members.items()
    }:
        raise ArtifactCompatibilityError("manifest rare-level state mismatch")
    try:
        knots = (
            {key: list(value) for key, value in transformer.knots.items()}
            if transformer.knots is not None
            else None
        )
        spline_mean = (
            {key: value.tolist() for key, value in transformer.spline_mean.items()}
            if transformer.spline_mean is not None
            else None
        )
        spline_std = (
            {key: value.tolist() for key, value in transformer.spline_std.items()}
            if transformer.spline_std is not None
            else None
        )
        spline_max_abs = (
            {key: value.tolist() for key, value in transformer.spline_max_abs.items()}
            if transformer.spline_max_abs is not None
            else None
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise ArtifactCompatibilityError("manifest spline state is malformed") from exc
    if manifest.get("knots") != knots:
        raise ArtifactCompatibilityError("manifest spline-knot state mismatch")
    if manifest.get("spline_mean") != spline_mean or manifest.get("spline_std") != spline_std:
        raise ArtifactCompatibilityError("manifest spline scaling state mismatch")
    if manifest.get("spline_max_abs") != spline_max_abs:
        raise ArtifactCompatibilityError("manifest spline maximum state mismatch")
    if manifest.get("fit_identity_digest") != transformer.fit_identity_digest:
        raise ArtifactCompatibilityError("fit-identity digest mismatch")
    if manifest.get("fit_counts") != transformer.fit_counts:
        raise ArtifactCompatibilityError("fit-count state mismatch")
    try:
        probes = _probe_sequence()
        if manifest.get("probe_inputs") != _probe_payload(probes):
            raise ArtifactCompatibilityError("compatibility probe inputs mismatch")
        result = transformer.transform(probes)
    except ArtifactCompatibilityError:
        raise
    except (V2FeatureError, TypeError, KeyError, AttributeError, ValueError) as exc:
        raise ArtifactCompatibilityError("label-free compatibility probe failed") from exc
    expected_columns = tuple(manifest.get("probe_columns", ()))
    expected_ids = tuple(manifest.get("probe_shot_ids", ()))
    try:
        expected_values = np.asarray(manifest["probe_values"], dtype=np.float64)
    except (KeyError, TypeError, ValueError) as exc:
        raise ArtifactCompatibilityError("compatibility probe output is malformed") from exc
    if (
        expected_columns != result.columns
        or expected_ids != result.shot_ids
        or expected_values.shape != result.values.shape
        or not np.allclose(expected_values, result.values, rtol=0.0, atol=1e-12)
    ):
        raise ArtifactCompatibilityError("label-free compatibility probe failed")
    return transformer
