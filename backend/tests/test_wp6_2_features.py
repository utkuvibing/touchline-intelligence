"""Public-contract checks for the fold-local WP6.2 F0/F1 transformer."""

from __future__ import annotations

import ast
import inspect
import json
import os
import pickle
import subprocess
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from touchline.features.geometry import distance_to_goal, visible_goal_angle
from touchline.modeling import wp6_2_features as feature_module
from touchline.modeling.preprocessing import (
    ShotRow,
    encode_rows,
    fit_scaler,
    fit_vocabulary,
)
from touchline.modeling.splits import MatchRecord
from touchline.modeling.v2_folds import (
    assign_inner_folds,
    inner_partition,
    load_gate_config,
    outer_fold_specs,
    outer_partition,
)
from touchline.modeling.wp6_1_context import (
    CONTEXT_SCHEMA_VERSION,
    V2ContextObservation,
    V2ShotContext,
    V2ShotMetadata,
)
from touchline.modeling.wp6_2_features import (
    ArtifactCompatibilityError,
    DegenerateKnotError,
    DegenerateNumericStateError,
    compatibility_probe_observations,
    fit_v2_transformer,
    load_v2_transformer,
    save_v2_transformer,
)
from touchline.modeling.wp6_2_training import (
    LabelJoinError,
    load_v2_training_rows,
    verified_cohort_sql,
)


