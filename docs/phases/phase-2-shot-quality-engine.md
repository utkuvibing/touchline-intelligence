# Phase 2 — Shot Quality Engine

**Estimate:** 100–130 hours, roughly 6–9 weeks at 15–20 hours/week  
**Release:** first complete data → model → API → web vertical slice  
**Application milestone:** earliest credible flagship release when every mandatory gate passes.

## Goals and user value

The Shot Quality Engine estimates the probability that a shot becomes a goal and exposes both the estimate and the evidence behind it. Analysts can compare chances, inspect shot locations and contexts, and understand where a model is trustworthy or weak. A football organization benefits from a transparent baseline for chance quality, finishing analysis, match review, and later value models—not from claiming to recreate StatsBomb's proprietary xG.

This phase teaches the developer to turn a football question into a leakage-aware, calibrated, reproducible model and then own its path through an API and UI.

## Deliverables

### Mandatory

- versioned shot cohort query, target definition, exclusions, and coverage table;
- documented coordinate/goal geometry with tested distance and visible-angle features;
- non-penalty primary analysis and an explicit penalty policy;
- transparent heuristic/reference-rate benchmark plus logistic-regression baseline;
- one gradient-boosting model compared on the same locked populations/splits;
- feature dictionary with availability time and leakage review;
- match-grouped development validation and one locked temporal holdout;
- Brier score, log loss, ROC AUC and/or PR AUC with class prevalence, calibration curve/table, and uncertainty or fold variability;
- calibration decision tested without fitting on final holdout;
- segment error analysis by at least distance band, angle band, body part, play pattern/set piece, header/non-header, competition/season, and sample-size-aware rare groups;
- reproducible training command, configuration, experiment records, artifacts, plots, and model card;
- tested FastAPI analysis/prediction endpoint with version and feature contract;
- simple web shot map/filter/detail view showing probabilities, actual outcomes, sample sizes, model/data attribution, and limitations;
- release report that compares models honestly and documents intended/non-intended uses.

### Recommended

- bootstrap confidence intervals for selected aggregate metrics;
- reliability table with expected calibration error used cautiously alongside proper scoring rules;
- explainability using logistic coefficients/odds reasoning and constrained model-native importance or SHAP on sampled data;
- model-versus-observed finishing summaries only when minimum-shot uncertainty is visible.

### Optional

- spatial residual heat map; separate headed-shot model experiment; calibrated boosting variant. Do not add neural networks, tracking-derived features, online feature stores, or live retraining.

## Technical work

### WP2.1 — Research question, cohort, and leakage contract (8–12 hours)

Define the primary question: estimate pre-shot goal probability using information available at or before the shot in the selected Open Data scope. Create a shot cohort table/query with one row per shot, immutable source IDs, match date/group, target, and documented exclusions. Report penalties, shootouts, own goals, missing coordinates, and rare categories separately.

Primary evaluation should use non-penalty shots because penalty geometry/context is nearly fixed and can dominate interpretation. Keep penalties visible with a clearly documented empirical or separate-model policy; never silently mix or drop them. Decide whether StatsBomb's supplied xG is excluded from all input features (it should be) and may be used only as an explicitly labelled external comparison if current terms and comparability allow.

For every feature, record when it is known. Exclude outcome, post-shot, provider xG, future match events, and fields derived from the target. Review assists/freeze-frame fields individually rather than assuming they are pre-shot and consistently available.

### WP2.2 — Geometry and feature pipeline (12–16 hours)

Normalize attacking direction and coordinate units. Implement Euclidean distance to goal centre and visible goal angle using a numerically stable two-post formulation. Test central, byline, goal-line, wide, missing, and mirrored examples. Add a deliberately limited set of categorical/context features—body part, technique, play pattern, first time, header, open goal, one-on-one, under pressure, set-piece/cross indicators—only after documenting coverage and semantics.

Fit preprocessing on training data only. Handle missing/unknown categories explicitly. The same feature function and schema must be used in training and serving; version it with the model.

### WP2.3 — Split and evaluation design (10–14 hours)

