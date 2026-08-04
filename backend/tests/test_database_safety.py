"""Contracts for the boundary that keeps destructive tests off non-local databases.

The failure this prevents leaves no evidence to debug afterwards: `.env` holds a deployment DSN for
a legitimate reason, someone runs pytest, and a fixture drops and recreates schemas in a database
nobody meant to touch. Every proof below is written as "the run stops *before* a connection is
opened", because a guard that refuses after connecting has already done the damage it exists to
prevent.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import psycopg
import pytest
from support import db_safety
from support.db_safety import UnsafeTestDatabaseError, connect_local, require_local_test_database

TESTS_DIR = Path(__file__).parent

#: Modules allowed to call ``psycopg.connect`` directly, with the reason each is not a mutation
#: risk. Anything else that connects must go through the guard, which is asserted structurally
#: below — a new fixture should not be able to reintroduce the hazard by not knowing about it.
DIRECT_CONNECT_ALLOWED = {
    # Read-only WP2.2 evidence: their own variable, READ ONLY transactions, no DDL. Both are
    # gated on TOUCHLINE_FULL_COHORT_DB_URL rather than TOUCHLINE_DB_URL, and neither creates a
    # schema, applies a migration or seeds a fixture -- there is nothing here for the mutation
    # guard to protect, and routing them through it would misstate what they do.
    "test_wp2_2_geometry_integration.py",
    "test_wp2_2_coverage_integration.py",
    # Connectivity smoke test: issues SELECT 1 and nothing else.
    "test_database_integration.py",
    # Policy tests that patch psycopg.connect to prove it is never reached.
    "test_write_target_policy.py",
    "test_ingest_command_policy.py",
    "test_ops_endpoints.py",
    # The guard itself.
    "test_database_safety.py",
}

LOCAL_TARGETS = [
    pytest.param("postgresql://touchline:localdev@localhost:5433/touchline", id="localhost"),
    pytest.param("postgresql://u:p@db.localhost:5432/touchline", id="name.localhost"),
    pytest.param("postgresql://u:p@127.0.0.1:5432/touchline", id="127.0.0.1"),
    pytest.param("postgresql://u:p@127.9.9.9:5432/touchline", id="127.x.x.x"),
    pytest.param("postgresql://u:p@[::1]:5432/touchline", id="ipv6-loopback"),
]

REMOTE_TARGETS = [
    pytest.param(
        "postgresql://u:p@ep-cool-name-123.eu-central-1.aws.neon.tech/touchline?sslmode=require",
        id="neon",
    ),
    pytest.param("postgresql://u:p@containers-us-west-1.railway.app:7432/railway", id="railway"),
    pytest.param("postgresql://u:p@staging-db.internal.example.com:5432/touchline", id="staging"),
    pytest.param("postgresql://u:p@10.0.0.5:5432/touchline", id="private-10"),
    pytest.param("postgresql://u:p@172.16.4.9:5432/touchline", id="private-172-16"),
    pytest.param("postgresql://u:p@192.168.1.20:5432/touchline", id="private-192-168"),
    pytest.param("postgresql://u:p@0.0.0.0:5432/touchline", id="unspecified-address"),
    pytest.param("postgresql://u:p@localhost.evil.example.com:5432/touchline", id="lookalike-host"),
]

MALFORMED_TARGETS = [
    pytest.param(None, id="unset"),
    pytest.param("", id="empty"),
    pytest.param("   ", id="blank"),
    pytest.param("not-a-dsn", id="not-a-dsn"),
    pytest.param("postgresql://", id="hostless"),
    pytest.param("://u:p@localhost:5432/touchline", id="schemeless"),
]


@pytest.fixture
def forbid_connect(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Record any attempt to open a connection, so "before connecting" is provable, not assumed."""
    attempts: list[object] = []

    def _record(*args: object, **kwargs: object) -> None:
        attempts.append(args)
        raise AssertionError("psycopg.connect was reached despite an unsafe target")

    monkeypatch.setattr(psycopg, "connect", _record)
    return attempts


@pytest.mark.parametrize("dsn", LOCAL_TARGETS)
def test_a_local_target_is_accepted(dsn: str) -> None:
    assert require_local_test_database(dsn) == dsn


@pytest.mark.parametrize("dsn", REMOTE_TARGETS)
def test_a_non_local_target_is_refused(dsn: str) -> None:
    with pytest.raises(UnsafeTestDatabaseError):
        require_local_test_database(dsn)


@pytest.mark.parametrize("dsn", MALFORMED_TARGETS)
def test_an_unclassifiable_target_fails_closed(dsn: str | None) -> None:
    """Absent, blank and unparseable targets are refused rather than given the benefit of doubt."""
    with pytest.raises(UnsafeTestDatabaseError):
        require_local_test_database(dsn)


@pytest.mark.parametrize("dsn", REMOTE_TARGETS + MALFORMED_TARGETS)
def test_the_guard_runs_before_any_connection_is_opened(
    dsn: str | None, forbid_connect: list[object]
) -> None:
    with pytest.raises(UnsafeTestDatabaseError):
        connect_local(dsn)

    assert forbid_connect == []


