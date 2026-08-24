# WP2.1 cohort and leakage contract

## Research question

Estimate the probability that a recorded Shot becomes a goal, using only information available at
or before the shot in the accepted four-tournament StatsBomb Open Data cohort. The target is a
probability, not a thresholded goal/no-goal decision. The model is not StatsBomb's proprietary xG
model and will not use provider xG as an input or training reference.

## Population and target

The version-1 population is the four complete tournaments accepted in ADR 0004 and pinned by the M1
manifest: World Cup 2018 `(43,3)`, Euro 2020 `(55,43)`, World Cup 2022 `(43,106)`, and Euro 2024
`(55,282)`. One row is one typed Shot event, identified by `event_id` and grouped later by
`match_id`. `match_date`, competition, and season are carried as split/audit metadata.

`is_goal = 1` exactly when the recorded `shots.outcome_name` is `Goal`; every other known shot
outcome maps to 0. Outcome is used once to construct the target and is not projected as a candidate
input. Own-goal events are not typed Shot details in this source model, so they are outside the shot
population and are counted separately rather than coerced into the target.

The SQL requires player, period, both raw location coordinates, outcome, body part, technique, and
shot type to be known. Each NULL predicate is explicit so SQL three-valued logic cannot silently
discard an unknown type or count an unknown outcome as a miss. M1 measured zero missing values for
these fields, but the predicates preserve the contract if a future pinned source differs.

## Penalty and class-balance policy

Primary modelling uses non-penalty shots. Penalties have nearly fixed geometry and a different
generating process, so mixing them into the main model would distort interpretation. A row is
excluded when `shot_type_name = 'Penalty'` or `period = 5`; both conditions remain even though all
currently observed shootout kicks satisfy both. Regulation penalties and shootout penalties stay in
the reconciliation evidence and may later receive a labelled empirical-rate policy. They are never
silently dropped or presented as predictions from the non-penalty model.

The measured non-penalty prevalence is 507/5,606 (9.04%). This is moderate imbalance. Because the
deliverable is a calibrated probability, there is no SMOTE, class weighting, or threshold tuning:
those interventions change the effective class prior without solving a minority-starvation problem.
The constant-prediction baseline in WP2.4 will be estimated from training rows only. The 9.04%
full-cohort description is not an evaluation baseline.

## Feature availability review

`Available` means the fact exists at or before the shot. It does not mean the field is approved for
the final model: categorical support, semantics, missing-value encoding, and training/serving parity
are WP2.2 gates. `Uncertain` blocks use until the named question is resolved. `Unavailable` means the
field is forbidden as an input.

| Candidate or field | Status at prediction time | WP2.1 decision |
|---|---|---|
| Raw shot `location_x`, `location_y` | Available | Project as raw coordinates. WP2.2 must create a geometry-safe representation and handle the measured `x = 120.1` exception without silently changing source data. |
| Body part ID/name | Available | Candidate after coverage and unknown-category handling. |
| Technique ID/name | Available | Candidate after coverage; rare values remain visible. |
| Shot type ID/name | Available | Used for the penalty policy and a possible context candidate; not a proxy for the target. |
| Play pattern ID/name | Available | Candidate after coverage and semantics review. |
| Period, minute, second | Available | Retained for eligibility/audit. Clock fields are not approved model inputs in WP2.1. |
| Team, player, possession IDs | Available | Immutable identity/grouping metadata only. Do not use sparse identities as model features without a later explicit decision. |
| Competition, season, match ID/date | Available | Scope, audit, grouping, and later split metadata only; not feature inputs. |
| `under_pressure` | Uncertain | Event-time concept, but absent-versus-false encoding and coverage must be verified before use. |
| `aerial_won` | Uncertain | Shot-time annotation with optional true-only-looking storage; verify semantics and redundancy with body part. |
| `first_time` | Uncertain | Plausibly known at contact; verify optional boolean semantics and coverage before use. |
| `follows_dribble` | Uncertain | Plausibly pre-shot, but only 7 recorded positives in this cohort; do not merge or use without review. |
| `open_goal` | Uncertain | Situation is observable at the shot, but provider annotation semantics and optional encoding require review. |
| `one_on_one` | Uncertain | Situation is observable at the shot, but provider annotation semantics and optional encoding require review. |
| Key-pass event and event relations | Uncertain | A preceding event may be available, but direction, timing, relation type, and coverage must be proven before deriving assist/cross features. |
| Embedded shot freeze-frame players | Uncertain | Event-time snapshot, but partial visibility/coverage and missing-player semantics require a separate contract. It is neither StatsBomb 360 nor tracking data. |
| Event position | Uncertain | Recorded at the event, but semantic value and risk of identity/role shortcuts need review. |
| Outcome ID/name | Unavailable | Target source only; forbidden as an input. |
| Shot end `x/y/z` | Unavailable | Post-shot trajectory/outcome information. |
| `deflected`, `redirect` | Unavailable | Shot-flight/post-contact information under the conservative prediction boundary. |
| `saved_off_target`, `saved_to_post` | Unavailable | Directly outcome-derived post-shot facts. |
| Event duration, `out` | Unavailable | Known only after the event completes. |
| Provider `statsbomb_xg` | Unavailable | Never ingested; parser and database contracts prohibit it. No external comparison is authorized by WP2.1. |
| Future events, final score, later match state | Unavailable | Information from after the shot. |
| Target-derived aggregates | Unavailable | Any rate or encoding fitted with outcome data must be fitted on training rows only in a later WP. |

The cohort query projects the raw uncertain booleans so their coverage can be audited, not because
they are approved final features. Downstream feature code must use an explicit allow-list; passing
the SQL frame wholesale to a model is forbidden.

## Measured reconciliation

The pinned full cohort was measured on 2026-08-02 using the four queries in
`backend/sql/wp2_1/` against source commit
`b0bc9f22dd77c206ddedc1d742893b3bbe64baec`. Results are recorded in
`reports/wp2.1-cohort-reconciliation.md`.

WP2.1 does not choose the development/calibration/tournament-holdout rows and does not train or
evaluate a model. Those decisions begin in WP2.3 and WP2.4. The tournament holdout changes time and
competition composition together; it is not called a temporal holdout.

Data provided by StatsBomb.
