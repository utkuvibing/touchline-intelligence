"""The descriptive conversion prevalence of the loaded cohort.

This is **not a model, and it is not a prediction.** It is a *descriptive prevalence*: the observed
conversion rate of the shots currently loaded, reported as a summary of that data.

It exists to prove the whole path end to end (PostgreSQL -> query -> API -> UI) with something that
is trivially correct. A knowingly mis-evaluated model published on a URL is not a placeholder, it
is a wrong artifact.

## What this number is NOT

It is **not** the baseline that M2 models are compared against, and it must never be used as a
prediction on evaluation rows.

The constant-prediction baseline in M2 is a different object with a different value:

* it is estimated from the **training split only**;
* it is then evaluated on validation and holdout rows using the same log loss, Brier score and
  calibration protocol as every candidate model;
* a model beats it on **those evaluation metrics**, not by being numerically distant from this
  prevalence.

Using this full-cohort rate as the prediction for holdout rows would be leakage in its plainest
form: the rate is computed from outcomes that include the holdout's own labels, so the "baseline"
would be scored partly on knowledge of the answers. The number below is a description of the
loaded data, and stops there.

The cohort follows ADR 0004: non-penalty shots only.
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg

from touchline.public_scope import (
    PUBLIC_SCOPE_DESCRIPTION,
    PUBLIC_SCOPE_PARAMS,
    PUBLIC_SCOPE_PREDICATE,
)

# Penalties are excluded because their geometry and context are nearly fixed, so mixing them into
# a single rate makes that rate describe neither open play nor penalties.
#
# The period filter is belt-and-braces. WP0.3 measured that every period-5 (shootout) kick in
# WC 2022 is also typed 'Penalty', so `shot_type` alone is currently sufficient - but the other
# internal tournaments must not affect this public query, and a WC 2022 shootout kick that arrived
# untyped would otherwise be counted as open play.
#
# Missing values are excluded explicitly rather than left to SQL's three-valued logic, which would
# handle them inconsistently and invisibly:
#
#   * a NULL `shot_type` makes `shot_type <> 'Penalty'` evaluate to NULL, so the row would be
#     dropped from the cohort silently - the same treatment as a penalty, for a completely
#     different reason;
#   * a NULL `period` behaves the same way;
#   * a NULL `outcome` would *not* be dropped. It would sit in the denominator while failing the
#     `outcome = 'Goal'` filter, i.e. be counted as a definite miss on the basis of no information.
#
# Requiring all three to be known makes the denominator mean one thing: shots we actually know the
# result of. WC 2022 has zero missing values in these columns, so this changes no current count -
# it changes what happens when a future competition does have them.
COHORT_PREDICATE = (
    "s.shot_type_name IS NOT NULL "
    "AND e.period IS NOT NULL "
    "AND s.outcome_name IS NOT NULL "
    "AND s.shot_type_name <> 'Penalty' "
    "AND e.period <> 5"
)

COHORT_DESCRIPTION = (
    f"Shots in the public {PUBLIC_SCOPE_DESCRIPTION} scope with a known shot type, period and "
    "outcome, excluding penalties and penalty-shootout kicks. Shots missing any of those three "
    "fields are excluded from both the numerator and the denominator rather than being counted "
    "as misses. No filtering by team, player or location."
)

# Interpolated from the module constant above, never from input, so the predicate and the text
# published beside it cannot drift apart.
BASE_RATE_SQL = f"""
    SELECT
        count(*)                                        AS shots,
        count(*) FILTER (WHERE s.outcome_name = 'Goal') AS goals
    FROM shots AS s
    JOIN events AS e ON e.event_id = s.event_id
    JOIN matches AS m ON m.match_id = e.match_id
    WHERE {PUBLIC_SCOPE_PREDICATE}
      AND {COHORT_PREDICATE}
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
        cur.execute(BASE_RATE_SQL, PUBLIC_SCOPE_PARAMS)
        row = cur.fetchone()

    if row is None:
        raise NoDataError("base-rate query returned no row")

    shots, goals = int(row[0]), int(row[1])
    if shots == 0:
        raise NoDataError("no shots are loaded; run `uv run poe ingest --reset` first")

    return BaseRate(shots=shots, goals=goals)