def _observations(count: int = 30) -> tuple[V2ContextObservation, ...]:
    base = V2ShotContext(
        CONTEXT_SCHEMA_VERSION,
        100.0,
        40.0,
        distance_to_goal(100, 40),
        visible_goal_angle(100, 40),
        "Right Foot",
        "Normal",
        "Open Play",
        "Regular Play",
        None,
        None,
        1,
        1,
        1,
        61,
        0,
        0,
        1,
        1.0,
        1,
        None,
        None,
        None,
        (),
    )
    rows = []
    for index in range(count):
        x, y = 75.0 + index, 15.0 + (index % 35)
        context = replace(
            base,
            location_x=x,
            location_y=y,
            distance_to_goal=distance_to_goal(x, y),
            visible_goal_angle=visible_goal_angle(x, y),
            first_time=index % 2 == 0,
            under_pressure=index % 3 == 0,
            play_pattern_name=None if index == 0 else "Regular Play",
        )
        rows.append(
            V2ContextObservation(
                V2ShotMetadata(str(index), index // 2, 43, 3, "WC2018", date(2018, 1, 1), index),
                context,
            )
        )
    return tuple(rows)


def test_f1_has_f0_plus_frozen_splines_and_raw_standardized_interaction() -> None:
    rows = _observations()
    f0 = fit_v2_transformer(rows, "F0")
    f1 = fit_v2_transformer(rows, "F1")
    matrix = f1.transform(rows)
    assert matrix.columns[: len(f0.columns)] == f0.columns
    assert matrix.values.shape == (30, len(f0.columns) + 13)
    assert matrix.columns[-13:] == tuple(
        [f"distance_spline_{i}" for i in range(6)]
        + [f"angle_spline_{i}" for i in range(6)]
        + ["distance_angle_z_product"]
    )
    np.testing.assert_allclose(matrix.values[:, -1], matrix.values[:, 0] * matrix.values[:, 1])
    assert f1.distance_spline is not None and f1.distance_spline.degree == 3
    assert f1.distance_spline.extrapolation == "linear"
    assert f1.distance_spline.include_bias is False


def test_constant_presence_indicators_are_valid_but_duplicate_spline_knots_fail() -> None:
    rows = _observations()
    constant_indicators = tuple(
        replace(item, context=replace(item.context, first_time=None, under_pressure=False))
        for item in rows
    )
    assert np.all(
        fit_v2_transformer(constant_indicators, "F0").transform(constant_indicators).values[:, 2:4]
        == 0
    )
    # Raw variance remains nonzero, so this reaches the stricter duplicate-knot boundary.
    repeated = tuple(
        replace(item, context=rows[0].context if index < 26 else item.context)
        for index, item in enumerate(rows)
    )
    with pytest.raises(DegenerateKnotError):
        fit_v2_transformer(repeated, "F1")


def test_f0_matches_existing_v1_encoding_on_shared_fixture() -> None:
    observations = _observations()[1:]
    rows = tuple(
        ShotRow(
            shot_id=item.metadata.shot_id,
            match_id=item.metadata.match_id,
            fold=None,
            competition_id=item.metadata.competition_id,
            season_id=item.metadata.season_id,
            y=0,
            distance_to_goal=item.context.distance_to_goal,
            visible_goal_angle=item.context.visible_goal_angle,
            body_part_name=item.context.body_part_name,
            technique_name=item.context.technique_name,
            play_pattern_name=item.context.play_pattern_name or "Regular Play",
            first_time=item.context.first_time,
            under_pressure=item.context.under_pressure,
        )
        for item in observations
    )
    # The v1 vocabulary accepts only categorical counts; use the same source values as WP6.2.
    counts = {
        (field, getattr(row, field)): sum(
            getattr(other, field) == getattr(row, field) for other in rows
        )
        for field in ("body_part_name", "technique_name", "play_pattern_name")
        for row in rows
    }
    vocabulary = fit_vocabulary(counts)
    scaler = fit_scaler(rows)
    expected_values, expected_columns = encode_rows(rows, vocabulary, scaler)
    actual = fit_v2_transformer(observations, "F0").transform(observations)
    assert actual.columns == tuple(expected_columns)
    np.testing.assert_array_equal(actual.values, expected_values)


def test_missing_unseen_and_rare_categories_follow_v1_policy() -> None:
    rows = _observations()
    rare_rows = tuple(
        replace(
            item,
            context=replace(
                item.context,
                body_part_name="Left Foot" if index < 2 else "Right Foot",
                technique_name="Volley" if index < 3 else "Normal",
            ),
        )
        for index, item in enumerate(rows)
    )
    transformer = fit_v2_transformer(rare_rows, "F0")
    matrix = transformer.transform(rare_rows)
    body_rare = matrix.columns.index("body_part_name::rare")
    technique_rare = matrix.columns.index("technique_name::rare")
    play_rare = matrix.columns.index("play_pattern_name::rare")
    assert np.all(matrix.values[:2, body_rare] == 1.0)
    assert np.all(matrix.values[:3, technique_rare] == 1.0)
    # The reserved missing token is counted before fitting.
    assert matrix.values[0, play_rare] == 1.0
    unseen = replace(
        rare_rows[0],
        context=replace(
            rare_rows[0].context,
            body_part_name="Head",
            technique_name="Backheel",
            play_pattern_name="From Corner",
        ),
    )
    unseen_matrix = transformer.transform((unseen,))
    category_columns = [index for index, name in enumerate(matrix.columns) if "::" in name]
    assert np.all(unseen_matrix.values[0, category_columns] == 0.0)


def test_f1_knots_scalers_and_parameters_are_exact() -> None:
    rows = _observations()
    transformer = fit_v2_transformer(rows, "F1")
    expected_distance = np.quantile(
        np.asarray([row.context.distance_to_goal for row in rows], dtype=np.float64),
        [0.0, 0.25, 0.5, 0.75, 1.0],
        method="linear",
    )
    assert transformer.knots is not None
    np.testing.assert_array_equal(transformer.knots["distance"], expected_distance)
    assert transformer.distance_spline is not None
    params = transformer.distance_spline.get_params(deep=False)
    assert params["degree"] == 3
    assert params["extrapolation"] == "linear"
    assert params["handle_missing"] == "error"
    assert params["include_bias"] is False
    assert params["n_knots"] == 5
    assert params["order"] == "C"
    assert params["sparse_output"] is False
    basis = transformer.distance_spline.transform(
        np.asarray([row.context.distance_to_goal for row in rows], dtype=np.float64).reshape(-1, 1)
    )
    assert transformer.spline_mean is not None and transformer.spline_std is not None
    np.testing.assert_array_equal(transformer.spline_mean["distance"], basis.mean(axis=0))
    np.testing.assert_array_equal(transformer.spline_std["distance"], basis.std(axis=0, ddof=0))
    matrix = transformer.transform(rows)
    np.testing.assert_array_equal(matrix.values[:, -1], matrix.values[:, 0] * matrix.values[:, 1])


def test_constant_raw_numeric_and_degenerate_fitted_spline_state_fail() -> None:
    rows = _observations()
    constant = tuple(
        replace(
            item,
            context=replace(
                item.context,
                location_x=rows[0].context.location_x,
                location_y=rows[0].context.location_y,
                distance_to_goal=rows[0].context.distance_to_goal,
                visible_goal_angle=rows[0].context.visible_goal_angle,
            ),
        )
        for item in rows
    )
    with pytest.raises(DegenerateNumericStateError):
        fit_v2_transformer(constant, "F0")
    transformer = fit_v2_transformer(rows, "F1")
    assert transformer.spline_std is not None
    transformer.spline_std["distance"][0] = 0.0
    with pytest.raises(DegenerateNumericStateError):
        transformer.transform(rows)


def test_near_degenerate_knot_gap_fails_without_fallback() -> None:
    values = np.asarray(
        [0.0, 0.0, 0.0, 1e-15, 1e-15, 1e-15, 1.0, 2.0, 3.0, 4.0, 5.0],
        dtype=np.float64,
    )
    with pytest.raises(DegenerateKnotError):
        feature_module._spline(values, "distance")


def test_shared_fold_primitive_keeps_validation_out_of_fitted_state() -> None:
    rows = _observations()
    config = load_gate_config()
    matches = tuple(
        MatchRecord(item.metadata.match_id, 43, 3, date(2018, 1, 1))
        for item in rows
        if item.metadata.event_index % 2 == 0
    )
    assignment = assign_inner_folds(matches, config, training_scopes={(43, 3)})
    training_matches, validation_matches = inner_partition(assignment, 0, config)
    training = tuple(item for item in rows if item.metadata.match_id in training_matches)
    validation = tuple(item for item in rows if item.metadata.match_id in validation_matches)
    transformer = fit_v2_transformer(training, "F1")
    mutated_validation = tuple(
        replace(
            item,
            context=replace(
                item.context,
                location_x=119.0,
                location_y=79.0,
                distance_to_goal=distance_to_goal(119.0, 79.0),
                visible_goal_angle=visible_goal_angle(119.0, 79.0),
                body_part_name="Head",
                technique_name="Backheel",
                play_pattern_name="From Corner",
            ),
        )
        for item in validation
    )
    # Validation values still use the frozen state, and cannot alter its digest or learned state.
    before = (transformer.numeric_mean.copy(), transformer.numeric_std.copy(), transformer.knots)
    transformed = transformer.transform(mutated_validation)
    assert transformed.values.shape[0] == len(validation)
    assert before[0] == transformer.numeric_mean
    assert before[1] == transformer.numeric_std
    assert before[2] == transformer.knots


def test_empty_malformed_and_duplicate_inputs_fail_loudly() -> None:
    with pytest.raises(ValueError):
        fit_v2_transformer((), "F0")
    with pytest.raises(TypeError):
        fit_v2_transformer((object(),), "F0")  # type: ignore[arg-type]
    rows = _observations(2)
    duplicate = replace(
        rows[1], metadata=replace(rows[1].metadata, shot_id=rows[0].metadata.shot_id)
    )
    with pytest.raises(ValueError, match="duplicate shot"):
        fit_v2_transformer((rows[0], duplicate), "F0")


class _FakeTransaction:
    def __enter__(self) -> _FakeTransaction:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _FakeCursor:
    def __init__(self, rows: list[tuple[object, object]]) -> None:
        self.rows = rows
        self.executed: list[tuple[str, object]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str, params: object = None) -> None:
        self.executed.append((sql, params))

    def fetchall(self) -> list[tuple[object, object]]:
        return self.rows


class _FakeConnection:
    def __init__(self, rows: list[tuple[object, object]]) -> None:
        self.cursor_value = _FakeCursor(rows)

    def transaction(self) -> _FakeTransaction:
        return _FakeTransaction()

    def cursor(self) -> _FakeCursor:
        return self.cursor_value


def test_label_join_is_read_only_authoritative_and_preserves_observation_order() -> None:
    rows = _observations(3)
    connection = _FakeConnection(
        [
            (rows[2].metadata.shot_id, 1),
            (rows[0].metadata.shot_id, 0),
            (rows[1].metadata.shot_id, 1),
        ]
    )
    joined = load_v2_training_rows(connection, rows)  # type: ignore[arg-type]
    assert [item.observation.metadata.shot_id for item in joined] == [
        item.metadata.shot_id for item in rows
    ]
    assert [item.is_goal for item in joined] == [0, 1, 1]
    assert "SET TRANSACTION READ ONLY" in connection.cursor_value.executed[0][0]
    query = connection.cursor_value.executed[1][0]
    assert query.startswith("SELECT shot_id::text, is_goal FROM (")
    assert "ANY(%s::text[])" in query
    assert verified_cohort_sql().encode("utf-8") in query.encode("utf-8")


@pytest.mark.parametrize(
    "label_rows",
    [
        [("0", 0)],  # missing
        [("0", 0), ("0", 1), ("1", 0), ("2", 1)],  # duplicate and extra
        [("0", 2), ("1", 0), ("2", 1)],  # non-binary
        [("foreign", 0), ("1", 0), ("2", 1)],  # foreign
    ],
)
def test_label_join_rejects_alignment_and_target_violations(
    label_rows: list[tuple[object, object]],
) -> None:
    with pytest.raises(LabelJoinError):
        load_v2_training_rows(_FakeConnection(label_rows), _observations(3))  # type: ignore[arg-type]


def test_feature_module_has_no_label_module_dependency() -> None:
    source = Path(__file__).parents[1] / "src/touchline/modeling/wp6_2_features.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert all("wp6_2_training" not in ast.unparse(node) for node in imports)


def test_artifact_round_trip_probe_identity_and_dependency_policy(tmp_path: Path) -> None:
    rows = _observations()
    transformer = fit_v2_transformer(rows, "F1")
    pickle_path, manifest_path = tmp_path / "transformer.pkl", tmp_path / "transformer.json"
    save_v2_transformer(transformer, pickle_path, manifest_path)
    loaded = load_v2_transformer(pickle_path, manifest_path)
    expected_probe = transformer.transform(compatibility_probe_observations())
    actual_probe = loaded.transform(compatibility_probe_observations())
    np.testing.assert_allclose(actual_probe.values, expected_probe.values, rtol=0.0, atol=1e-12)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "probe_inputs" in manifest and "probe_values" in manifest
    assert manifest["transformer_schema"] == "FittedV2Transformer"
    assert manifest["pickle_protocol"] == 5
    assert "is_goal" not in json.dumps(manifest)
    assert "outcome" not in json.dumps(manifest)
    # Patch/minor ranges are explicitly allowed, but a major/minor mismatch is not.
    manifest["versions"]["python"] = "3.12.99"
    manifest["versions"]["sklearn"] = "1.9.99"
    manifest["versions"]["numpy"] = "2.99.0"
    manifest["versions"]["scipy"] = "1.99.0"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    load_v2_transformer(pickle_path, manifest_path)
    manifest["versions"]["python"] = "3.13.0"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ArtifactCompatibilityError, match="python"):
        load_v2_transformer(pickle_path, manifest_path)


