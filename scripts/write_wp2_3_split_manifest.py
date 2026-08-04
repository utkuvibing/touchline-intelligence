"""Generate the WP2.3 locked split artifacts from the ingested full-cohort database.

One-shot re-lock tool: reads the match population read-only from the database named by
``TOUCHLINE_FULL_COHORT_DB_URL``, computes the canonical split assignment with
``touchline.modeling.splits``, and writes the committed artifacts:

- ``data/model/wp2_3_match_assignments.csv`` — match-level assignment, byte-pinned;
- ``data/model/wp2_3_split_manifest.json`` — rule metadata plus label-free counts and hashes
  (validated field-by-field by the full-cohort tests; not byte-pinned, because it carries
  ``generated_utc``).

The generation is **failure-safe**: both outputs are rendered and validated fully in memory, then
written to temporary files, and the committed artifacts are replaced only after both temporary
files are on disk. A failed validation or a crash leaves the previous artifacts untouched.

The script never writes to the database. Because it rewrites locked repository artifacts, it
refuses to read from a non-local PostgreSQL — the same classification the ingestion guard uses —
so a run pointed at a deployment cannot silently regenerate evidence from a different population.
``TOUCHLINE_ALLOW_REMOTE_WRITES`` naming the exact target is the deliberate per-run escape hatch,
as for ``poe ingest``.

The exact invocation is recorded in ``reports/wp2.3-split-evidence.md``; afterwards this script
exists for re-lock audits only — a re-lock is a declared contract change, not a routine run.

    TOUCHLINE_FULL_COHORT_DB_URL='postgresql://touchline:localdev@localhost:5433/touchline' \
        uv run python scripts/write_wp2_3_split_manifest.py
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path

import psycopg
from pydantic import PostgresDsn, TypeAdapter

from touchline.config import (
    REMOTE_WRITE_OVERRIDE_VAR,
    RemoteWriteBlockedError,
    is_local_write_target,
    write_target,
)
from touchline.ingest.source import SOURCE_COMMIT
from touchline.modeling.splits import (
    CALIBRATION_SCOPE,
    CSV_HEADER,
    DEVELOPMENT_SCOPE,
    HOLDOUT_SCOPE,
    N_FOLDS,
    MatchRecord,
    assign_tournament_split,
    manifest_summaries,
    render_match_assignments_csv,
)

ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "backend" / "sql" / "wp2_3"
COHORT_SQL_PATH = ROOT / "backend" / "sql" / "wp2_1" / "01_model_shot_cohort.sql"
OUT_DIR = ROOT / "data" / "model"
CSV_PATH = OUT_DIR / "wp2_3_match_assignments.csv"
MANIFEST_PATH = OUT_DIR / "wp2_3_split_manifest.json"
CSV_TMP = OUT_DIR / "wp2_3_match_assignments.csv.tmp"
MANIFEST_TMP = OUT_DIR / "wp2_3_split_manifest.json.tmp"

FULL_COHORT_DB_URL_VAR = "TOUCHLINE_FULL_COHORT_DB_URL"

#: The measured cohort anchors. A re-lock against a different population is a declared contract
#: change, so the generator refuses rather than silently re-pinning new evidence.
EXPECTED_MATCHES = 230
EXPECTED_ELIGIBLE_SHOTS = 5606

_DSN = TypeAdapter(PostgresDsn)


def _require_local_full_cohort(db_url: str) -> None:
    """Refuse to generate locked artifacts from a non-local database.

    Classification comes from the shared production primitives so this guard cannot drift from
    the ingestion guard's notion of "local". The deliberate per-target override for ingestion is
    honored here too, because the same reasoning applies: a run that rewrites locked artifacts
    against a deployment is either a mistake or a decision, and the variable makes the decision
    explicit per run.
    """
    parsed = _DSN.validate_python(db_url)
    if is_local_write_target(parsed):
        return
    target = write_target(parsed)
    if os.environ.get(REMOTE_WRITE_OVERRIDE_VAR, "").strip() == target:
        return
    raise RemoteWriteBlockedError(
        f"Refusing to generate the WP2.3 split artifacts from the non-local database {target}.\n"
        f"This command rewrites locked repository artifacts, and {FULL_COHORT_DB_URL_VAR} does "
        f"not point at a local PostgreSQL instance. The deployed database holds a different "
        f"population and would silently produce different evidence.\n"
        f"Local development should use the Docker Compose database on localhost:5433 (see "
        f"infra/docker-compose.yml). If generating from {target} is genuinely intended, name it "
        f"for this one run:\n"
        f"    {REMOTE_WRITE_OVERRIDE_VAR}='{target}' uv run python scripts/"
        f"write_wp2_3_split_manifest.py\n"
        f"The variable must equal that target exactly; a generic value such as '1' or 'true' is "
        f"not accepted."
    )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _validate_rendered(
    csv_text: str,
    manifest_text: str,
    records: list[MatchRecord],
    eligible_shots: dict[int, int],
    csv_sha256: str,
) -> None:
    """Validate both outputs in memory before anything touches the artifacts directory."""
    if len(records) != EXPECTED_MATCHES:
        raise AssertionError(
            f"expected {EXPECTED_MATCHES} matches, got {len(records)}; re-locking against a "
            "different population is a declared contract change"
        )
    if sum(eligible_shots.values()) != EXPECTED_ELIGIBLE_SHOTS:
        raise AssertionError(
            f"expected {EXPECTED_ELIGIBLE_SHOTS} eligible shots, got "
            f"{sum(eligible_shots.values())}; re-locking against a different population is a "
            "declared contract change"
        )

    lines = csv_text.splitlines()
    if not lines or lines[0] != CSV_HEADER:
        raise AssertionError("rendered CSV header does not match the pinned header")
    if len(lines) != EXPECTED_MATCHES + 1:
        raise AssertionError(
            f"rendered CSV has {len(lines) - 1} data rows, expected {EXPECTED_MATCHES}"
        )

    manifest = json.loads(manifest_text)
    if manifest["version"] != 1:
        raise AssertionError("manifest version is not 1")
    if manifest["attribution"] != "Data provided by StatsBomb.":
        raise AssertionError("manifest attribution is not the required StatsBomb line")
    if manifest["source_commit"] != SOURCE_COMMIT:
        raise AssertionError("manifest source_commit does not match the pinned source revision")
    if manifest["assignments_sha256"] != csv_sha256:
        raise AssertionError("manifest assignment hash does not match the rendered CSV")
    if manifest["cohort_sql_sha256"] != _sha256_file(COHORT_SQL_PATH):
        raise AssertionError("manifest cohort SQL hash does not match the WP2.1 cohort query")
    dt.datetime.fromisoformat(str(manifest["generated_utc"]))
    for split in ("development", "calibration", "holdout"):
        dt.date.fromisoformat(str(manifest["splits"][split]["date_first"]))
        dt.date.fromisoformat(str(manifest["splits"][split]["date_last"]))
    for fold in range(N_FOLDS):
        dt.date.fromisoformat(str(manifest["folds"][str(fold)]["date_first"]))
        dt.date.fromisoformat(str(manifest["folds"][str(fold)]["date_last"]))


def main() -> int:
    db_url = os.environ.get(FULL_COHORT_DB_URL_VAR)
    if not db_url:
        print(
            f"Refusing to generate the WP2.3 split artifacts: {FULL_COHORT_DB_URL_VAR} is not "
            "set. Point it at a local PostgreSQL that has been migrated and ingested.",
            file=sys.stderr,
        )
        return 1
    try:
        _require_local_full_cohort(db_url)
    except RemoteWriteBlockedError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    sql = (SQL_DIR / "01_split_match_population.sql").read_text(encoding="utf-8")
    with psycopg.connect(db_url, connect_timeout=15) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = list(cur.fetchall())
        conn.rollback()

    records = [
        MatchRecord(
            match_id=int(row[0]),
            competition_id=int(row[1]),
            season_id=int(row[2]),
            match_date=row[3] if isinstance(row[3], dt.date) else None,
        )
        for row in rows
    ]
    eligible_shots = {int(row[0]): int(row[4]) for row in rows}

    plan = assign_tournament_split(records)
    csv_text = render_match_assignments_csv(plan, records)
    splits, folds = manifest_summaries(plan, records, eligible_shots)
    csv_sha256 = _sha256_bytes(csv_text.encode("utf-8"))

    manifest = {
        "split_name": "wp2_3_tournament_split",
        "version": 1,
        "source_commit": SOURCE_COMMIT,
        "cohort_sql_sha256": _sha256_file(COHORT_SQL_PATH),
        "generated_utc": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rule": {
            "holdout_scope": list(HOLDOUT_SCOPE),
            "calibration_scope": list(CALIBRATION_SCOPE),
            "development_scopes": sorted(list(scope) for scope in DEVELOPMENT_SCOPE),
            "n_folds": N_FOLDS,
            "fold_assignment": (
                "development matches sorted by (match_date, match_id); fold = index % n_folds"
            ),
            "fold_semantics": (
                "deterministic match-grouped folds; not temporal; not forward-chaining; "
                "chronology applies only between top-level splits"
            ),
        },
        "splits": splits,
        "folds": folds,
        "assignments_sha256": csv_sha256,
        "attribution": "Data provided by StatsBomb.",
    }
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    _validate_rendered(csv_text, manifest_text, records, eligible_shots, csv_sha256)

    # Failure-safe replacement: write both temporary files first, and only then swap them into
    # the committed paths. A failure at any point before the swaps leaves the previous artifacts
    # untouched.
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        CSV_TMP.write_text(csv_text, encoding="utf-8", newline="\n")
        MANIFEST_TMP.write_text(manifest_text, encoding="utf-8")
        os.replace(CSV_TMP, CSV_PATH)
        os.replace(MANIFEST_TMP, MANIFEST_PATH)
    finally:
        for tmp in (CSV_TMP, MANIFEST_TMP):
            if tmp.exists():
                tmp.unlink()

    print(f"wrote {CSV_PATH.relative_to(ROOT)} ({len(records)} match rows, sha256={csv_sha256})")
    print(f"wrote {MANIFEST_PATH.relative_to(ROOT)}")
    print("matches per split:", {k: v["matches"] for k, v in splits.items()})
    print("eligible shots per split:", {k: v["eligible_shots"] for k, v in splits.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
