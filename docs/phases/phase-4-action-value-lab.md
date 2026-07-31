# Phase 4 — Action Value Lab

**Estimate:** 105–140 hours, roughly 7–10 weeks at 15–20 hours/week  
**Release:** reproducible research module comparing action-value methods  
**Portfolio state:** main 8–9 month portfolio is complete after this phase and consolidation.

## Goals and user value

Action Value Lab estimates how on-ball actions change a team's likelihood of scoring or conceding. It moves analysis beyond shots while keeping assumptions, possession logic, model comparisons, and discrepancies inspectable. Analysts can explore where and how actions create or destroy value; a research team gains a reproducible baseline for evaluating methods, not an unexplained universal player ranking.

The learning goal is paper-to-code research engineering: understand a method, define a compatible data representation, reproduce it, compare with a trusted implementation such as `socceraction`, investigate disagreement, and communicate uncertainty.

## Deliverables

### Mandatory

- research protocol naming questions, papers/reference versions, dataset manifest, compatible scope, success tolerances, and non-goals;
- canonical ordered action representation with source-event links and documented coordinate, direction, period, outcome, and action-type semantics;
- deterministic possession/sequence segmentation with at least 20 hand-annotated edge cases and discrepancy log;
- transparent grid-based Expected Threat (xT) baseline with move/shot transitions, scoring probability, convergence/fit checks, and value maps;
- xT action values and aggregate examples with exposure/context warnings;
- written VAEP study notes explaining states, labels, scoring/conceding probabilities, horizon, and offensive/defensive value;
- bounded, reproducible VAEP implementation using versioned features/labels/splits/models;
- independent `socceraction` reference run on the exact same compatible match/action subset and library version;
- row/action alignment report, metric/output comparison, tolerance definitions, and investigated discrepancy categories;
- grouped/temporal evaluation, calibration and proper scores for component probability models where applicable;
- at least two ablations or sensitivity tests (for example history length, feature family, grid resolution, possession rule, or model class);
- action, zone, possession, and player/team aggregate visualizations with sample/exposure context;
- API/UI integration as an “Action Value Lab” module reusing the platform rather than a separate app;
- English research report, reproducibility appendix, experiment records, limitations, and reference citations.

### Recommended

- uncertainty/stability across seasons or bootstrap resamples;
- provenance view linking an aggregate/value back to source actions;
- profiling of conversion/training/runtime bottlenecks.

### Optional

- alternative xT resolution/smoothing; additional interpretable classifier; carefully scoped off-ball contextual feature if available. Do not pursue real-time valuation, reinforcement learning, neural sequence models, or a claim of causal player contribution.

## Technical work

### WP4.1 — Research protocol and reference environment (8–12 hours)

Read the original VAEP paper/material, current `socceraction` documentation/source relevant to StatsBomb/SPADL and VAEP, and at least one xT methodological reference. Record exact citations and package versions. Define what “reproduce” means: shared input/action subset, aligned semantics, component probabilities and/or action values within justified tolerances, plus explained deviations. Pin a small reference subset before building.

List threats: provider conversion differences, action taxonomy, period boundaries, coordinates, scores, own goals, missing/duplicate events, reference-version changes, and random model variance. The goal is reproducibility and discrepancy understanding, not byte-for-byte identity when methods differ.

### WP4.2 — Canonical actions and possession segmentation (18–24 hours)

Convert source events into ordered on-ball actions with stable source links, start/end locations, team/player, action/result/body-part categories, period/time, score state, and attacking direction. State which events are omitted, merged, or synthesized. Ensure no sequences cross matches or periods incorrectly.

Define possession/sequence boundaries using explicit rules for team change, controlled/uncontrolled outcomes, restarts, fouls, shots, goalkeeper actions, out-of-play, contested events, and period ends. Compare available provider possession IDs with the custom definition; do not treat either as unquestioned truth. Hand-label at least 20 sequences including ambiguous transitions and maintain disagreement categories.

### WP4.3 — Expected Threat baseline (14–19 hours)