def test_artifact_rejects_changed_probe_or_column_contract(tmp_path: Path) -> None:
    transformer = fit_v2_transformer(_observations(), "F0")
    pickle_path, manifest_path = tmp_path / "transformer.pkl", tmp_path / "transformer.json"
    save_v2_transformer(transformer, pickle_path, manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["columns"] = list(reversed(manifest["columns"]))
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ArtifactCompatibilityError, match="column"):
        load_v2_transformer(pickle_path, manifest_path)


def test_artifact_rejects_actual_pickle_protocol_mismatch(tmp_path: Path) -> None:
    transformer = fit_v2_transformer(_observations(), "F0")
    pickle_path, manifest_path = tmp_path / "transformer.pkl", tmp_path / "transformer.json"
    save_v2_transformer(transformer, pickle_path, manifest_path)
    pickle_path.write_bytes(pickle.dumps(transformer, protocol=4))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["pickle_sha256"] = feature_module._sha(pickle_path)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ArtifactCompatibilityError, match="protocol"):
        load_v2_transformer(pickle_path, manifest_path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema_version", "wrong", "schema"),
        ("pipeline_config_sha256", "0" * 64, "pipeline_config_sha256"),
        ("dictionary_sha256", "0" * 64, "dictionary_sha256"),
        ("protocol_sha256", "0" * 64, "protocol_sha256"),
        ("cohort_sql_sha256", "0" * 64, "cohort_sql_sha256"),
        ("verified_cohort_query_sha256", "0" * 64, "verified_cohort_query_sha256"),
    ],
)
def test_artifact_rejects_project_and_schema_mutations(
    tmp_path: Path, field: str, value: str, message: str
) -> None:
    transformer = fit_v2_transformer(_observations(), "F0")
    pickle_path, manifest_path = tmp_path / "transformer.pkl", tmp_path / "transformer.json"
    save_v2_transformer(transformer, pickle_path, manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[field] = value
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ArtifactCompatibilityError, match=message):
        load_v2_transformer(pickle_path, manifest_path)


