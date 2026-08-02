"""CLI for the independent, read-only WP1.4 quality report."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg

from touchline.config import MissingConfigurationError, get_settings
from touchline.ingest.cli import SourceCounts
from touchline.ingest.run import CORE_COHORT
from touchline.ingest.source import SOURCE_COMMIT
from touchline.quality import inspect, render_text


def _scope(value: str) -> tuple[int, int]:
    try:
        competition, season = value.split("/", maxsplit=1)
        return int(competition), int(season)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("scope must be COMPETITION_ID/SEASON_ID") from exc


def _latest_matching_manifest(
    conn: psycopg.Connection, scope: tuple[tuple[int, int], ...]
) -> tuple[str, SourceCounts]:
    """Get measured source counts only from a successful manifest for this exact scope."""
    wanted = set(scope)
    if len(wanted) != len(scope):
        raise RuntimeError("quality scope must not repeat a competition-season")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT run_id::text, attempted_counts FROM ingestion_runs "
            "WHERE status = 'succeeded' AND source_commit = %s ORDER BY finished_at DESC",
            (SOURCE_COMMIT,),
        )
        rows = cur.fetchall()
        for run_id, attempted_counts in rows:
            cur.execute(
                "SELECT competition_id, season_id FROM ingestion_run_scopes WHERE run_id = %s",
                (run_id,),
            )
            persisted_scope = {(int(row[0]), int(row[1])) for row in cur.fetchall()}
            if persisted_scope == wanted and isinstance(attempted_counts, dict):
                return str(run_id), SourceCounts(**attempted_counts)
    raise RuntimeError("no successful manifest matches the requested source commit and exact scope")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit a loaded Touchline source scope without writing."
    )
    parser.add_argument(
        "--scope", action="append", type=_scope, help="repeatable competition/season"
    )
    parser.add_argument("--json-out", type=Path, default=Path("reports/wp1.4-core-cohort.json"))
    parser.add_argument("--text-out", type=Path, default=Path("reports/wp1.4-core-cohort.txt"))
    args = parser.parse_args(argv)
    scope = tuple(args.scope) if args.scope else CORE_COHORT
    try:
        settings = get_settings()
        with psycopg.connect(settings.db_url_str) as conn:
            run_id, source_counts = _latest_matching_manifest(conn, scope)
        with psycopg.connect(settings.db_url_str) as conn:
            report = inspect(conn, scope, source_counts, manifest_run_id=run_id)
    except (MissingConfigurationError, psycopg.Error, OSError, RuntimeError) as exc:
        print(f"quality report could not run: {exc}", file=sys.stderr)
        return 1
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.text_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(report.to_json(), encoding="utf-8")
    args.text_out.write_text(render_text(report), encoding="utf-8")
    print(render_text(report), end="")
    print(f"Machine report: {args.json_out}")
    print(f"Human report: {args.text_out}")
    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
