# ADR 0004: Cohort scope and validation design

## Status

Accepted — 2026-07-31

## Context

The original plan assumed the project would start from "one documented competition/season slice" and
later evaluate with a chronological holdout plus competition/season error slices. Counting the actual
data showed both assumptions fail.

`competitions.json` lists 87 competition-seasons. Counting team appearances per match revealed that
**every league season in StatsBomb Open Data is single-team-centric**: Ligue 1 2021/22 and 2022/23
contain Paris Saint-Germain in all 26 and 32 matches, Bundesliga 2023/24 contains Bayer Leverkusen in
all 34, La Liga 2020/21 contains Barcelona in all 35. Tournaments are complete and balanced —
WC 2022 has 64 matches across 32 teams, Euro 2024 has 51 across 24.

Sampling 12 WC 2022 and 10 Euro 2024 matches gave 18.9–23.0 non-penalty shots per match, 7.8–9.7%
conversion, and zero shots missing coordinates. Extrapolated, the largest single slice (WC 2022)
yields roughly 1,210 non-penalty shots and 117 goals — which, split three ways, leaves about 30 goals
in a holdout. A reliability curve on 30 events is noise.

Two further problems follow. A chronological holdout *inside* a league season measures one club's
form curve, not football drift. And a competition/season error slice is impossible if only one
competition was ingested.

## Decision

**Core cohort:** balanced tournaments only — WC 2018, Euro 2020, WC 2022, Euro 2024. Approximately
230 matches, ~4,700 non-penalty shots, ~420 goals. Only these matches are downloaded.

**Single-team league seasons are excluded from the core cohort** but retained as a declared
selection-bias slice, which also makes a genuine competition-level error slice possible.

**Validation** uses a three-way split, named explicitly rather than described:

```text
dev matches         → GroupKFold(match_id) → tuning, feature selection, model selection
calibration set     → matches disjoint from dev → calibration fitting only
tournament holdout  → later tournament → opened once, after selection, for the final report
```

**The holdout is called a tournament holdout, not a temporal holdout.** Holding out Euro 2024 changes
time and tournament composition together — club-cycle versus international, different preparation and
fixture density. That confounding is stated in the model card and the write-up rather than glossed.

Reliability binning follows the holdout goal count: at roughly 75 goals, five bins are defensible and
ten are not.

## Alternatives considered

- **One competition/season, as originally planned:** rejected — insufficient holdout events, and it
  makes a mandated error slice impossible.
- **Use the league seasons for a within-season chronological holdout:** rejected — the sample is one
  club plus its opponents, so the split measures that club's form, and the result would not
  generalise.
- **Ingest everything (87 competition-seasons):** rejected — large download and ingestion cost, and
  mixing men's, women's, youth and 1970s competitions into one cohort creates heterogeneity that this
  project cannot characterise responsibly.
- **Call the holdout "temporal":** rejected as inaccurate. It would be the first claim challenged in
  a technical interview, and correctly.

## Consequences

- Multi-competition ingestion is required from M1; the schema must carry competition and season as
  first-class dimensions.
- Evaluation claims are scoped to international-tournament football, which is stated as a limitation.
- The selection-bias slice becomes a genuine analytical asset rather than an excluded awkwardness.
- Shot counts here were sampled extrapolations. WP0.3 has since measured WC 2022 exactly; see the
  amendment below. The remaining three tournaments are still extrapolated.

## Amendment, 2026-07-31 — WC 2022 measured

WP0.3 loaded FIFA World Cup 2022 in full. The sampled estimate was **low by roughly 18%**: a
12-match sample gave 18.9 non-penalty shots per match, the true figure over all 64 is **22.3**.

| Measured, WC 2022 | |
|---|---:|
| Matches | 64 |
| Teams · players | 32 · 431 |
| Shots, all types | 1,494 |
| Penalties (incl. shootout kicks, all period 5) | 64 |
| **Non-penalty shots** | **1,430** |
| **Non-penalty goals** | **152** |
| Conversion | 10.6% |
| Shots missing location, player, outcome, body part or technique | **0** |

Two things this changes:

1. **The cohort is larger than assumed.** Re-extrapolating the other three tournaments at the
   measured rate gives roughly **5,100 non-penalty shots and ~545 goals** across
   WC 2018 + Euro 2020 + WC 2022 + Euro 2024, against the earlier estimate of ~4,700 and ~420.
   The holdout has more headroom than the original arithmetic suggested; the five-bin reliability
   decision should be revisited against the real count when the full cohort is loaded.
2. **Shootout kicks are typed `Penalty` and sit in period 5**, so a single `shot_type <> 'Penalty'`
   filter already excludes them. Worth knowing before writing the cohort query — a naive period
   filter alone would not have been enough, and neither would have been obvious from the schema.

Coverage is cleaner than expected: zero missing coordinates and zero unattributed shots in 1,494
rows. The parser still tolerates both, because that is a property of the source rather than a
guarantee, and the other three tournaments are not yet loaded.

## Review trigger

StatsBomb publishes a genuinely multi-team league season; the exact M1 counts differ materially from
the extrapolation; or a modelling question requires club football rather than tournament football.
