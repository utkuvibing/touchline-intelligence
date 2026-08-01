"""Smoke-test a deployed Touchline instance.

    uv run python scripts/smoke_deployed.py --api https://... --frontend https://...

Runs against the *deployed* URLs, not a local process. CI does not run this — it has no
credentials and no deployment — so it is a release check, invoked by hand after a deploy and
recorded in the release notes.

It checks facts, not vibes. Every expected number is hard-coded against the pinned WC 2022
snapshot: a smoke test that asks the system what it contains and then agrees with it has
checked nothing.

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

# What the pinned WC 2022 snapshot must produce.
EXPECTED_TOTAL_SHOTS = 1494
EXPECTED_COHORT_SHOTS = 1430
EXPECTED_COHORT_GOALS = 152

# Every WC 2022 shot has a recorded location, so all of them are plotted. The pitch markings
# contribute exactly one more circle — the penalty spot — so the served HTML must hold
# 1,494 + 1 elements. An exact count is the difference between "the map drew something" and
# "the map drew the tournament": a paging bug that fetched one page would still draw markers.
EXPECTED_CIRCLES = EXPECTED_TOTAL_SHOTS + 1

# An origin that is certainly not on the allow-list. `.invalid` is reserved by RFC 2606, so this
# can never collide with a real deployment.
DISALLOWED_ORIGIN = "https://smoke-test-disallowed.invalid"

TIMEOUT = 30


@dataclass
class Results:
    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        suffix = f" - {detail}" if detail else ""
        if ok:
            self.passed.append(name)
            print(f"  [PASS] {name}{suffix}")
        else:
            self.failed.append(name)
            print(f"  [FAIL] {name}{suffix}")


@dataclass(frozen=True)
class Response:
    status: int
    body: str
    headers: dict[str, str]

    def json(self) -> Any:
        try:
            return json.loads(self.body)
        except json.JSONDecodeError:
            return None


def _get(url: str, headers: dict[str, str] | None = None) -> Response:
    request = urllib.request.Request(
        url, headers={"User-Agent": "touchline-smoke/1.0", **(headers or {})}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read().decode("utf-8", errors="replace")
            return Response(
                response.status, body, {k.lower(): v for k, v in response.headers.items()}
            )
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return Response(exc.code, body, {k.lower(): v for k, v in exc.headers.items()})
    except urllib.error.URLError as exc:
        return Response(0, str(exc), {})


def _visible_text(html: str) -> str:
    """Strip the comment markers React emits between adjacent text nodes.

    Server-rendered React writes `1494<!-- --> shots shown, <!-- -->195<!-- --> of them goals.`,
    so a naive substring search for "1494 shots shown" fails against correct output. Removing the
    markers compares what a reader sees rather than how React framed it.
    """
    return re.sub(r"<!--.*?-->", "", html)


def check_api(api: str, results: Results) -> None:
    print(f"\nAPI: {api}")

    response = _get(f"{api}/health")
    body = response.json()
    results.check(
        "/health returns ok",
        response.status == 200 and bool(body) and body.get("status") == "ok",
        f"status={response.status}",
    )

    response = _get(f"{api}/ready")
    body = response.json()
    results.check(
        "/ready reports the database reachable",
        response.status == 200 and bool(body) and body.get("status") == "ready",
        f"status={response.status}, database={body.get('database') if body else 'n/a'}",
    )

    response = _get(f"{api}/baseline")
    body = response.json()
    if response.status != 200 or not body:
        results.check("/baseline returns the cohort rate", False, f"status={response.status}")
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

    response = _get(f"{api}/shots?limit=1")
    body = response.json()
    if response.status != 200 or not body:
        results.check("/shots returns a page", False, f"status={response.status}")
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


def check_cors(api: str, frontend: str, results: Results) -> None:
    """Verify the allow-list from the outside, with the origin the browser will actually send.

    This is the check that catches the most common deployment mistake: `TOUCHLINE_CORS_ORIGINS`
    left at its localhost default, or set to a preview URL rather than the production one. The
    page still renders — the frontend fetches server-side — but any browser-side call would be
    refused, and nothing else here would notice.
    """
    print("\nCORS")

    allowed = _get(f"{api}/health", {"Origin": frontend})
    header = allowed.headers.get("access-control-allow-origin")
    results.check(
        "the deployed frontend origin is allowed",
        header == frontend,
        f"access-control-allow-origin={header!r}, expected {frontend!r}",
    )

    refused = _get(f"{api}/health", {"Origin": DISALLOWED_ORIGIN})
    refused_header = refused.headers.get("access-control-allow-origin")
    results.check(
        "an unknown origin is refused",
        refused_header is None,
        f"access-control-allow-origin={refused_header!r}, expected absent",
    )
    results.check(
        "the allow-list is not a wildcard",
        refused_header != "*",
        "a wildcard lets any page on the internet read this API from a visitor's browser",
    )


def check_frontend(frontend: str, results: Results) -> None:
    print(f"\nFrontend: {frontend}")

    response = _get(frontend)
    results.check("page responds", response.status == 200, f"status={response.status}")
    if response.status != 200:
        return

    html = response.body
    text = _visible_text(html)

    results.check("page identifies the project", "Touchline Intelligence Platform" in text)
    results.check(
        "provisional notice is present",
        "no performance claim on this site has been evaluated" in text,
    )
    results.check("StatsBomb attribution is present", "Data provided by StatsBomb" in text)

    results.check(
        "page states the full shot count",
        f"{EXPECTED_TOTAL_SHOTS} shots shown" in text,
        f"expected '{EXPECTED_TOTAL_SHOTS} shots shown'",
    )

    circles = len(re.findall(r"<circle", html))
    results.check(
        "shot map drew every shot",
        circles == EXPECTED_CIRCLES,
        f"{circles} <circle> elements (expected {EXPECTED_CIRCLES}: "
        f"{EXPECTED_TOTAL_SHOTS} shots + 1 penalty spot)",
    )

    results.check(
        "page is not showing the API error state",
        "Could not load shots from the API" not in text,
    )
    results.check(
        "map is not disclosing a shortfall",
        "not the complete tournament" not in text,
        "a shortfall notice means paging did not retrieve every shot",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", required=True, help="deployed API base URL, no trailing slash")
    parser.add_argument("--frontend", required=True, help="deployed frontend URL")
    args = parser.parse_args()

    api = args.api.rstrip("/")
    frontend = args.frontend.rstrip("/")

    results = Results()
    check_api(api, results)
    check_cors(api, frontend, results)
    check_frontend(frontend, results)

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