Lock one final temporal period before comparing models. On the earlier development period, group splits by match so shots from one match never cross folds. Where data permits, use expanding/rolling temporal checks in addition to grouped folds to show season/competition shift. Explain that grouped validation protects shared match context, while temporal validation measures performance on later football/data conditions; neither proves causal generalization.

Choose Brier/log loss as primary probability-quality measures, calibration curves/tables for reliability, and discrimination metrics for ranking. Include naive base-rate and geometry-only baselines. Define how hyperparameters and calibration are selected without touching the final holdout.

### WP2.4 — Logistic baseline (14–18 hours)

Start with distance and angle, then add predeclared context features. Use regularization and a preprocessing pipeline. Inspect signs, magnitudes/odds interpretations, collinearity, convergence, category frequency, and predicted probability distributions. Compare an uncalibrated baseline with any calibration step; logistic regression is not automatically calibrated on shifted data.

Record each material feature-set change as an experiment, not an untraceable notebook branch.

### WP2.5 — Gradient boosting and controlled comparison (12–17 hours)

Choose one maintained gradient-boosting implementation, not a tournament of libraries. Use a small, declared search space within development folds. Compare against the exact same cohort, split IDs, metrics, and slices. Prefer the simpler logistic model if boosting gains are small, unstable, poorly calibrated, or hard to justify. Fit calibration only on an appropriate held-out/calibration fold.

### WP2.6 — Calibration, interpretation, and error analysis (14–18 hours)

Produce reliability plots with bin counts, predicted/observed tables, proper scores, fold dispersion, and the final untouched temporal result. Analyze false/high-confidence errors and segments, always displaying support. Check for systematic shifts across time, competition, shot type, and missingness. Use interpretation to describe association and model behaviour, not causal effects.

Write a model card covering intended use, data, target, exclusions, features, splits, metrics, calibration, ethical/use limitations, monitoring/retraining assumptions, and version.

### WP2.7 — API and web vertical slice (18–23 hours)

Package the selected model and feature metadata together. Provide narrow endpoints such as model metadata/metrics, filtered historical shots, and prediction or analysis for a validated shot input. Return model version and structured errors. Avoid arbitrary user-supplied Python or database query exposure.

Build an accessible pitch/shot-map page with filters, legend, probabilities, outcomes, and a selected-shot explanation. Present model and sample limitations next to results. Prefer server-side aggregate queries and bounded payloads. No authentication or custom design system.

### WP2.8 — Reproducibility and release (12–14 hours)

Train the selected config from a clean data manifest and Git state, validate artifact checksum/metadata, run API/frontend acceptance tests, and reproduce headline metrics within tolerance. Publish the model card, experiment comparison table, report, screenshots/demo, and exact release commands.

## Skills demonstrated

- statistical problem definition and binary classification;
- feature engineering and shared training/serving contracts;
- grouped and temporal model validation;
- leakage prevention, calibration, discrimination, and proper scoring rules;
- interpretable baselines and controlled model comparison;
- reproducible ML engineering and lightweight experiment tracking;
- FastAPI model integration, typed contracts, and frontend visualization;
- football shot-context understanding and responsible claims.

## Learning objectives

Explain or derive without AI:

- how sigmoid/log-odds connect features to logistic-regression probability;
- why maximum likelihood/log loss penalizes confident wrong predictions;
- how distance and visible goal angle are calculated and what edge cases break naive formulas;
- why random row splitting can leak shared match context and misrepresent future performance;
- what grouped validation protects against and what it does not;
- what temporal validation measures, including dataset and football-concept drift;
- data leakage and feature availability at prediction time;
- why discrimination and calibration are different;
- Brier score versus log loss, and why accuracy is weak for probabilistic xG;
- why ROC AUC can look reassuring with imbalanced targets and why prevalence/PR context matters;
- why penalties need an explicit policy;
- regularization, overfitting, bias/variance, and why a complex model may be worse;
- why calibration fitted on the evaluation holdout invalidates that holdout;
- association versus causation in feature interpretation;
- why this model must not be described as StatsBomb's xG model.

