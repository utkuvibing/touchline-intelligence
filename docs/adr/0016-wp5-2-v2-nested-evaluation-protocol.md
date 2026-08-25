# ADR 0016: WP5.2 v2 nested evaluation protocol and mechanical gates

**Status:** accepted for WP5.2 upon merge of the contract, config, fold-semantics module and
tests. The module is production code but is imported by no serving or training path yet — nothing
consumes it until M6/M7 — and no experiment has executed under this protocol, so no result claim
is attached to it.

**Date:** 2026-08-25

**Contract:** [WP5.2 v2 nested protocol contract](../modeling/wp5_2-v2-nested-protocol-contract.md)

## Context

The v1 protocol (WP2.3/ADR 0013) locked a single three-way split — WC2018+Euro2020 development,
WC2022 calibration, Euro2024 one-time tournament holdout — and that holdout was opened once for
the WP2.7/WP2.8 release. It is spent: no future model can claim it as untouched evidence, and
recycling it would be exactly the "holdout reopened after a poor result" failure mode the plan
prohibits.

The post-M4 roadmap therefore requires a corrected protocol before any v2 modeling: outer
leave-one-tournament-out evaluation over all four inspected tournaments, inner match-grouped
selection, fold-local preprocessing, exactly four candidate families, a restricted calibration
policy, and two newly sealed external qualification sets (AFCON 2023 and Copa América 2024,
sealed in M5 WP5.1 with loader-level rejection). The roadmap also fixes every numerical gate —
bundle admission, internal replacement, calibration adoption, external promotion — so the M7
release decision can be a mechanical application of committed thresholds rather than reviewer
judgment.

Two preregistration hazards had to be closed before the first v2 run: silent drift between prose
commitments and executable code, and conflation of selection evidence (biased by construction)
with generalization evidence (the sealed sets).

## Decision

1. Commit the complete v2 protocol **before any v2 experiment runs** as three mutually pinned
   artifacts: the prose contract, a machine-readable gate config (`data/model/v2_protocol.json`),
   and this ADR. Unit tests enforce an exact allowed-key schema on the config and pin every
   numerical gate to literals, so changing prose, config or tests without the others fails CI.
2. Ship the target-free fold semantics as **one production module**,
   `backend/src/touchline/modeling/v2_folds.py`, driven only by the machine-readable config: four
   LOTO scopes `(43,3)`, `(55,43)`, `(43,106)`, `(55,282)` in fixed order; inner CV grouped
   strictly by `match_id`, `k=5`, matches sorted by `(match_date, match_id)`, `index % 5`,
   `shuffle=false`, no seed; loud failure on duplicate ids, missing dates, foreign or sealed
   scopes, and degenerate partitions; unresolved ties resolve mechanically to the simpler
   candidate (lower bundle level, then logistic over boosting), never to measured performance.
   M6 and M7 must import this exact module — the inner split count is read from the frozen
   config with no caller override, and inner-fold construction rejects any scope outside the
   development pool or the declared outer-training partition — only materialized fold-manifest
   generation is deferred to M7's harness.
3. Fix uncertainty mechanics at WP2.7's proven values — paired differences, match-clustered
   bootstrap, 2,000 replicates, seed 0, 95% percentile intervals — extended with one preregistered
   rule: pooled multi-tournament comparisons resample tournament-stratified within each replicate,
   preserving per-stratum match counts, so pooled intervals are not dominated by the largest
   tournament.
4. Declare the evidence hierarchy binding: outer-LOTO results are internal development/selection
   evidence, optimistically biased and never presented as the unbiased post-selection estimate;
   the one-time sealed AFCON/Copa América qualification is the only external generalization
   evidence and the only basis for replacing v1.
5. Freeze the candidate list at exactly four families (constant prevalence, v1-form L2 logistic,
   context-rich spline logistic with inner-selected M6 bundle, one `HistGradientBoostingClassifier`
   challenger) including their hyperparameter search spaces, before any outcome-bearing run.
   Adding families or widening grids afterwards requires a new ADR.
