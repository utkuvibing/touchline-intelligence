"""Feature construction: vocabulary, scaling and encoding for the WP2.4 feature set.

Three contracts are pinned here, because each is the kind of thing that looks right and is wrong
when broken:

1. **Training-only preprocessing.** The continuous standardizer is fitted on **training rows only**
   per fold; validation rows must never shift its mean or standard deviation. Leaking validation
   rows into the scaler is a subtle form of target leakage even though the scaler itself is
   label-free, because the fitted scale would then encode information from rows it is later scored
   against. The final serving artifact refits on all development rows.
2. **Dev-wide, label-free vocabulary with a pre-registered rare merge (D8).** The vocabulary of
   categorical levels is fitted **once, on development rows, without the target**: any level with
   fewer than 25 development rows merges into a single ``rare`` level. The reference level is
   dropped from the design matrix so coefficients are interpreted relative to it and the matrix is
   not collinear with the intercept.
3. **Unseen-level policy (serving-time behavior).** Any level not in the fitted vocabulary encodes
   as the reference category (all-zero one-hot): it never raises and never drops the row. Because
   the vocabulary is dev-wide, no development row is unseen during development cross-validation;
   this policy exists for calibration, holdout and M3 serving. It is the written policy WP2.3
   required for ``shot_type_name = 'Corner'``, inherited here as a general behavior.

Presence indicators (``first_time``, ``under_pressure``) are 0/1 columns: 1 when the provider
annotated the field TRUE, 0 otherwise. Absence is *not* ``false`` — these are presence indicators,
never booleans (WP2.2 Slice B).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int_]

#: Continuous features, scaled by the per-fold training-row standardizer.
CONTINUOUS_FIELDS: tuple[str, ...] = ("distance_to_goal", "visible_goal_angle")

#: Presence indicators: raw source booleans (true-only annotations) encoded as 0/1.
PRESENCE_SOURCE_FIELDS: tuple[str, ...] = ("first_time", "under_pressure")

#: Candidate categorical fields (D8). ``shot_type_name`` is excluded by decision D2, so a future
#: ``Corner`` shot can never reach this vocabulary except as an unseen (reference) level.
CATEGORICAL_FIELDS: tuple[str, ...] = ("body_part_name", "technique_name", "play_pattern_name")

#: Locked interpretation reference levels (D8). The reference column is dropped from the matrix.
REFERENCE_LEVELS: Mapping[str, str] = {
    "body_part_name": "Right Foot",
    "technique_name": "Normal",
    "play_pattern_name": "Regular Play",
}

#: The synthetic bucket every dev-rare and future-unseen level is reported under.
RARE_LEVEL = "rare"

#: D8 pre-registered threshold: any categorical level with fewer development rows than this merges
#: into ``rare``. Fixed before any model output is viewed.
RARE_MIN_DEV_ROWS = 25


class DegenerateScalerError(ValueError):
    """A continuous feature with zero variance on the fitted rows.

    A zero standard deviation cannot be divided through meaningfully and would fabricate an
    arbitrary scale; the feature is a fixed-constant column and is a fact worth surfacing.
    """


@dataclass(frozen=True)
class ShotRow:
    """One cohort row with every raw field the pipeline consumes.

    Field names are part of the contract: the loader (**dataset.py**) produces exactly these and
    the encoders below read them by name, so a renamed column fails loudly instead of silently
    becoming an unseen level. ``competition_id``/``season_id`` are loaded so the D5 presence report
    can be stated per development tournament (WC 2018 / Euro 2020) as the contract requires.
    """

    shot_id: str
    match_id: int
    fold: int | None
    competition_id: int
    season_id: int
    y: int
    distance_to_goal: float
    visible_goal_angle: float
    body_part_name: str
    technique_name: str
    play_pattern_name: str
    first_time: bool | None
    under_pressure: bool | None
    # Retained for WP2.7 slice analysis; it is not part of the shipped feature vector.
    shot_type_name: str = "unknown"

    def presence(self, field: str) -> int:
        """Presence indicator: 1 when the provider annotated this TRUE, else 0. Never "false"."""
        return 1 if getattr(self, field) is True else 0


@dataclass(frozen=True)
class Vocabulary:
    """The dev-wide, label-free categorical vocabulary and its rare merge.

    ``levels[field]`` is the ordered list of design columns for that field — the retained levels
    minus the reference. The reference maps in ``reference`` and the merged members in
    ``rare_members`` are recorded so the artifact manifest can state exactly what was admitted.
    """

    levels: Mapping[str, tuple[str, ...]]
    reference: Mapping[str, str]
    rare_members: Mapping[str, tuple[str, ...]]

    @property
    def fields(self) -> tuple[str, ...]:
        return tuple(self.reference)

    def column_names(self) -> list[str]:
        """Deterministic full feature-column ordering: continuous, presence, then categorical."""
        names: list[str] = list(CONTINUOUS_FIELDS)
        names.extend(f"{field}_presence" for field in PRESENCE_SOURCE_FIELDS)
        for field in self.fields:
            for level in self.levels[field]:
                names.append(f"{field}::{level}")
        return names

    def as_dict(self) -> dict[str, object]:
        return {
            "levels": {field: list(levels) for field, levels in self.levels.items()},
            "reference": dict(self.reference),
            "rare_members": {field: list(members) for field, members in self.rare_members.items()},
        }


def fit_vocabulary(
    dev_counts: Mapping[tuple[str, str], int],
    threshold: int = RARE_MIN_DEV_ROWS,
) -> Vocabulary:
    """Build the label-free vocabulary from development-row level counts.

    ``dev_counts`` maps ``(field, level) -> development-row count`` for development rows only —
    it must never include calibration or holdout rows, whose levels would leak future annotation
    regimes into the vocabulary. Every level with fewer than ``threshold`` rows is merged into
    ``rare``. The reference level is always retained (it names the dropped column) regardless of
    count. Column order is deterministic (alphabetical, ``rare`` last).
    """
    levels: dict[str, tuple[str, ...]] = {}
    rare_members: dict[str, tuple[str, ...]] = {}
    for field in CATEGORICAL_FIELDS:
        reference = REFERENCE_LEVELS[field]
        field_counts = {level: count for (f, level), count in dev_counts.items() if f == field}
        retained = {level for level, count in field_counts.items() if count >= threshold}
        retained.add(reference)
        merged = sorted(
            level for level in field_counts if level not in retained and level != RARE_LEVEL
        )
        columns = sorted(retained - {reference})
        if merged:
            columns.append(RARE_LEVEL)
        levels[field] = tuple(columns)
        rare_members[field] = tuple(merged)
    return Vocabulary(
        levels=levels,
        reference=dict(REFERENCE_LEVELS),
        rare_members=rare_members,
    )


@dataclass(frozen=True)
class StandardScaler:
    """Per-feature mean and standard deviation (population SD, ddof=0) fitted on training rows."""

    mean: Mapping[str, float]
    std: Mapping[str, float]

    def as_dict(self) -> dict[str, object]:
        return {"mean": dict(self.mean), "std": dict(self.std)}


def fit_scaler(rows: Sequence[ShotRow]) -> StandardScaler:
    """Fit the continuous standardizer on ``rows`` — callers pass **training rows only**.

    The per-fold split is the caller's responsibility (the fold protocol in **train.py**); this
    function is deliberately a pure fit so a mistaken call that passes validation rows is a caller
    bug that the fold tests catch by construction.
    """
    mean: dict[str, float] = {}
    std: dict[str, float] = {}
    for field in CONTINUOUS_FIELDS:
        values = np.asarray([getattr(row, field) for row in rows], dtype=np.float64)
        scale = float(values.std())
        if not scale > 0.0:
            raise DegenerateScalerError(
                f"continuous feature {field!r} has zero standard deviation on the fitted rows"
            )
        mean[field] = float(values.mean())
        std[field] = scale
    return StandardScaler(mean=mean, std=std)


def _field_one_hot(vocabulary: Vocabulary, field: str, value: str) -> IntArray:
    """0/1 flags for ``field``'s columns given one raw categorical value.

    Three distinct cases, kept apart so a wrong one cannot pass silently:

    - a **retained dev level** sets its own column;
    - a **dev-rare level** (merged at vocabulary build, recorded in ``rare_members``) sets the
      ``rare`` column;
    - the **reference level and any truly unseen level** set no column at all — the all-zero
      one-hot that is the reference encoding (the unseen-level policy; serving-time behaviour).

    It never raises and never drops the row.
    """
    n_columns = len(vocabulary.levels[field])
    flags = np.zeros(n_columns, dtype=np.int_)
    existing = vocabulary.levels[field]
    if value == vocabulary.reference[field]:
        return flags
    if value in existing:
        flags[existing.index(value)] = 1
    elif value in vocabulary.rare_members[field]:
        flags[existing.index(RARE_LEVEL)] = 1
    return flags


def encode_rows(
    rows: Sequence[ShotRow],
    vocabulary: Vocabulary,
    scaler: StandardScaler,
) -> tuple[FloatArray, list[str]]:
    """Encode rows into the feature matrix ``(X, column_names)`` in deterministic order."""
    columns = vocabulary.column_names()
    n_columns = len(columns)
    matrix = np.empty((len(rows), n_columns), dtype=np.float64)
    for index, row in enumerate(rows):
        cursor = 0
        for field in CONTINUOUS_FIELDS:
            matrix[index, cursor] = (getattr(row, field) - scaler.mean[field]) / scaler.std[field]
            cursor += 1
        for field in PRESENCE_SOURCE_FIELDS:
            matrix[index, cursor] = float(row.presence(field))
            cursor += 1
        for field in vocabulary.fields:
            flags = _field_one_hot(vocabulary, field, getattr(row, field))
            matrix[index, cursor : cursor + flags.size] = flags
            cursor += flags.size
    return matrix, columns