def test_a_refusal_never_leaks_credentials_or_query_parameters() -> None:
    dsn = (
        "postgresql://neondb_owner:npg_S3cr3tT0k3n@ep-cool-name-123.eu-central-1.aws.neon.tech"
        "/touchline?sslmode=require&options=endpoint%3Dep-cool-name-123"
    )

    with pytest.raises(UnsafeTestDatabaseError) as exc:
        require_local_test_database(dsn)

    message = str(exc.value)
    assert "ep-cool-name-123.eu-central-1.aws.neon.tech/touchline" in message
    for secret in ("neondb_owner", "npg_S3cr3tT0k3n", "sslmode", "options", "endpoint%3D"):
        assert secret not in message
    # The whole DSN must not survive anywhere in the chain either: pydantic puts the offending
    # input value in its own error, so the parse failure is suppressed rather than chained.
    assert dsn not in message
    assert exc.value.__cause__ is None


def test_a_malformed_target_refusal_does_not_echo_the_target() -> None:
    dsn = "postgres!//user:hunter2@somewhere"

    with pytest.raises(UnsafeTestDatabaseError) as exc:
        require_local_test_database(dsn)

    message = str(exc.value)
    assert "hunter2" not in message
    assert dsn not in message
    assert exc.value.__cause__ is None


def test_the_deliberate_ingest_override_cannot_unlock_a_mutating_test_run(
    monkeypatch: pytest.MonkeyPatch, forbid_connect: list[object]
) -> None:
    """`poe ingest` accepts a per-target override. A pytest run must not inherit it.

    The variable is plausibly still exported from an earlier deliberate ingest, and a whole test
    session is a far larger blast radius than the one command it was typed for.
    """
    dsn = "postgresql://u:p@ep-cool-name-123.eu-central-1.aws.neon.tech/touchline"
    monkeypatch.setenv(
        "TOUCHLINE_ALLOW_REMOTE_WRITES", "ep-cool-name-123.eu-central-1.aws.neon.tech/touchline"
    )

    with pytest.raises(UnsafeTestDatabaseError):
        connect_local(dsn)

    assert forbid_connect == []


def test_a_self_declared_local_environment_label_does_not_make_a_target_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOUCHLINE_ENVIRONMENT", "local")

    with pytest.raises(UnsafeTestDatabaseError):
        require_local_test_database("postgresql://u:p@ep-x.eu-central-1.aws.neon.tech/touchline")


def test_connect_local_reaches_psycopg_with_the_validated_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The safe path still connects — a guard that refuses everything protects nothing useful."""
    seen: dict[str, Any] = {}
    opened: Any = object()

    def _capture(dsn: str, **kwargs: Any) -> Any:
        seen["dsn"] = dsn
        seen["kwargs"] = kwargs
        return opened

    monkeypatch.setattr(psycopg, "connect", _capture)

    result: Any = connect_local(
        "postgresql://touchline:localdev@localhost:5433/touchline", autocommit=True
    )

    assert result is opened
    assert seen["dsn"] == "postgresql://touchline:localdev@localhost:5433/touchline"
    assert seen["kwargs"] == {"autocommit": True}


def test_no_mutating_test_module_opens_its_own_connection() -> None:
    """Structural proof that a fixture cannot bypass the boundary by not knowing about it.

    Schema creation, migration, reset and ingestion fixtures all live in modules covered here. A
    new one that calls `psycopg.connect` directly fails this test rather than quietly becoming the
    single unprotected path.
    """
    offenders: list[str] = []
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        if path.name in DIRECT_CONNECT_ALLOWED:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "connect"
                and isinstance(node.value, ast.Name)
                and node.value.id == "psycopg"
            ):
                offenders.append(f"{path.name}:{node.lineno}")

    assert offenders == []


def test_every_mutating_module_imports_the_guard() -> None:
    """The other half of the structural proof: the modules that mutate actually use it."""
    mutating = {
        "test_baseline_integration.py",
        "test_full_cohort_acceptance.py",
        "test_ingest_load_integration.py",
        "test_ingest_run_integration.py",
        "test_migrations_integration.py",
        "test_schema_drift_integration.py",
        "test_shots_integration.py",
        "test_wp1_5_analysis_integration.py",
        "test_wp1_6_reproducibility_integration.py",
        "test_wp2_1_cohort_integration.py",
    }

    missing = {
        name
        for name in mutating
        if "from support.db_safety import connect_local"
        not in (TESTS_DIR / name).read_text(encoding="utf-8")
    }

    assert missing == set()


def test_a_representative_mutating_fixture_refuses_a_deployed_target(
    monkeypatch: pytest.MonkeyPatch, forbid_connect: list[object]
) -> None:
    """End to end through a real fixture, not just the helper it calls.

    `test_migrations_integration` is the sharpest case in the suite: its fixture drops a schema and
    applies every production migration. Pointed at Neon, it must raise before connecting.
    """
    import test_migrations_integration as migrations_module

    monkeypatch.setattr(
        migrations_module,
        "DB_URL",
        "postgresql://u:p@ep-cool-name-123.eu-central-1.aws.neon.tech/touchline",
    )

    fixture = migrations_module.conn.__wrapped__  # type: ignore[attr-defined]
    with pytest.raises(UnsafeTestDatabaseError):
        next(fixture())

    assert forbid_connect == []


def test_the_read_only_full_cohort_module_is_left_alone() -> None:
    """The WP2.2 evidence tests take a different variable and are deliberately not guarded here.

    They open READ ONLY transactions against a database that must already hold the ingested
    cohort. Routing them through a mutation guard would imply they mutate something.
    """
    source = (TESTS_DIR / "test_wp2_2_geometry_integration.py").read_text(encoding="utf-8")

    assert "TOUCHLINE_FULL_COHORT_DB_URL" in source
    assert "conn.read_only = True" in source
    assert "from support.db_safety import" not in source
    assert db_safety.__name__ == "support.db_safety"
