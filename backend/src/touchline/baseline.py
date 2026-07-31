"""The constant base-rate baseline.

This is **not a model.** It returns one number - the observed conversion rate of the loaded shot
cohort - and returns it for every shot regardless of where the shot was taken, who took it, or
anything else. There is no fitting, no train/test split, and no performance claim.

Two reasons it exists rather than a placeholder model:

1. It proves the whole path end to end (PostgreSQL -> query -> API -> UI) with something that is
   *trivially correct*. A knowingly mis-evaluated model published on a URL is not a placeholder,
   it is a wrong artifact.
2. It is the number every real model in M2 must beat. A shot-quality model that cannot improve on
   "assume every shot is average" has learned nothing, and having the figure measured and served
   from day one makes that comparison concrete rather than theoretical.

The cohort follows ADR 0004: non-penalty shots only.
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg

# Penalties are excluded because their geometry and context are nearly fixed, so mixing them into
# a single rate makes that rate describe neither open play nor penalties.
#
# The period filter is belt-and-braces. WP0.3 measured that every period-5 (shootout) kick in
# WC 2022 is also typed 'Penalty', so `shot_type` alone is currently sufficient - but the other
# three tournaments in the cohort are not loaded yet, and a shootout kick that arrived untyped
# would otherwise be counted as open play.
COHORT_PREDICATE = "shot_type <> 'Penalty' AND period <> 5"

COHORT_DESCRIPTION = (
    "All shots in the loaded scope excluding penalties and penalty-shootout kicks. "
    "No filtering by competition, team, player, period or location."
)

# Interpolated from the module constant above, never from input, so the predicate and the text
# published beside it cannot drift apart.
BASE_RATE_SQL = f"""
    SELECT
        count(*)                                 AS shots,
        count(*) FILTER (WHERE outcome = 'Goal') AS goals
    FROM shots
    WHERE {COHORT_PREDICATE}
"""


class NoDataError(RuntimeError):
    """No shots are loaded, so there is no rate to report.

    Distinct from a rate of zero: "nothing has been ingested" and "nothing was scored" are
    different facts and must not produce the same answer.
    """


@dataclass(frozen=True, slots=True)
class BaseRate:
    """The observed conversion rate, with the counts it was derived from.

    The counts travel with the rate deliberately. A rate on its own invites being read as a
    property of football; the denominator is what makes it a property of *this loaded scope*.
    """

    shots: int
    goals: int

    @property
    def value(self) -> float:
        return self.goals / self.shots


def compute_base_rate(conn: psycopg.Connection) -> BaseRate:
    """Count the cohort and its goals in a single pass.

    Computed on request rather than cached: the table is small, and a cached figure that silently
    disagreed with the database would be worse than the query cost it saved.
    """
    with conn.cursor() as cur:
        cur.execute(BASE_RATE_SQL)
        row = cur.fetchone()

    if row is None:
        raise NoDataError("base-rate query returned no row")

    shots, goals = int(row[0]), int(row[1])
    if shots == 0:
        raise NoDataError("no shots are loaded; run `uv run poe ingest --reset` first")

    return BaseRate(shots=shots, goals=goals)