6. Restate calibration policy (raw / intercept-only / Platt only; isotonic excluded) together
   with its **exact leakage-free fitting procedure**, preregistered now: per outer fold,
   intercept-only/Platt candidates are fitted only from out-of-fold raw predictions generated
   inside the outer training partition by the frozen inner CV, then applied to that fold's
   untouched outer-holdout raw predictions; the adoption gates evaluate these per-fold calibrated
   predictions. For the final refit, in order: generate development OOF raw predictions with the
   frozen inner procedure, fit the selected calibrator on them, refit the base model on all
   development rows, and freeze the model–calibrator pair before opening either sealed set. All
   gate numbers are verbatim from the post-M4 roadmap: bundle admission (CI wholly below zero;
   Brier degradation ≤ 0.0005; at most one represented tournament worse; no tournament worse than
   0.005 log loss); internal replacement (≥ 0.003 pooled log-loss improvement; ≥ 3 of 4
   tournaments non-worse); calibration adoption (≥ 0.001 improvement; no pooled Brier degradation;
   intercept/slope closer to ideal in ≥ 3 of 4; no tournament worse than 0.002); external
   promotion (≥ 0.003 combined improvement vs the stronger v1 variant; paired Brier upper bound ≤
   +0.0005; neither external tournament worse than 0.005). The external `constant_prevalence`
   reference is defined as the full-development prevalence over all four development-pool
   tournaments, frozen before sealed-set opening — a training-pool statistic, never an
   external-set statistic.
7. Carry the stop conditions into the protocol text: if the external gate fails, retain v1,
   publish v2 as a negative result, and freeze further model selection until a genuinely untouched
   complete tournament exists at a future pinned revision (per the WP5.1 future reservation, none
   does today). Recycling a sealed set after opening is prohibited here, not only in the registry.

## Consequences

Any v2 experiment run from now on is either an execution of this frozen document or a visible,
ADRed deviation. Silent protocol drift becomes a CI failure instead of a review-time discovery.
The bias structure of reported numbers is explicit up front, which protects the project from its
most tempting error after a disappointing holdout history: relabeling selection evidence as
confirmation evidence.

The protocol is stricter than strictly necessary in places — frozen search grids, no seed-based
fold shuffling, mechanical tie-breaking — because preregistration value comes precisely from
giving up post-hoc freedom. WC2022 loses its privileged calibration status and becomes ordinary
development data under the corrected protocol; Euro 2024 is admitted to v2 development with its
untouchability cost recorded rather than hidden.

No artifact here executes a model, reads sealed rows, or produces a metric; the boundary is
enforced by review of the diff and by the absence of any execution record.

## Rejected alternatives

- Keep tuning around the v1 three-way split: rejected — the holdout is spent, and reusing it for
  v2 selection would invalidate every future claim.
- Generate fold manifests now alongside the contract: rejected — the manifest is trivially
  derivable from tournament membership, and committing generated artifacts before the harness
  design settles invites drift; the semantics are frozen in a production module instead.
- Let each phase (M6/M7) implement its own fold logic against shared prose: rejected — divergent
  reimplementations are how nested protocols quietly break; the config-driven module shipped here
  is the only permitted primitive.
- Fit calibrators on the outer holdout or on in-sample predictions: rejected — either fits the
  calibrator to rows whose outcomes influenced the underlying model, which is precisely the
  leakage the corrected protocol exists to remove; only inner-CV OOF raw predictions may fit a
  calibrator.
- Defer search-space freezing to M7: rejected — declaring grids after seeing any run output is
  post-hoc search under another name (the ADR 0011 precedent applied to v2).
- Adopt isotonic regression or additional calibrators: rejected on corpus size (~5,600 shots);
  raw/intercept/Platt covers the defensible space.
- Stratify the bootstrap by tournament only for pooled comparisons via reviewer choice at report
  time: rejected — stratification is part of the estimator definition and must be fixed before
  intervals exist.
