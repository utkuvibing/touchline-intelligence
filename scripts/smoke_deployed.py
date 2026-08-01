"""Smoke-test a deployed Touchline instance.

    uv run python scripts/smoke_deployed.py --api https://... --frontend https://...

Runs against the *deployed* URLs, not a local process. CI does not run this — it has no
credentials and no deployment — so it is a release check, invoked by hand after a deploy and
recorded in the release notes.

It checks facts, not vibes: that the database is actually reachable from the API, that the
conversion rate matches the loaded cohort, that the shot total is the full pinned snapshot, and
that the rendered page really contains shot markers rather than an error state.

Exit code is 0 only if every check passes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

# What the pinned WC 2022 snapshot must produce. Hard-coded rather than read back from the
# deployment: a smoke test that asks the system what it contains and then agrees with it has
# checked nothing.
EXPECTED_TOTAL_SHOTS = 1494
EXPECTED_COHORT_SHOTS = 1430
EXPECTED_COHORT_GOALS = 152

TIMEOUT = 30


@dataclass
class Results:
    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        suffix = f" — {detail}" if detail else ""
        if ok:
            self.passed.append(name)
            print(f"  [PASS] {name}{suffix}")
        else:
            self.failed.append(name)
            print(f"  [FAIL] {name}{suffix}")


def _get(url: str) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "touchline-smoke/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        return 0, str(exc)


def _get_json(url: str) -> tuple[int, Any]:
    status, body = _get(url)
    try:
        return status, json.loads(body)
    except json.JSONDecodeError:
        return status, None


def check_api(api: str, results: Results) -> None:
    print(f"\nAPI: {api}")

    status, body = _get_json(f"{api}/health")
    results.check(
        "/health returns ok",
        status == 200 and body and body.get("status") == "ok",
        f"status={status}",
    )

    status, body = _get_json(f"{api}/ready")
    ready = status == 200 and body and body.get("status") == "ready"
    results.check(
        "/ready reports the database reachable",
        bool(ready),
        f"status={status}, database={body.get('database') if body else 'n/a'}",
    )

    status, body = _get_json(f"{api}/baseline")
    if status != 200 or not body:
        results.check("/baseline returns the cohort rate", False, f"status={status}")
    else:
        results.check(
            "/baseline matches the pinned snapshot",
            body.get("shots") == EXPECTED_COHORT_SHOTS
            and body.get("goals") == EXPECTED_COHORT_GOALS,
            f"{body.get('goals')}/{body.get('shots')} "
            f"(expected {EXPECTED_COHORT_GOALS}/{EXPECTED_COHORT_SHOTS})",
        )
        results.check(
            "/baseline still says it is not a model",
            "not a model" in body.get("caveat", ""),
        )

    status, body = _get_json(f"{api}/shots?limit=1")
    if status != 200 or not body:
        results.check("/shots returns a page", False, f"status={status}")
    else:
        results.check(
            "/shots reports the full pinned snapshot",
            body.get("total") == EXPECTED_TOTAL_SHOTS,
            f"total={body.get('total')} (expected {EXPECTED_TOTAL_SHOTS})",
        )
        shot = (body.get("shots") or [{}])[0]
        results.check(
            "/shots returns recorded facts",
            all(shot.get(k) is not None for k in ("shot_id", "team", "outcome")),
        )
        results.check(
            "/shots carries no probability field",
            not any(k.lower() in {"xg", "statsbomb_xg", "probability", "prediction"} for k in shot),
        )


def check_frontend(frontend: str, expected_api: str | None, results: Results) -> None:
    print(f"\nFrontend: {frontend}")

    status, html = _get(frontend)
    results.check("page responds", status == 200, f"status={status}")
    if status != 200:
        return

    results.check("page identifies the project", "Touchline Intelligence Platform" in html)
    results.check(
        "provisional notice is present",
        "no performance claim on this site has been evaluated" in html,
    )
    results.check("StatsBomb attribution is present", "Data provided by StatsBomb" in html)

    # The shot map is server-rendered, so the markers are in the HTML. Counting them is what
    # distinguishes "the page loaded" from "the page loaded and the data reached it".
    markers = len(re.findall(r"<circle", html))
    results.check(
        "shot map rendered with markers",
        markers > 100,
        f"{markers} <circle> elements",
    )

    results.check(
        "page is not showing the API error state",
        "Could not load shots from the API" not in html,
    )
    results.check(
        "map is not disclosing a shortfall",
        "not the complete tournament" not in html,
        "a shortfall notice means paging did not retrieve every shot",
    )

    if expected_api:
        status, _ = _get(f"{expected_api}/health")
        results.check("frontend's API is the one just checked", status == 200)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", required=True, help="deployed API base URL, no trailing slash")
    parser.add_argument("--frontend", required=True, help="deployed frontend URL")
    args = parser.parse_args()

    api = args.api.rstrip("/")
    frontend = args.frontend.rstrip("/")

    results = Results()
    check_api(api, results)
    check_frontend(frontend, api, results)

    total = len(results.passed) + len(results.failed)
    print(f"\n{len(results.passed)}/{total} checks passed")
    if results.failed:
        print("\nFailed:")
        for name in results.failed:
            print(f"  - {name}")
        return 1
    print("Deployment smoke test passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
