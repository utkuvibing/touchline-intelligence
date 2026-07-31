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
- Shot counts here are sampled extrapolations. The first output of M1 is the exact count, and this
  ADR's numbers are updated from it.

## Review trigger

StatsBomb publishes a genuinely multi-team league season; the exact M1 counts differ materially from
the extrapolation; or a modelling question requires club football rather than tournament football.
