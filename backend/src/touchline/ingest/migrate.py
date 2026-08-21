"""Apply Touchline's ordered, hand-written PostgreSQL migrations."""

from __future__ import annotations

import hashlib
import re
import sys
from dataclasses import dataclass
from importlib import resources

import psycopg

from touchline.config import (
    DirectDatabaseUrlRequiredError,
    MigrationDatabaseUrlInvalidError,
    MigrationDatabaseUrlRequiredError,
    MissingConfigurationError,
    RuntimeDatabaseUrlInvalidError,
    get_settings,
    migration_database_url,
    migration_uses_dedicated_url,
    require_direct_database_url,
)

MIGRATION_PACKAGE = "touchline.ingest.migrations"
MIGRATION_NAME = re.compile(r"^(?P<number>\d{4})_[a-z0-9_]+\.sql$")
MANAGED_TABLES = ("competitions", "teams", "players", "matches", "shots")

M0_COLUMNS = {
    ("competitions", "competition_id", "integer", False),
    ("competitions", "season_id", "integer", False),
    ("competitions", "competition_name", "text", False),
    ("competitions", "season_name", "text", False),
    ("competitions", "country_name", "text", True),
    ("teams", "team_id", "integer", False),
    ("teams", "team_name", "text", False),
    ("players", "player_id", "integer", False),
    ("players", "player_name", "text", False),
    ("matches", "match_id", "integer", False),
    ("matches", "competition_id", "integer", False),
    ("matches", "season_id", "integer", False),
    ("matches", "match_date", "date", True),
    ("matches", "kick_off", "text", True),
    ("matches", "home_team_id", "integer", False),
    ("matches", "away_team_id", "integer", False),
    ("matches", "home_score", "integer", True),
    ("matches", "away_score", "integer", True),
    ("matches", "competition_stage", "text", True),
    ("shots", "shot_id", "text", False),
    ("shots", "match_id", "integer", False),
    ("shots", "team_id", "integer", False),
    ("shots", "player_id", "integer", True),
    ("shots", "period", "integer", True),
    ("shots", "minute", "integer", True),
    ("shots", "second", "integer", True),
    ("shots", "location_x", "double precision", True),
    ("shots", "location_y", "double precision", True),
    ("shots", "outcome", "text", True),
    ("shots", "body_part", "text", True),
    ("shots", "technique", "text", True),
    ("shots", "shot_type", "text", True),
}
M0_PRIMARY_KEYS = {
    "competitions": ("competition_id", "season_id"),
    "teams": ("team_id",),
    "players": ("player_id",),
    "matches": ("match_id",),
    "shots": ("shot_id",),
}


class MigrationError(RuntimeError):
    """The migration history or packaged migration set is invalid."""