## Manual implementation requirements

| Component | Why manual involvement matters | Knowledge built | Sufficient manual level |
|---|---|---|---|
| Cohort/target and leakage table | methodology errors cannot be repaired by model code | prediction timing, exclusions, football semantics | write the cohort SQL and classify every final feature as available/unavailable/uncertain |
| Shot geometry | it is the core domain feature and a common silent bug | coordinate systems, trigonometry, edge cases | derive formulas, implement/rewrite them, calculate five examples by hand, and test mirrors/bounds |
| Logistic baseline | makes probability modelling explainable | sigmoid, odds, likelihood, regularization | implement the pipeline using a library but manually derive/interpret a small coefficient example and debug one fit |
| Split generation | leakage control is a human research decision | grouping, time ordering, selection bias | write/rewrite split code and prove match disjointness and chronological holdout with tests |
| Metric and calibration interpretation | dashboards can hide misleading evaluation | proper scores, reliability, support, uncertainty | manually calculate Brier/log loss on a tiny example and narrate one calibration plot |
| Error analysis conclusion | requires football/statistical judgment | segments, uncertainty, limitations | inspect at least 30 sampled errors and write conclusions before AI editing |

It is sufficient to use scikit-learn/boosting libraries; reimplementing optimizers or trees from scratch is not required.

## AI-agent delegation

Agents may draft preprocessing boilerplate, typed model/config schemas, experiment serializers, plot utilities, boosting search code after the split is locked, API CRUD/validation, UI components, test skeletons, and model-card formatting.

Acceptance protocol:

1. developer approves cohort, target, features, exclusions, groups, cutoff, and metrics before training;
2. tests prove training-only fitting, group disjointness, time ordering, deterministic seeds, and training/serving feature parity;
3. compare generated metric values with a tiny manual or independent calculation;
4. inspect model predictions and plots, not just command exit status;
5. require the agent to state uncertainties and suspected leakage explicitly;
6. make at least one meaningful manual change to geometry, split, evaluation, or API behaviour;
7. conduct a no-agent teach-back before the release claim is used.

## Technical interview readiness

- Why is random shot-level train/test splitting inappropriate here?
- How do match-grouped and temporal validation answer different questions?
- How did you prevent preprocessing leakage?
- Derive or explain your shot distance and angle features.
- Why did you exclude or separately handle penalties?
- What do Brier score and log loss tell you that ROC AUC does not?
- A model has higher AUC but worse calibration—would you deploy it for chance valuation?
- How did you calibrate without contaminating the final holdout?
- Why might logistic regression beat boosting in a production-conscious decision?
- Which model errors were systematic, and how did sample size affect your conclusion?
- How do you ensure API features match training features?
- How would drift show up, and what would trigger retraining?
- How is your xG different from StatsBomb's published field?

## Testing and validation

- **Unit tests:** geometry with hand-computed cases; coordinate orientation; penalty/outcome/cohort rules; category/missing handling; metric calculations; artifact metadata; API input validation.
- **Integration tests:** SQL cohort from fixture database through feature pipeline, model training on deterministic fixture, saved artifact reload, FastAPI endpoint prediction, frontend/API contract.
- **Data-quality tests:** one row per shot/source ID; valid targets/probabilities; coordinate and category coverage; no forbidden features; match dates/groups present; exclusion counts reconciled.
- **Model validation:** base-rate and geometry baselines; grouped folds; locked temporal holdout; Brier/log loss and discrimination; calibration with counts; segment metrics/support; fold or bootstrap variability; leakage checklist.
- **Manual acceptance:** inspect at least 50 mapped shots and 30 high-error cases against source context; verify UI locations/outcomes; try invalid API inputs and empty filters; check attribution/limitations on the page.
- **Reproducibility:** clean run from pinned ingestion manifest/config/commit recreates split IDs, metrics within declared tolerance, plots, and artifact metadata; API returns the reproduced model version.

