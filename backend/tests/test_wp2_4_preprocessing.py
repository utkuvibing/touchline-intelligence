"""Unit contracts for the WP2.4 feature pipeline. Synthetic rows, no database, no target leakage.

Pinned behaviours:

- the continuous standardizer is fitted on **training rows only**: a validation row's scaled value
  uses training mean/SD exactly, and is provably different from what a leaked co-fit would give;
- the rare merge honours the pre-registered boundary: a level with exactly 25 development rows is
  retained, one with 24 is merged into ``rare``, and the reference level is always dropped from the
  design matrix (never collinear with the intercept);
- the unseen-level policy encodes a **genuinely unknown synthetic category** as the reference
  (all-zero one-hot) â€” never raises, never drops â€” while a dev-rare level lands in the ``rare``
  column;
- presence indicators are 0/1 with the locked names ``first_time_presence`` /
  ``under_pressure_presence``;
- everything is deterministic: identical inputs give identical columns and identical matrices.
"""

from __future__ import annotations

import math

from touchline.modeling.preprocessing import (
    CONTINUOUS_FIELDS,
    RARE_LEVEL,
    DegenerateScalerError,
    ShotRow,
    StandardScaler,
    encode_rows,
    fit_scaler,
    fit_vocabulary,
)

#: Dev-wide, label-free level counts mirroring the real measured distribution, including the
#: pre-registered boundary cases (Volley 25 retained; Kick Off 29 retained; Other 8 and 18 merged).
DEV_COUNTS: dict[tuple[str, str], int] = {
    ("body_part_name", "Right Foot"): 100,
    ("body_part_name", "Left Foot"): 60,
    ("body_part_name", "Head"): 40,
    ("body_part_name", "Other"): 18,
    ("technique_name", "Normal"): 120,
    ("technique_name", "Half Volley"): 30,
    ("technique_name", "Volley"): 25,
    ("technique_name", "Backheel"): 12,
    ("technique_name", "Diving Header"): 20,
    ("technique_name", "Overhead Kick"): 17,
    ("technique_name", "Lob"): 17,
    ("play_pattern_name", "Regular Play"): 80,
    ("play_pattern_name", "From Free Kick"): 50,
    ("play_pattern_name", "From Corner"): 45,
    ("play_pattern_name", "From Throw In"): 40,
    ("play_pattern_name", "From Goal Kick"): 35,
    ("play_pattern_name", "From Counter"): 32,
    ("play_pattern_name", "From Keeper"): 31,
    ("play_pattern_name", "From Kick Off"): 29,
    ("play_pattern_name", "Other"): 8,
}


def _row(
    *,
    distance_to_goal: float = 30.0,
    visible_goal_angle: float = 0.3,
    body_part_name: str = "Right Foot",
    technique_name: str = "Normal",
    play_pattern_name: str = "Regular Play",
    first_time: bool | None = None,
    under_pressure: bool | None = None,
    y: int = 0,
    competition_id: int = 43,
    season_id: int = 3,
) -> ShotRow:
    return ShotRow(
        shot_id="s",
        match_id=1,
        fold=0,
        competition_id=competition_id,
        season_id=season_id,
        y=y,
        distance_to_goal=distance_to_goal,
        visible_goal_angle=visible_goal_angle,
        body_part_name=body_part_name,
        technique_name=technique_name,
        play_pattern_name=play_pattern_name,
        first_time=first_time,
        under_pressure=under_pressure,
    )


def _scaler() -> StandardScaler:
    """A scaler fitted on rows whose both continuous features vary (never degenerate)."""
    return fit_scaler(
        [
            _row(distance_to_goal=10.0, visible_goal_angle=0.1),
            _row(distance_to_goal=20.0, visible_goal_angle=0.3),
            _row(distance_to_goal=30.0, visible_goal_angle=0.5),
        ]
    )


def test_vocabulary_rare_merge_boundary_and_reference_dropped() -> None:
    vocab = fit_vocabulary(DEV_COUNTS)
    # 25 retained (Volley), 24 would merge; the explicitly-raised boundary is exercised below.
    assert "Volley" in vocab.levels["technique_name"]
    # Reference levels are dropped from the design columns (interpreted against the intercept).
    assert "Right Foot" not in vocab.levels["body_part_name"]
    assert "Normal" not in vocab.levels["technique_name"]
    assert "Regular Play" not in vocab.levels["play_pattern_name"]
    # Dev-rare members recorded for the artifact manifest.
    assert set(vocab.rare_members["body_part_name"]) == {"Other"}
    assert set(vocab.rare_members["play_pattern_name"]) == {"Other"}
    assert {"Backheel", "Diving Header", "Overhead Kick", "Lob"} <= set(
        vocab.rare_members["technique_name"]
    )


def test_rare_merge_threshold_is_exact() -> None:
    counts = dict(DEV_COUNTS)
    counts[("body_part_name", "Head")] = 25  # boundary: retained
    counts[("body_part_name", "Left Foot")] = 24  # boundary: merged
    vocab = fit_vocabulary(counts)
    assert "Head" in vocab.levels["body_part_name"]
    assert "Left Foot" in vocab.rare_members["body_part_name"]