def test_artifact_rejects_pipeline_config_content_mutation(tmp_path: Path) -> None:
    transformer = fit_v2_transformer(_observations(), "F0")
    pickle_path, manifest_path = tmp_path / "transformer.pkl", tmp_path / "transformer.json"
    save_v2_transformer(transformer, pickle_path, manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["pipeline_config"]["bundles"]["F1"]["degree"] = 2
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ArtifactCompatibilityError, match="pipeline configuration"):
        load_v2_transformer(pickle_path, manifest_path)


def test_artifact_rejects_probe_output_nontransformer_and_versions_before_unpickle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transformer = fit_v2_transformer(_observations(), "F0")
    pickle_path, manifest_path = tmp_path / "transformer.pkl", tmp_path / "transformer.json"
    save_v2_transformer(transformer, pickle_path, manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["probe_values"][0][0] += 1.0
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ArtifactCompatibilityError, match="probe"):
        load_v2_transformer(pickle_path, manifest_path)
    save_v2_transformer(transformer, pickle_path, manifest_path)
    pickle_path.write_bytes(b"not-a-transformer")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["pickle_sha256"] = feature_module._sha(pickle_path)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ArtifactCompatibilityError, match="pickle"):
        load_v2_transformer(pickle_path, manifest_path)
    # Dependency rejection happens before pickle.loads, so corrupt bytes cannot mask it.
    manifest["versions"]["sklearn"] = "99.0.0"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(pickle, "loads", lambda _: pytest.fail("unpickled"))
    with pytest.raises(ArtifactCompatibilityError, match="sklearn"):
        load_v2_transformer(pickle_path, manifest_path)