Discretize the pitch using a modest fixed grid. Estimate state-conditioned shot/move choices, goal probability after shots, and move transition probabilities from training data. Solve or iterate the Bellman-style equation to convergence, guarding empty/sparse cells. Value successful moves by change in xT, document policy for unsuccessful moves and shots, and keep train/evaluation populations separate.

Test toy grids where values can be calculated manually. Plot counts and uncertainty/sparsity beside the value surface. Examine grid-resolution sensitivity; avoid interpreting cell artifacts as football truth.

### WP4.4 — VAEP implementation (22–30 hours)

Define game states as a bounded history of actions and build features for action type/result/body part, location/movement, time, score, teams, and recent context, matching the studied formulation where possible. Define future scoring and conceding labels over the chosen action horizon without crossing match boundaries or leaking future features. Generate grouped and temporal splits.

Train transparent component classifiers first; evaluate discrimination, Brier/log loss, calibration, temporal shift, and class balance. Calculate offensive/defensive/total action value from changes in scoring/conceding probabilities, handling possession/team perspective carefully. Store action-level lineage and aggregate only after validating sign and units.

### WP4.5 — Trusted-reference comparison (16–22 hours)

Run `socceraction` independently on the same pinned source/reference subset. Align match/action keys, taxonomy, coordinates, chronological order, feature/label rows, model configuration where supported, and exclusions. Build a comparison funnel: source events → converted actions → eligible states → labelled samples → scored actions. At every stage report matched/unmatched counts.

Compare exact categorical mappings, feature samples, label prevalence, component probabilities/metrics, and final action values. Classify differences as input conversion, possession/action semantics, feature/label logic, model/stochastic variation, version difference, or defect. Fix confirmed defects; document intentional differences. Never change tolerances after seeing results without explaining why.

### WP4.6 — Ablations, aggregation, and visualizations (12–16 hours)

Run at least two experiments that answer a real decision, such as whether longer action history, score context, a finer xT grid, or a more complex classifier adds stable value. Preserve the simple baseline. Visualize individual possessions/action trails, xT surface, positive/negative action examples, distributions, and exposure-aware aggregates. Avoid league tables that imply causal player quality; show minutes/actions and uncertainty/stability.

### WP4.7 — Platform integration and report (15–17 hours)

Add bounded endpoints for model/method metadata, value surfaces, action/possession drill-down, and aggregated views. Integrate one frontend module using existing navigation, contracts, and attribution. Write the research report with methods, assumptions, reference protocol, discrepancies, ablations, limitations, and reproducibility commands. Record a demo centred on one research finding and one disagreement investigation.

## Skills demonstrated

- paper reading and reproducible research engineering;
- event-to-action conversion and possession/domain modelling;
- Markov/state-value reasoning and Expected Threat;
- supervised temporal labels, calibration, and action valuation;
- independent reference implementation comparison and discrepancy diagnosis;
- ablation/sensitivity analysis and experimental traceability;
- analytical visualization and integration into a production-conscious data product;
- careful distinction between model value, observed outcome, and causal contribution.

## Learning objectives

Explain from first principles without AI:

- why event order, action taxonomy, and possession definition affect every action-value result;
- how a grid xT model estimates shot/move/goal/transition probabilities and solves for state value;
- assumptions behind treating pitch cells as states and historical transitions as policy/environment evidence;
- how VAEP represents game states and defines scoring/conceding labels over a future horizon;
- how changes in scoring and conceding probability become offensive, defensive, and total action value;
- where label leakage can enter sequential football modelling;
- why matches must remain grouped and time order still matters;
- why component probability calibration affects differences in value;
- the difference between reproducing a method, matching one library, and validating football usefulness;
- how to diagnose discrepancies systematically rather than tune until outputs match;
- what an ablation can and cannot establish;
- why aggregated action value is not automatically causal player quality or recruitment value.

## Manual implementation requirements

