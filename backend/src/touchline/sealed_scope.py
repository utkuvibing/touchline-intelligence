"""Sealed external evaluation sets (M5 WP5.1).

M5 seals two complete men's tournaments from the pinned StatsBomb Open Data revision as the
one-time v2 external qualification sets (PLAN.md, Post-M4 roadmap):

- AFCON 2023 — competition ``1267``, season ``107``;
- Copa América 2024 — competition ``223``, season ``282``.

Before M7's frozen candidate exists, nothing in normal development may read their rows or labels.
The only permitted access is *target-free structural validation*: file existence, schema
compatibility, match identifiers, coordinate bounds and parser success — never shot outcomes,
goal counts, conversion rates, model scores or row-level previews.

This module is the single enforcement point, mirroring ``config.require_local_write_target``:
guards are centralized here so every development loader rejects a sealed scope through one named
error rather than scattering ad-hoc checks. The season id ``282`` also belongs to Euro 2024's
``(55, 282)``, so every check compares the full ``(competition_id, season_id)`` pair — never a
bare season id.

The constants are pinned by unit tests against the committed machine-readable registry at
``data/model/v2_evaluation_registry.json``; changing one without the other must break CI.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: Sealed competition-season pairs. A development loader that receives either must fail loudly.
SEALED_SCOPES: frozenset[tuple[int, int]] = frozenset({(1267, 107), (223, 282)})

#: Canonical names, used in error messages and the registry.
SEALED_SET_NAMES: dict[tuple[int, int], str] = {
    (1267, 107): "AFCON 2023",
    (223, 282): "Copa America 2024",
}

#: The only access any sealed set permits before M7 opens its qualification run.
PERMITTED_ACCESS = "target_free_structural_only"

REGISTRY_PATH = Path("data/model/v2_evaluation_registry.json")


class SealedScopeError(ValueError):
    """A caller asked a development loader to touch a sealed external evaluation set.

    Raised before any download or database work happens: rejecting a sealed scope is a policy
    fact about the request, not a data failure, so no partial state can exist. Every raise site
    names the sealed tournament and this module's rule.
    """


def require_unsealed_scopes(scopes: Any) -> None:
    """Reject a scope collection containing a sealed competition-season pair.

    Accepts any iterable of ``(competition_id, season_id)`` pairs. Empty iterables are not this
    function's concern — callers keep their own emptiness policies.
    """
    for scope in scopes:
        require_unsealed_scope(scope)


def require_unsealed_scope(scope: tuple[int, int]) -> None:
    """Reject a single ``(competition_id, season_id)`` pair if it is sealed."""
    pair = (int(scope[0]), int(scope[1]))
    if pair in SEALED_SCOPES:
        raise SealedScopeError(
            f"competition-season {pair} ({SEALED_SET_NAMES[pair]}) is a sealed external "
            f"evaluation set; only {PERMITTED_ACCESS} is permitted before M7"
        )


def load_registry(path: Path | None = None) -> dict[str, Any]:
    """Load and structurally validate the committed evaluation registry.

    Validates only structure and internal consistency with this module's constants; the registry
    carries no outcome-bearing field by construction.
    """
    registry_path = path if path is not None else REGISTRY_PATH
    payload: dict[str, Any] = json.loads(registry_path.read_text(encoding="utf-8"))
    for key in ("schema_version", "attribution", "development_pool", "sealed_sets"):
        if key not in payload:
            raise ValueError(f"evaluation registry is missing required key {key!r}")
    sealed_in_registry = {
        (entry["competition_id"], entry["season_id"]): entry["name"]
        for entry in payload["sealed_sets"]
        if entry.get("status") == "sealed"
    }
    if sealed_in_registry != SEALED_SET_NAMES:
        raise ValueError(
            "evaluation registry sealed sets disagree with the enforced constants "
            f"{sorted(SEALED_SET_NAMES)}: {sorted(sealed_in_registry)}"
        )
    return payload