@pytest.mark.parametrize("dependency", ["sklearn", "numpy", "scipy"])
def test_artifact_rejects_each_unsupported_dependency_range(
    tmp_path: Path, dependency: str
) -> None:
    transformer = fit_v2_transformer(_observations(), "F0")
    pickle_path, manifest_path = tmp_path / "transformer.pkl", tmp_path / "transformer.json"
    save_v2_transformer(transformer, pickle_path, manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["versions"][dependency] = "99.0.0"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ArtifactCompatibilityError, match=dependency):
        load_v2_transformer(pickle_path, manifest_path)


def test_artifact_round_trip_in_fresh_subprocess(tmp_path: Path) -> None:
    transformer = fit_v2_transformer(_observations(), "F1")
    pickle_path, manifest_path = tmp_path / "transformer.pkl", tmp_path / "transformer.json"
    save_v2_transformer(transformer, pickle_path, manifest_path)
    script = """
from pathlib import Path
import sys
from touchline.modeling.wp6_2_features import load_v2_transformer

artifact = load_v2_transformer(Path(sys.argv[1]), Path(sys.argv[2]))
assert artifact.bundle == "F1"
assert len(artifact.columns) == 18
"""
    environment = os.environ.copy()
    source_root = str(Path(__file__).parents[1] / "src")
    environment["PYTHONPATH"] = source_root + os.pathsep + environment.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-c", script, str(pickle_path), str(manifest_path)],
        cwd=Path(__file__).parents[2],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_artifact_probe_is_not_caller_overridable(tmp_path: Path) -> None:
    transformer = fit_v2_transformer(_observations(), "F0")
    pickle_path, manifest_path = tmp_path / "transformer.pkl", tmp_path / "transformer.json"
    assert "probe_observations" not in inspect.signature(save_v2_transformer).parameters
    assert "probe_observations" not in inspect.signature(load_v2_transformer).parameters
    with pytest.raises(TypeError):
        save_v2_transformer(transformer, pickle_path, manifest_path, _observations(3))  # type: ignore[call-arg]