| Component | Why manual involvement matters | Knowledge built | Sufficient manual level |
|---|---|---|---|
| Paper/method derivation notes | a library call is not research reproduction | states, labels, value equations, assumptions | write a 2–4 page derivation with a toy example before implementation |
| Possession/action rules | source semantics and edge cases determine results | event sequencing, football restarts/control | define rules, annotate 20 sequences, implement/rewrite boundary state machine |
| xT toy implementation | exposes the mechanics hidden by packages | transition matrices, iteration, convergence | implement a small grid from counts and solve/test by hand; production may be vectorized with libraries |
| VAEP features/labels/value | highest leakage and sign risk | sequential labels, team perspective, probability changes | personally write/rewrite core label/value functions and golden sequence tests |
| Reference alignment investigation | matching requires judgment, not code generation | reproducibility, differential debugging | manually trace at least ten first-divergence cases and classify causes |
| Ablation conclusion | prevents metric collecting without decisions | controlled experiments and limitations | state hypothesis before each run and author adopt/reject conclusion |

Reimplementing gradient-boosting internals is not required. Using `socceraction` as the production implementation alone is insufficient for the learning goal.

## AI-agent delegation

Agents may draft conversion mappings after rules are defined, vectorized feature code, experiment plumbing, plot/UI/API scaffolds, differential comparison utilities, fixtures, and report formatting. Agents can explain papers as a secondary aid but must not substitute for reading cited material.

Review protocol:

1. pin paper/reference/library/source versions and record any ambiguity;
2. approve action, possession, feature, label, horizon, split, and value definitions before broad runs;
3. use tiny hand-worked sequences and toy grids to verify generated code;
4. prohibit future-row access outside label construction and test match/period boundaries;
5. compare intermediate representations, not only final correlations;
6. inspect the first divergence rather than accepting a high average match rate;
7. make a meaningful manual correction or methodological change and document it;
8. require a no-AI whiteboard explanation of xT, VAEP, discrepancies, and limitations.

## Technical interview readiness

- How did you define possession, and where does it disagree with provider IDs?
- Derive the core xT update and explain its assumptions.
- How do grid size and sparse cells affect xT?
- What is a VAEP game state, and how are scoring/conceding labels created?
- How do you prevent future-action leakage?
- Why does probability calibration matter for action values?
- How do offensive and defensive VAEP components handle team perspective?
- What did you compare with `socceraction`, and what did “matching” mean?
- Walk through a discrepancy from source event to final action value.
- Why might two correct implementations disagree?
- Which ablation changed your decision and which did not?
- Why should a scout not interpret total action value as causal player talent?
- What engineering choices made the research reproducible and product-integrated?

## Testing and validation

- **Unit tests:** event ordering; coordinate direction; action mapping; possession boundaries; score state; toy xT transitions/convergence; feature history boundaries; future labels; value sign/team perspective; aggregate denominators.
- **Integration tests:** fixture match from PostgreSQL events to actions/possessions/xT/VAEP; experiment config to artifact; API/UI golden possession; independent reference pipeline on the pinned subset.
- **Data-quality tests:** unique/stable action IDs; monotonic order within match/period; coordinate bounds; no cross-match histories; source/action reconciliation; possession start/end coverage; label prevalence; matched-reference funnel counts.
- **Model validation:** grouped/temporal component metrics, Brier/log loss, calibration, prevalence, stability; xT held-out likelihood/value sanity; ablations with locked splits; support-aware aggregates.
- **Manual acceptance:** review 20 annotated possessions, 30 high/low value actions, xT sparse cells, ten first-divergence cases, and UI source drill-down; verify attribution/citations/limitations.
- **Reproducibility:** from pinned manifest/commit/config and exact reference version, regenerate action counts/hashes, experiment metrics within tolerance, reference comparison report, plots, and API version metadata.

Reference agreement is not the only validation. A shared bug or shared data assumption can still produce matching output.

## Portfolio artifact

