"""WP2.4 caller-check: the pinned WP2.3 artifacts are canonical LF and hash to the manifest.

This is the guard that turns the WP2.4 locked-artifact integrity fix into a contract. It is a plain
unit test with no database and no network, so it runs on every CI platform. It asserts three things
that, together, keep the WP2.3 split artifacts reproducible:

1. ``core.autocrlf`` or a developer's editor cannot silently rewrite the pinned CSV/SQL to CRLF:
   ``.gitattributes`` forces ``eol=lf`` for ``*.csv``, ``*.sql`` and ``*.json``, and the hash checks
   below compare against the canonical LF bytes, failing loudly if a ``\\r`` ever sneaks in.
2. The working-tree assignment CSV is byte-pinned: raw bytes are canonical LF and their SHA-256
   equals the value the split manifest records.
3. The corrected ``cohort_sql_sha256`` in the manifest is the canonical LF digest of the WP2.1
   cohort query (a documented re-lock, WP2.4 §6), and the file it names is also canonical LF.

The Git history carries the correction rationale: the previous manifest value
``379c25d2…`` was hashed from a CRLF working-tree checkout, which made the digest
platform-dependent. The committed blob is LF and hashes to ``301d8a62…``; that is the value
every loader must verify.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CSV_PATH = ROOT / "data" / "model" / "wp2_3_match_assignments.csv"
MANIFEST_PATH = ROOT / "data" / "model" / "wp2_3_split_manifest.json"
COHORT_SQL_PATH = ROOT / "backend" / "sql" / "wp2_1" / "01_model_shot_cohort.sql"
GITATTRIBUTES_PATH = ROOT / ".gitattributes"

CSV_HEADER = "match_id,competition_id,season_id,match_date,split,fold"
EXPECTED_CSV_ROWS = 231  # header + 230 matches

#: Canonical LF digests, pinned as the corrected re-lock values (WP2.4 plan §6).
ASSIGNMENTS_SHA256 = "e2d5517d96aa81d2229e1ef00a3c692f44f280630c3e75b7f6735e7cdc1787d8"
COHORT_SQL_SHA256 = "301d8a620b60d8da6011c7c4d12ef8108c658df4d923f612c3e3bf9e0427978e"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_gitattributes_pins_canonical_lf_for_pinned_artifact_types() -> None:
    text = GITATTRIBUTES_PATH.read_text(encoding="utf-8")
    for rule in ("*.csv text eol=lf", "*.sql text eol=lf", "*.json text eol=lf"):
        assert rule in text, f".gitattributes must keep the rule: {rule}"


def test_assignment_csv_is_canonical_lf_and_byte_pinned() -> None:
    data = CSV_PATH.read_bytes()
    assert b"\r" not in data, "assignment CSV must be canonical LF; a CRLF checkout is a re-lock"
    assert data.count(b"\n") == EXPECTED_CSV_ROWS
    first_line = data.split(b"\n", 1)[0].decode("utf-8")
    assert first_line == CSV_HEADER
    assert _sha256_bytes(data) == ASSIGNMENTS_SHA256


def test_cohort_sql_is_canonical_lf_and_matches_the_corrected_manifest_hash() -> None:
    data = COHORT_SQL_PATH.read_bytes()
    assert b"\r" not in data, "cohort SQL must be canonical LF; a CRLF checkout is a re-lock"
    assert _sha256_bytes(data) == COHORT_SQL_SHA256


def test_manifest_is_canonical_lf_and_records_the_corrected_sql_digest() -> None:
    raw = MANIFEST_PATH.read_bytes()
    assert b"\r" not in raw, "split manifest must be canonical LF"
    manifest = json.loads(raw)
    assert manifest["assignments_sha256"] == ASSIGNMENTS_SHA256
    assert manifest["cohort_sql_sha256"] == COHORT_SQL_SHA256
    assert manifest["cohort_sql_sha256"] == _sha256_bytes(COHORT_SQL_PATH.read_bytes())
    assert manifest["assignments_sha256"] == _sha256_bytes(CSV_PATH.read_bytes())
