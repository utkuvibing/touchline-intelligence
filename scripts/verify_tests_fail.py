"""Verify that the test suite actually protects what it claims to.

A green suite proves the tests pass, not that they would fail if the behaviour broke. This script
introduces one deliberate break per protected contract, runs the relevant tests, asserts they fail,
and restores the file.

Run with a clean working tree:

    uv run python scripts/verify_tests_fail.py

It has already earned its place three times. It found that the /health liveness test passed even
when /health was made to call the database (the failure was invisible from the response body), that
the /ready secret-leak test passed for the wrong reason because its substring blocklist missed the
actual driver error, and that the read-only test configured a separate transaction instead of
observing the production query's transaction. All three tests were rewritten.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

HEALTH_ANCHOR = "    settings = get_settings()\n    return Health("
HEALTH_BROKEN = (
    "    settings = get_settings()\n"
    "    _check_database(settings)  # DELIBERATE BREAK\n"
    "    return Health("
)

DB_URL_ANCHOR = "    db_url: PostgresDsn = Field(\n        description="
DB_URL_BROKEN = (
    "    db_url: PostgresDsn = Field(\n"
    '        default="postgresql://a:b@localhost:5432/c",  # DELIBERATE BREAK\n'
    "        description="
)

OPS_TESTS = "uv run pytest backend/tests/test_ops_endpoints.py -q"
CONFIG_TESTS = "uv run pytest backend/tests/test_config.py -q"
PARSE_TESTS = "uv run pytest backend/tests/test_ingest_parse.py -q"
# Database-backed mutations only prove anything when TOUCHLINE_DB_URL is set, and the hermeticity
# break is invisible unless a TOUCHLINE_* variable is exported. The script reports MISSED otherwise,
# which is honest: an unrun test protects nothing.
LOAD_TESTS = "uv run pytest backend/tests/test_ingest_load_integration.py -q"
BASELINE_TESTS = "uv run pytest backend/tests/test_baseline_integration.py -q"
SHOTS_TESTS = "uv run pytest backend/tests/test_shots_integration.py -q"
MIGRATION_TESTS = "uv run pytest backend/tests/test_migrations_integration.py -q"
FRONTEND_TESTS = "npm test"


@dataclass(frozen=True)
class Break:
    """One deliberate defect and the command that must notice it."""

    contract: str
    path: Path
    anchor: str
    replacement: str
    command: str
    cwd: Path


BREAKS: list[Break] = [
    Break(
        contract="/health must not touch the database (liveness)",
        path=ROOT / "backend/src/touchline/main.py",
        anchor=HEALTH_ANCHOR,
        replacement=HEALTH_BROKEN,
        command=OPS_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="db_url must have no default (fail fast on misconfiguration)",
        path=ROOT / "backend/src/touchline/config.py",
        anchor=DB_URL_ANCHOR,
        replacement=DB_URL_BROKEN,
        command=CONFIG_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="/ready must report an exception class name only (no secret leak)",
        path=ROOT / "backend/src/touchline/main.py",
        anchor="        return False, type(exc).__name__",
        replacement="        return False, str(exc)  # DELIBERATE BREAK",
        command=OPS_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="the 'no evaluated model' notice must stay while M0 has no model",
        path=FRONTEND / "components/HomeView.tsx",
        anchor='        <p role="note">{PROVISIONAL_NOTICE}</p>',
        replacement="        {/* DELIBERATE BREAK */}",
        command=FRONTEND_TESTS,
        cwd=FRONTEND,
    ),
    Break(
        contract="StatsBomb attribution must stay (licence obligation)",
        path=FRONTEND / "components/HomeView.tsx",
        anchor="          Data provided by StatsBomb.",
        replacement="          DELIBERATE BREAK.",
        command=FRONTEND_TESTS,
        cwd=FRONTEND,
    ),
    Break(
        contract="an absent shot location must stay NULL, never be coerced to a real coordinate",
        path=ROOT / "backend/src/touchline/ingest/parse.py",
        anchor="    if v is None:\n        return None, None",
        replacement="    if v is None:\n        return 0.0, 0.0  # DELIBERATE BREAK",
        command=PARSE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="a malformed location must raise, not be silently treated as absent",
        path=ROOT / "backend/src/touchline/ingest/parse.py",
        anchor='        raise ParseError(f"expected location to be exactly [x, y], got {v!r}")',
        replacement="        return None, None  # DELIBERATE BREAK",
        command=PARSE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="a location must have exactly two elements, not merely at least two",
        path=ROOT / "backend/src/touchline/ingest/parse.py",
        anchor=(
            "    if (\n"
            "        not isinstance(v, list)\n"
            "        or len(v) != 2\n"
            "        or not all(not isinstance(x, bool) and "
            "isinstance(x, int | float) for x in v)\n"
            "    ):"
        ),
        replacement=(
            "    if (\n"
            "        not isinstance(v, list)\n"
            "        or len(v) < 2  # DELIBERATE BREAK\n"
            "        or not all(not isinstance(x, bool) and "
            "isinstance(x, int | float) for x in v)\n"
            "    ):"
        ),
        command=PARSE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="optional event integer fields must reject coercible wrong types",
        path=ROOT / "backend/src/touchline/ingest/parse.py",
        anchor=(
            "def _optional_int(obj: dict[str, Any], key: str, context: str) -> int | None:\n"
            "    value = obj.get(key)\n"
            "    if value is None:\n"
            "        return None\n"
            "    if isinstance(value, bool) or not isinstance(value, int):\n"
            '        raise ParseError(f"expected {context}.{key} to be an integer, got {value!r}")'
        ),
        replacement=(
            "def _optional_int(obj: dict[str, Any], key: str, context: str) -> int | None:\n"
            "    value = obj.get(key)\n"
            "    if value is None:\n"
            "        return None\n"
            "    if False:  # DELIBERATE BREAK\n"
            '        raise ParseError(f"expected {context}.{key} to be an integer, got {value!r}")'
        ),
        command=PARSE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="optional event numeric fields must reject coercible strings",
        path=ROOT / "backend/src/touchline/ingest/parse.py",
        anchor=(
            "    if isinstance(value, bool) or not isinstance(value, int | float):\n"
            '        raise ParseError(f"expected {context}.{key} to be numeric, got {value!r}")'
        ),
        replacement=(
            "    if False:  # DELIBERATE BREAK\n"
            '        raise ParseError(f"expected {context}.{key} to be numeric, got {value!r}")'
        ),
        command=PARSE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="optional event and shot booleans must reject truthy non-booleans",
        path=ROOT / "backend/src/touchline/ingest/parse.py",
        anchor=(
            "    if not isinstance(value, bool):\n"
            '        raise ParseError(f"expected {context}.{key} to be boolean, got {value!r}")'
        ),
        replacement=(
            "    if False:  # DELIBERATE BREAK\n"
            '        raise ParseError(f"expected {context}.{key} to be boolean, got {value!r}")'
        ),
        command=PARSE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="optional event string fields must reject non-string values",
        path=ROOT / "backend/src/touchline/ingest/parse.py",
        anchor=(
            "def _optional_str(obj: dict[str, Any], key: str, context: str) -> str | None:\n"
            "    value = obj.get(key)\n"
            "    if value is None:\n"
            "        return None\n"
            "    if not isinstance(value, str):\n"
            '        raise ParseError(f"expected {context}.{key} to be a string, got {value!r}")'
        ),
        replacement=(
            "def _optional_str(obj: dict[str, Any], key: str, context: str) -> str | None:\n"
            "    value = obj.get(key)\n"
            "    if value is None:\n"
            "        return None\n"
            "    if False:  # DELIBERATE BREAK\n"
            '        raise ParseError(f"expected {context}.{key} to be a string, got {value!r}")'
        ),
        command=PARSE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="required lineup integer fields must reject coercible values",
        path=ROOT / "backend/src/touchline/ingest/parse.py",
        anchor=(
            "def _required_int(obj: Any, key: str, context: str) -> int:\n"
            "    value = _require(obj, key, context)\n"
            "    if isinstance(value, bool) or not isinstance(value, int):\n"
            '        raise ParseError(f"expected {context}.{key} to be an integer, got {value!r}")'
        ),
        replacement=(
            "def _required_int(obj: Any, key: str, context: str) -> int:\n"
            "    value = _require(obj, key, context)\n"
            "    if False:  # DELIBERATE BREAK\n"
            '        raise ParseError(f"expected {context}.{key} to be an integer, got {value!r}")'
        ),
        command=PARSE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="required lineup string fields must reject coercible values",
        path=ROOT / "backend/src/touchline/ingest/parse.py",
        anchor=(
            "def _required_str(obj: Any, key: str, context: str) -> str:\n"
            "    value = _require(obj, key, context)\n"
            "    if not isinstance(value, str):\n"
            '        raise ParseError(f"expected {context}.{key} to be a string, got {value!r}")'
        ),
        replacement=(
            "def _required_str(obj: Any, key: str, context: str) -> str:\n"
            "    value = _require(obj, key, context)\n"
            "    if False:  # DELIBERATE BREAK\n"
            '        raise ParseError(f"expected {context}.{key} to be a string, got {value!r}")'
        ),
        command=PARSE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="lineup members must remain a list container",
        path=ROOT / "backend/src/touchline/ingest/parse.py",
        anchor=(
            "        if not isinstance(raw_lineup, list):\n"
            '            raise ParseError(f"expected {team_context}.lineup to be a list, '
            'got {raw_lineup!r}")'
        ),
        replacement=(
            "        if not isinstance(raw_lineup, list):\n"
            "            raw_lineup = []  # DELIBERATE BREAK"
        ),
        command=PARSE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="lineup positions must remain a list container",
        path=ROOT / "backend/src/touchline/ingest/parse.py",
        anchor=(
            "            if not isinstance(positions, list):\n"
            '                raise ParseError("expected lineup member.positions to be a list")'
        ),
        replacement=(
            "            if not isinstance(positions, list):\n"
            "                positions = []  # DELIBERATE BREAK"
        ),
        command=PARSE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="lineup cards must remain a list container",
        path=ROOT / "backend/src/touchline/ingest/parse.py",
        anchor=(
            "            if not isinstance(cards, list):\n"
            '                raise ParseError("expected lineup member.cards to be a list")'
        ),
        replacement=(
            "            if not isinstance(cards, list):\n"
            "                cards = []  # DELIBERATE BREAK"
        ),
        command=PARSE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="config tests must be hermetic against the real environment",
        path=ROOT / "backend/tests/test_config.py",
        anchor="        monkeypatch.delenv(name, raising=False)",
        replacement="        pass  # DELIBERATE BREAK",
        command=CONFIG_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="the loader must not commit - the caller owns the transaction",
        path=ROOT / "backend/src/touchline/ingest/load.py",
        anchor="    return LoadCounts(**counts)",
        replacement="    conn.commit()  # DELIBERATE BREAK\n    return LoadCounts(**counts)",
        command=LOAD_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="the base rate must exclude penalties",
        path=ROOT / "backend/src/touchline/baseline.py",
        anchor="    \"AND s.shot_type_name <> 'Penalty' \"",
        replacement='    "AND true "  # DELIBERATE BREAK',
        command=BASELINE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="fetch_shots must make its own transaction read-only",
        path=ROOT / "backend/src/touchline/shots.py",
        anchor='cur.execute("SET TRANSACTION READ ONLY")',
        replacement="pass  # DELIBERATE BREAK",
        command=SHOTS_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="a map showing fewer shots than the API reports must disclose the shortfall",
        path=FRONTEND / "components/HomeView.tsx",
        anchor="            {missing > 0 && (",
        replacement="            {false && (  /* DELIBERATE BREAK */",
        command=FRONTEND_TESTS,
        cwd=FRONTEND,
    ),
    Break(
        contract="an empty database must raise, not report a conversion rate of zero",
        path=ROOT / "backend/src/touchline/baseline.py",
        anchor="    if shots == 0:\n        raise NoDataError(",
        replacement="    if False:  # DELIBERATE BREAK\n        raise NoDataError(",
        command=BASELINE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="migrations must be applied in their declared order",
        path=ROOT / "backend/src/touchline/ingest/migrate.py",
        anchor="    migrations = read_migrations()",
        replacement=("    migrations = tuple(reversed(read_migrations()))  # DELIBERATE BREAK"),
        command=MIGRATION_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="applied migration checksum drift must be rejected",
        path=ROOT / "backend/src/touchline/ingest/migrate.py",
        anchor="            if checksum != by_version[version].checksum:",
        replacement="            if False:  # DELIBERATE BREAK",
        command=MIGRATION_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="applied migration history must be an exact ordered prefix",
        path=ROOT / "backend/src/touchline/ingest/migrate.py",
        anchor="        if applied_versions != packaged_versions[: len(applied_versions)]:",
        replacement="        if False:  # DELIBERATE BREAK",
        command=MIGRATION_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="an unversioned M0 schema must match its known physical signature",
        path=ROOT / "backend/src/touchline/ingest/migrate.py",
        anchor="            _validate_unversioned_m0_schema(conn)",
        replacement="            pass  # DELIBERATE BREAK",
        command=MIGRATION_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="the destructive rebuild must use the ordered migrations",
        path=ROOT / "backend/src/touchline/ingest/load.py",
        anchor="    apply_migrations(conn)",
        replacement="    return  # DELIBERATE BREAK",
        command=LOAD_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="a shot must reference an existing event",
        path=ROOT / "backend/src/touchline/ingest/migrations/0005_event_and_lineup_constraints.sql",
        anchor=(
            "    ADD CONSTRAINT shots_event_fk FOREIGN KEY (event_id, event_type_name)\n"
            "        REFERENCES events (event_id, event_type_name),"
        ),
        replacement=(
            "    ADD CONSTRAINT shots_event_fk CHECK (event_id IS NOT NULL), -- DELIBERATE BREAK"
        ),
        command=MIGRATION_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="an event must reference an existing match",
        path=ROOT / "backend/src/touchline/ingest/migrations/0005_event_and_lineup_constraints.sql",
        anchor=(
            "    ADD CONSTRAINT events_match_fk FOREIGN KEY (match_id) "
            "REFERENCES matches (match_id),"
        ),
        replacement=(
            "    ADD CONSTRAINT events_match_fk CHECK (match_id > 0), -- DELIBERATE BREAK"
        ),
        command=MIGRATION_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="event x coordinates must remain within the StatsBomb pitch",
        path=ROOT / "backend/src/touchline/ingest/migrations/0005_event_and_lineup_constraints.sql",
        anchor=(
            "    ADD CONSTRAINT events_location_x_bounds "
            "CHECK (location_x IS NULL OR location_x BETWEEN 0.0 AND 120.0),"
        ),
        replacement=(
            "    ADD CONSTRAINT events_location_x_bounds "
            "CHECK (location_x IS NULL OR location_x BETWEEN -1000.0 AND 1000.0), "
            "-- DELIBERATE BREAK"
        ),
        command=MIGRATION_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="event y coordinates must remain within the StatsBomb pitch",
        path=ROOT / "backend/src/touchline/ingest/migrations/0005_event_and_lineup_constraints.sql",
        anchor=(
            "    ADD CONSTRAINT events_location_y_bounds "
            "CHECK (location_y IS NULL OR location_y BETWEEN 0.0 AND 80.0),"
        ),
        replacement=(
            "    ADD CONSTRAINT events_location_y_bounds "
            "CHECK (location_y IS NULL OR location_y BETWEEN -1000.0 AND 1000.0), "
            "-- DELIBERATE BREAK"
        ),
        command=MIGRATION_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="provider xG must be removed recursively before JSONB persistence",
        path=ROOT / "backend/src/touchline/ingest/parse.py",
        anchor=(
            '        return {k: _strip_xg(v) for k, v in value.items() if k != "statsbomb_xg"}'
        ),
        replacement=(
            "        return {k: _strip_xg(v) for k, v in value.items()} # DELIBERATE BREAK"
        ),
        command=PARSE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="lineup positions must preserve one-based source order",
        path=ROOT / "backend/src/touchline/ingest/parse.py",
        anchor="            for i, p in enumerate(positions, start=1):",
        replacement=("            for i, p in enumerate(positions, start=0):  # DELIBERATE BREAK"),
        command=PARSE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="lineup cards must preserve one-based source order",
        path=ROOT / "backend/src/touchline/ingest/parse.py",
        anchor="            for i, c in enumerate(cards, start=1):",
        replacement=("            for i, c in enumerate(cards, start=0):  # DELIBERATE BREAK"),
        command=PARSE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="full fixture ingestion must load every generic event",
        path=ROOT / "backend/src/touchline/ingest/load.py",
        anchor="        for r in events\n    ]",
        replacement="        for r in events if r.type_name == 'Shot'  # DELIBERATE BREAK\n    ]",
        command=LOAD_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="event indexes must be unique within a match",
        path=ROOT / "backend/src/touchline/ingest/migrations/0005_event_and_lineup_constraints.sql",
        anchor="    ADD CONSTRAINT events_match_index_unique UNIQUE (match_id, event_index),",
        replacement="    -- DELIBERATE BREAK: event index uniqueness removed",
        command=MIGRATION_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="directed event relations must reference a source event in the same match",
        path=ROOT / "backend/src/touchline/ingest/migrations/0005_event_and_lineup_constraints.sql",
        anchor=(
            "    ADD CONSTRAINT event_relations_source_event_fk "
            "FOREIGN KEY (match_id, source_event_id)\n"
            "        REFERENCES events (match_id, event_id),"
        ),
        replacement="    -- DELIBERATE BREAK: source relation foreign key removed",
        command=MIGRATION_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="JSONB must reject provider xG even if parser protection regresses",
        path=ROOT / "backend/src/touchline/ingest/migrations/0005_event_and_lineup_constraints.sql",
        anchor=(
            "    ADD CONSTRAINT events_no_provider_xg\n"
            "        CHECK (type_data IS NULL OR NOT "
            "jsonb_path_exists(type_data, '$.**.statsbomb_xg'));"
        ),
        replacement=("    ADD CONSTRAINT events_no_provider_xg CHECK (true); -- DELIBERATE BREAK"),
        command=MIGRATION_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="shot details may attach only to events whose type is Shot",
        path=ROOT / "backend/src/touchline/ingest/migrations/0005_event_and_lineup_constraints.sql",
        anchor=(
            "    ADD CONSTRAINT shots_event_fk FOREIGN KEY (event_id, event_type_name)\n"
            "        REFERENCES events (event_id, event_type_name),"
        ),
        replacement=(
            "    ADD CONSTRAINT shots_event_fk FOREIGN KEY (event_id) "
            "REFERENCES events (event_id), -- DELIBERATE BREAK"
        ),
        command=MIGRATION_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="shot freeze-frame actors must reference a typed shot detail",
        path=ROOT / "backend/src/touchline/ingest/migrations/0005_event_and_lineup_constraints.sql",
        anchor=(
            "    ADD CONSTRAINT shot_freeze_frame_players_shot_fk FOREIGN KEY (event_id)\n"
            "        REFERENCES shots (event_id),"
        ),
        replacement=(
            "    ADD CONSTRAINT shot_freeze_frame_players_shot_fk FOREIGN KEY (event_id)\n"
            "        REFERENCES events (event_id), -- DELIBERATE BREAK"
        ),
        command=MIGRATION_TESTS,
        cwd=ROOT,
    ),
]


def _tests_fail(command: str, cwd: Path) -> bool:
    """Run a test command and report whether it failed, which is the desired outcome here."""
    # shell=True is safe here: every command is a fixed literal defined above in this file,
    # with no interpolation of external input.
    result = subprocess.run(
        command,
        cwd=cwd,
        shell=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode != 0


def check(defect: Break) -> bool:
    """Apply one break, run its tests, restore the file. True when the break was caught."""
    original = defect.path.read_text(encoding="utf-8")
    occurrences = original.count(defect.anchor)
    if occurrences != 1:
        print(
            f"[MISSED] mutation anchor matched {occurrences} times; expected exactly once: "
            f"{defect.contract}"
        )
        return False

    mutated = original.replace(defect.anchor, defect.replacement, 1)
    if defect.path.suffix == ".py":
        try:
            compile(mutated, str(defect.path), "exec")
        except SyntaxError as exc:
            print(f"[MISSED] mutation produced invalid Python: {defect.contract}: {exc.msg}")
            return False

    defect.path.write_text(mutated, encoding="utf-8")
    try:
        caught = _tests_fail(defect.command, defect.cwd)
    finally:
        defect.path.write_text(original, encoding="utf-8")

    print(f"[{'CAUGHT' if caught else 'MISSED'}] {defect.contract}")
    return caught


def main() -> int:
    results = [check(defect) for defect in BREAKS]
    caught = results.count(True)
    missed = results.count(False)
    print(f"\nMutation totals: {caught} CAUGHT, {missed} MISSED, 0 SKIP")
    if all(results):
        print(f"\nAll {len(results)} contracts are genuinely protected. Files restored.")
        return 0
    print(f"\n{missed} of {len(results)} breaks went unnoticed. Files restored.")
    print("A test that does not fail here is not protecting anything.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