class MigrationDriftError(MigrationError):
    """An applied migration no longer matches its packaged SQL."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: str
    sql: str
    checksum: str


def read_migrations() -> tuple[Migration, ...]:
    """Read and validate the ordered SQL files shipped in the package."""
    root = resources.files(MIGRATION_PACKAGE)
    files = sorted(
        (item for item in root.iterdir() if item.name.endswith(".sql")),
        key=lambda item: item.name,
    )
    migrations: list[Migration] = []
    for expected_number, item in enumerate(files, start=1):
        match = MIGRATION_NAME.fullmatch(item.name)
        if match is None or int(match.group("number")) != expected_number:
            raise MigrationError(
                "migration files must be consecutively numbered from 0001; "
                f"found {item.name!r} at position {expected_number}"
            )
        sql_text = item.read_text(encoding="utf-8")
        canonical_sql = sql_text.replace("\r\n", "\n").replace("\r", "\n")
        migrations.append(
            Migration(
                version=item.name.removesuffix(".sql"),
                sql=sql_text,
                checksum=hashlib.sha256(canonical_sql.encode("utf-8")).hexdigest(),
            )
        )
    if not migrations:
        raise MigrationError("no packaged SQL migrations were found")
    return tuple(migrations)


def _validate_unversioned_m0_schema(conn: psycopg.Connection) -> None:
    """Accept only the exact known M0 shape before recording migration 0001."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = current_schema()
              AND table_type = 'BASE TABLE'
              AND table_name = ANY(%s)
            """,
            (list(MANAGED_TABLES),),
        )
        tables = {str(row[0]) for row in cur.fetchall()}
        if not tables:
            return
        if tables != set(MANAGED_TABLES):
            raise MigrationDriftError(
                "unversioned M0 schema does not match the expected managed table set"
            )

        cur.execute(
            """
            SELECT table_name, column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = ANY(%s)
            """,
            (list(MANAGED_TABLES),),
        )
        columns = {
            (str(table), str(column), str(data_type), str(nullable) == "YES")
            for table, column, data_type, nullable in cur.fetchall()
        }
        if columns != M0_COLUMNS:
            raise MigrationDriftError(
                "unversioned M0 schema does not match expected columns, types, or nullability"
            )

        cur.execute(
            """
            SELECT constraints.table_name, keys.column_name, keys.ordinal_position
            FROM information_schema.table_constraints AS constraints
            JOIN information_schema.key_column_usage AS keys
              ON keys.constraint_schema = constraints.constraint_schema
             AND keys.constraint_name = constraints.constraint_name
             AND keys.table_name = constraints.table_name
            WHERE constraints.table_schema = current_schema()
              AND constraints.constraint_type = 'PRIMARY KEY'
              AND constraints.table_name = ANY(%s)
            ORDER BY constraints.table_name, keys.ordinal_position
            """,
            (list(MANAGED_TABLES),),
        )
        primary_keys: dict[str, list[str]] = {}
        for table, column, _ in cur.fetchall():
            primary_keys.setdefault(str(table), []).append(str(column))
        actual_primary_keys = {table: tuple(columns) for table, columns in primary_keys.items()}
        if actual_primary_keys != M0_PRIMARY_KEYS:
            raise MigrationDriftError("unversioned M0 schema does not match expected primary keys")


def apply_migrations(conn: psycopg.Connection) -> tuple[str, ...]:
    """Apply pending migrations in order inside the caller-owned transaction.

    Returns the versions applied by this call. Re-running with the same packaged files is a no-op.
    Applied SQL is immutable: a checksum mismatch is reported rather than silently accepted.
    """
    migrations = read_migrations()
    by_version = {migration.version: migration for migration in migrations}

    with conn.cursor() as cur:
        cur.execute(
            "SELECT pg_advisory_xact_lock(hashtext(current_database()), hashtext(current_schema()))"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version    text PRIMARY KEY,
                checksum   text NOT NULL CHECK (checksum ~ '^[0-9a-f]{64}$'),
                applied_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute("LOCK TABLE schema_migrations IN EXCLUSIVE MODE")
        cur.execute("SELECT version, checksum FROM schema_migrations ORDER BY version")
        applied_rows = [(str(version), str(checksum)) for version, checksum in cur.fetchall()]

        if not applied_rows:
            _validate_unversioned_m0_schema(conn)

        applied_versions = [version for version, _ in applied_rows]
        removed = sorted(set(applied_versions) - set(by_version))
        if removed:
            raise MigrationDriftError(
                "applied migrations are missing from the package: " + ", ".join(removed)
            )
        packaged_versions = [migration.version for migration in migrations]
        if applied_versions != packaged_versions[: len(applied_versions)]:
            raise MigrationDriftError(
                "applied migrations must be an exact ordered prefix of packaged migrations"
            )
        for version, checksum in applied_rows:
            if checksum != by_version[version].checksum:
                raise MigrationDriftError(f"applied migration {version} has changed")

        newly_applied: list[str] = []
        for migration in migrations[len(applied_versions) :]:
            cur.execute(migration.sql)
            cur.execute(
                "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                (migration.version, migration.checksum),
            )
            newly_applied.append(migration.version)
    return tuple(newly_applied)


def main() -> int:
    """Apply pending migrations to the configured database."""
    try:
        settings = get_settings()
        db_url = migration_database_url(settings)
        require_direct_database_url(
            db_url,
            variable_name=(
                "TOUCHLINE_MIGRATION_DB_URL"
                if migration_uses_dedicated_url()
                else "TOUCHLINE_DB_URL"
            ),
        )
    except (
        DirectDatabaseUrlRequiredError,
        MigrationDatabaseUrlInvalidError,
        MigrationDatabaseUrlRequiredError,
        MissingConfigurationError,
        RuntimeDatabaseUrlInvalidError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    try:
        with psycopg.connect(str(db_url)) as conn:
            applied = apply_migrations(conn)
    except psycopg.Error as exc:
        # Driver messages can include a DSN or provider detail. The command is often run in CI or
        # a platform pre-deploy log, so expose only the exception class and keep credentials out.
        print(f"Migration failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    if applied:
        print("Applied migrations: " + ", ".join(applied))
    else:
        print("Database schema is current; no migrations applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
