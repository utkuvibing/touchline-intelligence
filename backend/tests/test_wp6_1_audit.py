"""Focused audit contracts; this module must stay structurally label-free."""

from __future__ import annotations

import inspect
import json
from datetime import date
from pathlib import Path

import pytest
from test_wp6_1_context import _context

from touchline.modeling import wp6_1_audit
from touchline.modeling.wp6_1_audit import (
    FeatureDictionaryError,
    build_coverage_report,
    load_feature_dictionary,
)
from touchline.modeling.wp6_1_context import V2ContextObservation, V2ShotMetadata


def test_committed_dictionary_validates_and_never_admits_a_bundle() -> None:
    dictionary = load_feature_dictionary()
    assert dictionary["schema_version"] == "1.0"
    assert "V2TrainingExample" not in inspect.getsource(wp6_1_audit)
    assert "wp6_1_labels" not in inspect.getsource(wp6_1_audit)
    assert dictionary["source_observation_statuses"] == [
        "confirmed",
        "requires_normalization",
        "unsupported",
    ]
    assert "admit" in str(dictionary["admission_disclaimer"])


def test_dictionary_rejects_provider_xg_at_canonical_boundary(tmp_path: Path) -> None:
    payload = json.loads(load_feature_dictionary.__globals__["FEATURE_DICTIONARY_PATH"].read_text())
    payload["features"][0]["source_fields"] = ["statsbomb_xg"]
    path = tmp_path / "dictionary.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(FeatureDictionaryError, match="provider xG"):
        load_feature_dictionary(path)

    payload = json.loads(load_feature_dictionary.__globals__["FEATURE_DICTIONARY_PATH"].read_text())
    payload["features"][0]["source_fields"] = ["xg"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(FeatureDictionaryError, match="provider xG"):
        load_feature_dictionary(path)


def test_coverage_is_target_free_and_tournament_partitioned() -> None:
    observation = V2ContextObservation(
        V2ShotMetadata("a", 1, 43, 3, "WC2018", date(2018, 6, 14), 2),
        _context(),
    )
    report = build_coverage_report([observation], load_feature_dictionary())
    assert report.total_contexts == 1
    assert report.contexts_by_tournament == {
        "Euro2020": 0,
        "Euro2024": 0,
        "WC2018": 1,
        "WC2022": 0,
    }
    assert report.availability_by_feature_and_tournament["distance_to_goal"]["WC2018"] == {
        "available": 1,
        "absent": 0,
        "invalid": 0,
        "unsupported": 0,
    }
    assert report.invalid_structure_count == 0
    assert report.freeze_frame_by_tournament["WC2018"]["unusable_freeze_frames"] == 1
    assert report.freeze_frame_by_tournament["WC2018"]["shots_without_identified_goalkeeper"] == 1
    assert sum(report.missingness_signatures_by_tournament["WC2018"].values()) == 1
    assert report.availability_by_feature_and_tournament["preceding_event_end_zone"]["WC2018"] == {
        "available": 0,
        "absent": 0,
        "invalid": 0,
        "unsupported": 1,
    }


def test_audit_refuses_empty_context_population() -> None:
    with pytest.raises(ValueError, match="at least one context"):
        build_coverage_report([], load_feature_dictionary())


def test_dictionary_rejects_wrong_status_declaration(tmp_path: Path) -> None:
    payload = json.loads(load_feature_dictionary.__globals__["FEATURE_DICTIONARY_PATH"].read_text())
    payload["source_observation_statuses"] = ["confirmed", "unsupported"]
    path = tmp_path / "dictionary.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(FeatureDictionaryError, match="exactly the three"):
        load_feature_dictionary(path)


def test_dictionary_rejects_an_unreviewed_schema_version(tmp_path: Path) -> None:
    payload = json.loads(load_feature_dictionary.__globals__["FEATURE_DICTIONARY_PATH"].read_text())
    payload["schema_version"] = "2.0"
    path = tmp_path / "dictionary.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(FeatureDictionaryError, match="schema_version"):
        load_feature_dictionary(path)


def test_cli_refuses_a_deployed_database_before_connecting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    connected = False

    def forbidden_connect(*args: object, **kwargs: object) -> None:
        nonlocal connected
        connected = True

    monkeypatch.setenv(
        "TOUCHLINE_FULL_COHORT_DB_URL",
        "postgresql://u:p@deployed.example.com/touchline",
    )
    monkeypatch.setattr("touchline.modeling.wp6_1_audit.psycopg.connect", forbidden_connect)

    assert wp6_1_audit.main(["--json-out", str(tmp_path / "report.json")]) == 1
    assert connected is False
