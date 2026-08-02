"""Database-endpoint policy at migration and ingestion command boundaries."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from touchline.config import Settings, require_direct_database_url
from touchline.ingest import cli, migrate

POOLED_DSN = (
    "postgresql://operator:super-secret@"
    "ep-touchline-pooler.eu-central-1.aws.neon.tech/touchline?sslmode=require"
)
DIRECT_DSN = (
    "postgresql://operator:super-secret@"
    "ep-touchline.eu-central-1.aws.neon.tech/touchline?sslmode=require"
)


def _unexpected_work(*args: object, **kwargs: object) -> None:
    del args, kwargs
    pytest.fail("the pooled-URL policy must run before database or source work")


def test_pooled_url_remains_valid_api_configuration() -> None:
    """The endpoint policy belongs to operator commands, not shared application settings."""
    settings = Settings(_env_file=None, db_url=POOLED_DSN)  # type: ignore[call-arg, arg-type]
    assert "-pooler" in settings.db_url_str


def test_direct_neon_url_is_accepted_for_operator_commands() -> None:
    settings = Settings(_env_file=None, db_url=DIRECT_DSN)  # type: ignore[call-arg, arg-type]
    require_direct_database_url(settings.db_url)


@pytest.mark.parametrize(
    ("command", "patch_source"),
    [
        pytest.param(migrate.main, False, id="migration"),
        pytest.param(lambda: cli.main([]), True, id="ingestion"),
    ],
)
def test_operator_commands_reject_neon_pooler_before_any_work(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: Callable[[], int],
    patch_source: bool,
) -> None:
    monkeypatch.setenv("TOUCHLINE_DB_URL", POOLED_DSN)
    monkeypatch.setattr("psycopg.connect", _unexpected_work)
    if patch_source:
        monkeypatch.setattr(cli, "StatsBombSource", _unexpected_work)

    assert command() == 1

    error = capsys.readouterr().err
    assert "direct Neon URL" in error
    assert "-pooler" in error
    assert "super-secret" not in error
    assert POOLED_DSN not in error