def _four_scope_observations() -> tuple[V2ContextObservation, ...]:
    config = load_gate_config()
    scopes = tuple(
        (entry["competition_id"], entry["season_id"], entry["name"])
        for entry in config["development_pool"]
    )
    template = _observations(1)[0].context
    results: list[V2ContextObservation] = []
    serial = 0
    for scope_index, (competition_id, season_id, tournament) in enumerate(scopes):
        for match_offset in range(5):
            for row_offset in range(4):
                x, y = 55.0 + (serial * 1.7) % 60.0, 12.0 + (serial * 7) % 63
                context = replace(
                    template,
                    location_x=x,
                    location_y=y,
                    distance_to_goal=distance_to_goal(x, y),
                    visible_goal_angle=visible_goal_angle(x, y),
                    body_part_name="Left Foot" if serial % 5 == 0 else "Right Foot",
                    technique_name="Volley" if serial % 7 == 0 else "Normal",
                    play_pattern_name="From Corner" if serial % 11 == 0 else "Regular Play",
                )
                results.append(
                    V2ContextObservation(
                        V2ShotMetadata(
                            f"scope-{scope_index}-{match_offset}-{row_offset}",
                            1000 + scope_index * 100 + match_offset,
                            int(competition_id),
                            int(season_id),
                            str(tournament),
                            date(2018 + scope_index * 2, 1, match_offset + 1),
                            row_offset,
                        ),
                        context,
                    )
                )
                serial += 1
    return tuple(results)


def test_every_outer_and_inner_fold_is_fit_isolated() -> None:
    rows = _four_scope_observations()
    config = load_gate_config()
    records = tuple(
        MatchRecord(
            item.metadata.match_id,
            item.metadata.competition_id,
            item.metadata.season_id,
            item.metadata.match_date,
        )
        for item in rows
        if item.metadata.event_index == 0
    )
    specs = outer_fold_specs(config)
    for spec in specs:
        outer_training, outer_holdout = outer_partition(records, specs, spec)
        training_scopes = {(record.competition_id, record.season_id) for record in outer_training}
        assignment = assign_inner_folds(outer_training, config, training_scopes=training_scopes)
        outer_ids = {record.match_id for record in outer_holdout}
        for fold in range(5):
            inner_training_ids, validation_ids = inner_partition(assignment, fold, config)
            training = tuple(row for row in rows if row.metadata.match_id in inner_training_ids)
            excluded = tuple(
                row for row in rows if row.metadata.match_id in set(validation_ids) | outer_ids
            )
            transformer = fit_v2_transformer(training, "F1")
            before = pickle.dumps(transformer, protocol=5)
            mutated = tuple(
                replace(
                    row,
                    context=replace(
                        row.context,
                        location_x=119.0,
                        location_y=79.0,
                        distance_to_goal=distance_to_goal(119, 79),
                        visible_goal_angle=visible_goal_angle(119, 79),
                        body_part_name="Unseen",
                        technique_name="Unseen",
                        play_pattern_name="Unseen",
                    ),
                )
                for row in excluded
            )
            assert transformer.transform(mutated).values.shape[0] == len(excluded)
            assert before == pickle.dumps(transformer, protocol=5)
