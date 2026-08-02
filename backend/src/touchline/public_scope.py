"""The deliberately narrow data scope exposed by the public M0 endpoints.

WP1.3 loads four tournaments for internal analysis, but the unresolved redistribution question
means that adding database rows must not silently publish them. Keeping the public scope as a
named query-level contract makes that separation explicit and testable.
"""

from __future__ import annotations

PUBLIC_COMPETITION_ID = 43
PUBLIC_SEASON_ID = 106

PUBLIC_SCOPE_PREDICATE = (
    "m.competition_id = %(public_competition_id)s AND m.season_id = %(public_season_id)s"
)

PUBLIC_SCOPE_PARAMS = {
    "public_competition_id": PUBLIC_COMPETITION_ID,
    "public_season_id": PUBLIC_SEASON_ID,
}

PUBLIC_SCOPE_DESCRIPTION = "FIFA World Cup 2022 (competition 43, season 106)"