Model tests check expected relationships and reproducibility, not a magically fixed “good” score. Performance thresholds are set only after baselines and dataset scope are recorded.

## Portfolio artifact

- **English write-up:** “Building and evaluating a leakage-aware shot quality model,” including baseline reasoning, split diagram, calibration, slices, limitations, and model choice.
- **Demo:** 4–6 minute flow from a historical shot map to API response, model card, experiment table, and one revealing error segment.
- **GitHub deliverable:** reproducible config/command, cohort SQL, feature tests, experiment records, model card, API contract, UI, and green validation suite.
- **Draft CV claim:** “Built an end-to-end shot-quality engine on a versioned StatsBomb Open Data cohort, comparing regularized logistic regression with gradient boosting under match-grouped and temporal validation, with calibration/error analysis, FastAPI serving, and a TypeScript shot-map interface.”
- **Interview story (problem–decision–result):** Problem—random split accuracy would overstate how an xG model handles new matches and later seasons. Decision—lock a temporal holdout, group development folds by match, start with geometry/logistic regression, and compare calibration and proper scores before complexity. Result—the selected model has a defensible evidence trail and exposed limitations, then runs unchanged behind the API and UI.

Insert actual cohort sizes and measured metrics only after the final locked run. Never imply club deployment.

## Definition of done

- Cohort, target, exclusions, penalty policy, feature availability, and source coverage are versioned and reconciled.
- Geometry passes hand-derived and automated edge-case tests.
- Match IDs do not cross grouped folds; final holdout is chronologically later and remains untouched until the declared final evaluation.
- Naive, geometry/logistic, and one boosting candidate share identical locked evaluation rows/splits.
- Release table includes Brier, log loss, discrimination, calibration with counts, and at least eight supported error slices.
- Calibration/model selection uses no final-holdout labels; leakage checklist has no unresolved blocker.
- A clean training run reproduces headline metrics within documented tolerance and packages model/version/feature metadata.
- API validates inputs, reports model version, and agrees with offline predictions on golden cases.
- UI accurately plots golden shots and visibly presents attribution, data scope, sample sizes, and limitations.
- Model card, English report, demo, GitHub release, CV claim, and interview story are complete.
- Developer passes a no-AI explanation of geometry, logistic regression, splits, metrics, calibration, model choice, and one failure case.

## Risks and scope cuts

| Risk | Response |
|---|---|
| strong-looking leakage from provider xG/outcome/post-shot data | availability table, forbidden-feature test, code review before fitting |
| too few later-season shots or changed coverage | publish counts, use fewer comparisons, report uncertainty; do not force claims |
| boosting/search consumes the phase | one library, small search, stop after decision-relevant comparison |
| calibration bins tell a misleading story | include counts and proper scores; test alternative binning only as sensitivity |
| UI becomes a design project | one functional shot map and detail panel using simple components |
| training/serving skew | one versioned feature function/schema and golden prediction tests |
| AI writes methodology the developer cannot defend | mandatory derivations, manual split/geometry work, error review, teach-back |

Cut first: SHAP/polish, residual heat maps, extra boosting variants, extra categorical features, additional competitions, personalized finishing analysis, live prediction form. Keep cohort integrity, baselines, grouped/temporal evaluation, calibration, error slices, reproducibility, model card, and the minimal API/UI vertical slice.

## Dependencies

- Phase 1 definition of done and a pinned ingestion manifest;
- typed shot fields, match dates/groups, source identifiers, and verified coordinate convention;
- sufficient shot/goal counts after exclusions, checked before schedule commitment;
- Phase 0 test/CI/config patterns and experiment workflow;
- current StatsBomb attribution implemented in app/report/demo.

## Estimated effort

**100–130 hours / 6–9 weeks.** Suggested allocation: 10 hours research/cohort, 15 geometry/features, 12 splits/metrics learning, 28–35 modelling/evaluation, 18–23 API/UI, 10–15 tests/reproducibility, and 7–10 report/demo. If the phase exceeds nine weeks, ship the calibrated transparent baseline and defer optional boosting interpretation/polish.

