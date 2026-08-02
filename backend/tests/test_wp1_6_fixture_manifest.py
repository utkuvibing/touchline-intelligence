"""Byte-level contract for the fictional, network-free integration fixture."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from touchline.ingest.source import SOURCE_COMMIT

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "statsbomb"
MANIFEST_PATH = FIXTURE_ROOT / "manifest.json"


def test_fixture_manifest_pins_every_and_only_ingested_json_byte_stream() -> None:
    """Fixture changes require an intentional manifest/checksum and test-contract update."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    assert manifest["fixture_name"] == "fictional-statsbomb-shaped-two-match-scope"
    assert manifest["format_version"] == 1
    assert manifest["network"] == "forbidden"
    # The production runner records this source revision in its lifecycle manifest.  This fixture
    # is fictional, so this is a runner-contract pin rather than a claim about real source bytes.
    assert manifest["source_commit_for_manifest_contract"] == SOURCE_COMMIT

    expected = manifest["files_sha256"]
    actual = {
        path.relative_to(FIXTURE_ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in FIXTURE_ROOT.rglob("*.json")
        if path != MANIFEST_PATH
    }
    assert actual == expected
