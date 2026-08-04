"""Generate the WP2.3 locked split artifacts from the ingested full-cohort database.

One-shot re-lock tool: reads the match population read-only from the database named by
``TOUCHLINE_FULL_COHORT_DB_URL``, computes the canonical split assignment with
``touchline.modeling.splits``, and writes the committed artifacts:

- ``data/model/wp2_3_match_assignments.csv`` — match-level assignment, byte-pinned;
- ``data/model/wp2_3_split_manifest.json`` — rule metadata plus label-free counts and hashes
  (validated field-by-field by the full-cohort tests; not byte-pinned, because it carries
  ``generated_utc``).

The script never writes to the database and refuses to run without the environment variable.
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

from touchline.ingest.source import SOURCE_COMMIT
from touchline.modeling.splits import (
    CALIBRATION_SCOPE,
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

FULL_COHORT_DB_URL_VAR = "TOUCHLINE_FULL_COHORT_DB_URL"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def main() -> int:
    db_url = os.environ.get(FULL_COHORT_DB_URL_VAR)
    if not db_url:
        print(
            f"Refusing to generate the WP2.3 split artifacts: {FULL_COHORT_DB_URL_VAR} is not "
            "set. Point it at a local PostgreSQL that has been migrated and ingested.",
            file=sys.stderr,
        )
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

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CSV_PATH.write_text(csv_text, encoding="utf-8", newline="\n")
    csv_sha256 = _sha256_file(CSV_PATH)

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
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"wrote {CSV_PATH.relative_to(ROOT)} ({len(records)} match rows, sha256={csv_sha256})")
    print(f"wrote {MANIFEST_PATH.relative_to(ROOT)}")
    print("matches per split:", {k: v["matches"] for k, v in splits.items()})
    print("eligible shots per split:", {k: v["eligible_shots"] for k, v in splits.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
