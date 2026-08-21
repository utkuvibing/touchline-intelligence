"""Static contract for the native Railway deployment gate."""

from __future__ import annotations

import json
from pathlib import Path


def test_railway_uses_predeploy_migration_and_readiness_healthcheck() -> None:
    config = json.loads((Path(__file__).parents[2] / "railway.json").read_text(encoding="utf-8"))

    deploy = config["deploy"]
    assert deploy["preDeployCommand"] == ["python -m touchline.ingest.migrate"]
    assert deploy["healthcheckPath"] == "/ready"
    assert deploy["restartPolicyType"] == "ON_FAILURE"