- **English write-up:** a substantive research report, “Reproducing and stress-testing action-value models on StatsBomb Open Data,” with methods, reference funnel, discrepancies, ablations, and limitations.
- **Demo:** 6–8 minute narrated action/possession walkthrough plus one differential-debugging case and integrated UI.
- **GitHub deliverable:** versioned conversion, possession tests, xT/VAEP configs, reference adapter/comparison, ablations, report, and reproducibility appendix.
- **Draft CV claim:** “Reproduced xT and a bounded VAEP pipeline on versioned football event data, validating sequential labels and calibrated component models with grouped/temporal splits, then comparing action-level outputs against a pinned `socceraction` reference and documenting discrepancies and ablations.”
- **Interview story (problem–decision–result):** Problem—an action-value implementation could look plausible while differing because of hidden conversion, possession, or label semantics. Decision—pin a reference subset, validate toy cases, compare each intermediate stage with `socceraction`, and classify first divergences. Result—the integrated module has an auditable reproduction boundary, confirmed fixes, documented intentional differences, and evidence about which added complexity mattered.

Use actual alignment rates, discrepancies, and model metrics only after the final report.

## Definition of done

- Research question, citations, source/reference versions, success tolerances, and non-goals are recorded before final experiments.
- Canonical actions reconcile to source through a documented funnel and pass ordering/direction/type tests.
- Possession rules pass 20 annotated edge cases; unresolved ambiguous categories are reported.
- xT reproduces hand-worked toy values, converges under a documented rule, exposes counts/sparsity, and passes resolution sensitivity.
- VAEP feature/label histories never cross matches; future labels and team-perspective value signs pass golden tests.
- Component models have grouped/temporal, proper-score, discrimination, calibration, and prevalence evidence.
- The same compatible subset runs independently through `socceraction`; matched/unmatched counts and discrepancy categories are published.
- At least ten first divergences are traced and every material difference is fixed or explicitly justified.
- At least two predeclared ablations end in adopt/reject/inconclusive decisions.
- API/UI integrate into the existing platform and link values back to actions, scope, method version, support, and limitations.
- Clean reproduction creates materially equivalent outputs within justified tolerances.
- Research report, demo, GitHub release, CV claim, and interview story are complete, and the developer can defend the method unaided.

## Risks and scope cuts

| Risk | Response |
|---|---|
| possession/action conversion consumes the phase | freeze a compatible action subset and publish exclusions before adding breadth |
| reference version/API changes | pin environment and source commit; compare through a small adapter |
| attempting exact identity despite semantic differences | define intermediate tolerances and intentional-difference categories up front |
| label leakage across action histories/matches | boundary tests, feature-availability review, manual golden sequences |
| sparse positives or cells make metrics unstable | report prevalence/support, simplify features/grid, aggregate carefully |
| action-value leaderboard is mistaken for talent | show exposure/context and use case-level drill-down; avoid recruitment claim |
| AI paraphrases papers inaccurately | read/cite primary material and derive toy cases manually |
| schedule reaches month nine | preserve xT plus bounded VAEP/reference comparison; cut UI and extra experiments |

Cut first: UI polish, multiple classifiers, fine grids, extended competitions, advanced uncertainty, extra aggregate leaderboards, additional possession variants. Then restrict VAEP/reference work to a smaller compatible subset. Keep paper study, manual possession cases, toy xT, leakage-safe labels, one reference comparison, two small ablations, and the research report. If necessary, label VAEP “bounded reproduction” rather than overstating completeness.

## Dependencies

- Phase 1 stable event/lineup schema, ordering, source provenance, and relevant event fields;
- Phase 2 experiment, split, calibration, artifact, API, and model-card patterns;
- Phase 3 deployed platform stable enough that research work will not break the public portfolio;
- viable shared match subset supported by both the local converter and pinned `socceraction` reference;
- primary methodological sources and current dependency documentation;
- current StatsBomb attribution/usage review.

## Estimated effort

**105–140 hours / 7–10 weeks.** Approximate allocation: 10–14 hours reading/protocol, 18–24 conversion/possession, 14–19 xT, 22–30 VAEP, 16–22 reference comparison, 10–14 ablations/visuals, and 10–17 integration/report. The upper range is genuinely uncertain because conversion mismatches are research findings; scope the subset before sacrificing validation.