def test_column_names_are_deterministic_and_reference_free() -> None:
    vocab = fit_vocabulary(DEV_COUNTS)
    names = vocab.column_names()
    assert names[:2] == ["distance_to_goal", "visible_goal_angle"]
    assert names[2:4] == ["first_time_presence", "under_pressure_presence"]
    # body_part: Head, Left Foot, rare (Right Foot dropped) -> 3 columns.
    assert names[4:7] == [
        "body_part_name::Head",
        "body_part_name::Left Foot",
        "body_part_name::rare",
    ]
    # Total: 2 continuous + 2 presence + 3 + 3 + (8 play-pattern non-reference) = 18.
    assert len(names) == 18
    assert fit_vocabulary(DEV_COUNTS).column_names() == names


def test_scaler_is_fitted_on_training_rows_only() -> None:
    train = [
        _row(distance_to_goal=10.0, visible_goal_angle=0.1),
        _row(distance_to_goal=20.0, visible_goal_angle=0.3),
        _row(distance_to_goal=30.0, visible_goal_angle=0.5),
    ]
    val = [_row(distance_to_goal=999.0, visible_goal_angle=0.2)]
    scaler = fit_scaler(train)
    matrix, names = encode_rows(val, fit_vocabulary(DEV_COUNTS), scaler)
    distance_index = names.index("distance_to_goal")
    expected = (999.0 - 20.0) / (math.sqrt(((10 - 20) ** 2 + (20 - 20) ** 2 + (30 - 20) ** 2) / 3))
    assert math.isclose(matrix[0, distance_index], expected, abs_tol=1e-12)
    # A leaked co-fit (train + validation) would give a different scale. Prove it matters:
    leaked = fit_scaler(train + val)
    leak_matrix, _ = encode_rows(val, fit_vocabulary(DEV_COUNTS), leaked)
    assert not math.isclose(leak_matrix[0, distance_index], matrix[0, distance_index])


def test_presence_indicators_are_zero_one_and_never_booleans() -> None:
    vocab = fit_vocabulary(DEV_COUNTS)
    scaler = _scaler()
    rows = [
        _row(first_time=True, under_pressure=None),
        _row(first_time=None, under_pressure=True),
        _row(first_time=None, under_pressure=None),
    ]
    matrix, names = encode_rows(rows, vocab, scaler)
    ft = names.index("first_time_presence")
    up = names.index("under_pressure_presence")
    assert matrix[0, ft] == 1.0 and matrix[0, up] == 0.0
    assert matrix[1, ft] == 0.0 and matrix[1, up] == 1.0
    assert matrix[2, ft] == 0.0 and matrix[2, up] == 0.0


def test_unseen_level_encodes_as_reference_all_zero_and_never_drops() -> None:
    vocab = fit_vocabulary(DEV_COUNTS)
    scaler = _scaler()
    reference_row = _row(body_part_name="Right Foot")
    unseen_row = _row(body_part_name="SyntheticUnknownLevel")
    ref_matrix, names = encode_rows([reference_row], vocab, scaler)
    unseen_matrix, _ = encode_rows([unseen_row], vocab, scaler)
    body_a = names.index("body_part_name::Head")
    body_b = names.index("body_part_name::Left Foot")
    body_c = names.index("body_part_name::rare")
    # The unseen category is a genuinely unknown value; it must produce the reference (all-zero)
    # encoding for the field â€” identical to the reference row, never raising and never dropping.
    for col in (body_a, body_b, body_c):
        assert ref_matrix[0, col] == 0.0
        assert unseen_matrix[0, col] == ref_matrix[0, col]


def test_dev_rare_level_lands_in_the_rare_column() -> None:
    vocab = fit_vocabulary(DEV_COUNTS)
    scaler = _scaler()
    matrix, names = encode_rows([_row(technique_name="Backheel")], vocab, scaler)
    rare_col = names.index(f"technique_name::{RARE_LEVEL}")
    assert matrix[0, rare_col] == 1.0


def test_encoding_is_deterministic() -> None:
    vocab = fit_vocabulary(DEV_COUNTS)
    scaler = _scaler()
    rows = [_row(distance_to_goal=12.5, first_time=True), _row(distance_to_goal=44.0)]
    a, na = encode_rows(rows, vocab, scaler)
    b, nb = encode_rows(rows, vocab, scaler)
    assert na == nb
    assert (a == b).all()


def test_degenerate_zero_variance_scale_fails_loudly() -> None:
    constant_rows = [_row(distance_to_goal=25.0), _row(distance_to_goal=25.0)]
    try:
        fit_scaler(constant_rows)
    except DegenerateScalerError:
        pass
    else:
        raise AssertionError("zero-variance continuous feature must raise DegenerateScalerError")


def test_vocabulary_and_scaler_serialize_for_the_artifact_manifest() -> None:
    vocab = fit_vocabulary(DEV_COUNTS)
    assert set(vocab.as_dict()) == {"levels", "reference", "rare_members"}
    scaler = _scaler()
    assert isinstance(scaler.as_dict()["mean"], dict)
    assert set(StandardScaler(mean=scaler.mean, std=scaler.std).as_dict()) == {"mean", "std"}
    assert set(vocab.fields) == set(("body_part_name", "technique_name", "play_pattern_name"))
    assert CONTINUOUS_FIELDS == ("distance_to_goal", "visible_goal_angle")
