"""Contracts for the WP5.4 validation-tier orchestrator."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from touchline import validation_tiers

LOCAL_DB = "postgresql://touchline:localdev@127.0.0.1:5433/touchline"
LOCAL_COHORT_DB = "postgresql://touchline:localdev@localhost:5433/touchline_cohort"
REMOTE_DB = "postgresql://touchline:secret@db.example.com:5432/touchline"


def test_pr_plan_composes_existing_code_health_commands() -> None:
    plan = validation_tiers.plan_for(validation_tiers.Tier.PR)

    assert plan.purpose == "Code health"
    assert [command.argv for command in plan.commands] == [
        ("uv", "run", "poe", "check"),
        ("npm", "--prefix", "frontend", "run", "lint"),
        ("npm", "--prefix", "frontend", "run", "typecheck"),
        ("npm", "--prefix", "frontend", "test"),
    ]


@pytest.mark.parametrize(
    "value",
    [
        LOCAL_DB,
        LOCAL_COHORT_DB,
        "postgresql://u:p@[::1]/db",
        "postgresql://u:p@localhost/db?sslmode=disable&application_name=validation",
    ],
)
def test_loopback_postgres_targets_are_allowed(value: str) -> None:
    assert validation_tiers.is_local_postgres_url(value) is True


@pytest.mark.parametrize(
    "value", [REMOTE_DB, "postgresql://u:p@localhost.evil.example.com/db", "not-a-url"]
)
def test_unknown_or_remote_targets_fail_closed(value: str) -> None:
    assert validation_tiers.is_local_postgres_url(value) is False


@pytest.mark.parametrize(
    "value",
    [
        "postgresql://u:p@localhost/db?hostaddr=203.0.113.10",
        "postgresql://u:p@localhost/db?host=db.example.com",
        "postgresql://u:p@localhost/db?service=production",
        "postgresql://u:p@localhost/db?port=5432",
        "postgresql://u:p@localhost/db?ho%73taddr=203.0.113.10",
        "postgresql://u:p@localhost:5433,203.0.113.10:5432/db",
        "postgresql://u:p@localhost:5433,db.example.com:5432/db",
    ],
)
def test_libpq_routing_query_parameters_fail_closed(value: str) -> None:
    assert validation_tiers.is_local_postgres_url(value) is False


def test_missing_required_database_refuses_before_dispatch(tmp_path: Path) -> None:
    dispatched: list[tuple[str, ...]] = []

    def dispatch(argv: Sequence[str], _: Path, __: Mapping[str, str]) -> int:
        dispatched.append(tuple(argv))
        return 0

    with pytest.raises(validation_tiers.ValidationPrerequisiteError, match="TOUCHLINE_DB_URL"):
        validation_tiers.run_tier(
            validation_tiers.Tier.PR,
            {},
            repo_root=tmp_path,
            run_command=dispatch,
        )

    assert dispatched == []


def test_remote_database_refuses_before_dispatch(tmp_path: Path) -> None:
    with pytest.raises(
        validation_tiers.ValidationPrerequisiteError, match="possible deployed write"
    ):
        validation_tiers.run_tier(
            validation_tiers.Tier.PR,
            {"TOUCHLINE_DB_URL": REMOTE_DB},
            repo_root=tmp_path,
        )


def test_pr_dispatches_in_order_and_stops_on_first_failure(tmp_path: Path) -> None:
    dispatched: list[tuple[str, ...]] = []

    def dispatch(argv: Sequence[str], _: Path, __: Mapping[str, str]) -> int:
        command = tuple(argv)
        dispatched.append(command)
        return 17 if len(dispatched) == 2 else 0

    result = validation_tiers.run_tier(
        validation_tiers.Tier.PR,
        {"TOUCHLINE_DB_URL": LOCAL_DB},
        repo_root=tmp_path,
        run_command=dispatch,
    )

    assert result == 17
    assert dispatched == [
        ("uv", "run", "poe", "check"),
        ("npm", "--prefix", "frontend", "run", "lint"),
    ]


def test_pr_children_cannot_inherit_full_cohort_or_full_source_opt_ins(tmp_path: Path) -> None:
    child_environments: list[dict[str, str]] = []
    parent_environment = {
        "TOUCHLINE_DB_URL": LOCAL_DB,
        "TOUCHLINE_FULL_COHORT_DB_URL": "postgresql://u:p@sealed.example/db",
        "TOUCHLINE_FULL_SOURCE": "1",
        "touchline_full_source": "1",
        "Touchline_Full_Cohort_Db_Url": "postgresql://u:p@sealed.example/db",
        "PGHOSTADDR": "203.0.113.10",
        "pgservice": "production",
        "PGSERVICEFILE": "C:/secrets/pg_service.conf",
        "PATH": "test-path",
    }

    def dispatch(_: Sequence[str], __: Path, environment: Mapping[str, str]) -> int:
        child_environments.append(dict(environment))
        return 0

    assert (
        validation_tiers.run_tier(
            validation_tiers.Tier.PR,
            parent_environment,
            repo_root=tmp_path,
            run_command=dispatch,
        )
        == 0
    )

    assert child_environments
    assert all(
        not (
            validation_tiers.PR_DATA_SCOPE_ENVIRONMENT | validation_tiers.LIBPQ_ROUTING_ENVIRONMENT
        ).intersection(variable.upper() for variable in environment)
        for environment in child_environments
    )
    assert all(environment["TOUCHLINE_DB_URL"] == LOCAL_DB for environment in child_environments)
    assert parent_environment["TOUCHLINE_FULL_SOURCE"] == "1"


def test_subprocess_receives_only_the_explicit_child_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    received: dict[str, Any] = {}

    def fake_run(argv: tuple[str, ...], **kwargs: Any) -> object:
        received["argv"] = argv
        received.update(kwargs)
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert validation_tiers._run_command(("example",), tmp_path, {"ONLY": "explicit"}) == 0
    assert received == {
        "argv": ("example",),
        "cwd": tmp_path,
        "env": {"ONLY": "explicit"},
        "check": False,
    }


def test_milestone_refuses_before_any_command_until_sentinel_runner_exists(tmp_path: Path) -> None:
    dispatched: list[tuple[str, ...]] = []

    def dispatch(argv: Sequence[str], _: Path, __: Mapping[str, str]) -> int:
        dispatched.append(tuple(argv))
        return 0

    with pytest.raises(validation_tiers.TierUnavailableError, match="15-sentinel"):
        validation_tiers.run_tier(
            validation_tiers.Tier.MILESTONE,
            {"TOUCHLINE_DB_URL": LOCAL_DB, "TOUCHLINE_FULL_COHORT_DB_URL": LOCAL_COHORT_DB},
            repo_root=tmp_path,
            is_clean_tree=lambda: True,
            run_command=dispatch,
        )

    assert dispatched == []


def test_milestone_requires_a_clean_tree_before_unavailability(tmp_path: Path) -> None:
    with pytest.raises(validation_tiers.ValidationPrerequisiteError, match="clean Git"):
        validation_tiers.run_tier(
            validation_tiers.Tier.MILESTONE,
            {"TOUCHLINE_DB_URL": LOCAL_DB, "TOUCHLINE_FULL_COHORT_DB_URL": LOCAL_COHORT_DB},
            repo_root=tmp_path,
            is_clean_tree=lambda: False,
        )


def test_release_requires_full_cohort_database_before_unavailability(tmp_path: Path) -> None:
    with pytest.raises(
        validation_tiers.ValidationPrerequisiteError, match="TOUCHLINE_FULL_COHORT_DB_URL"
    ):
        validation_tiers.run_tier(
            validation_tiers.Tier.RELEASE,
            {"TOUCHLINE_DB_URL": LOCAL_DB},
            repo_root=tmp_path,
            is_clean_tree=lambda: True,
        )


def test_dry_run_reports_blocked_future_tier_without_dispatching(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert validation_tiers.main(["milestone", "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "Scientific and contract integrity" in output
    assert "BLOCKED:" in output
    assert "15-sentinel" in output
