# Phase 5 — Optional Spatial Intelligence

**Status:** optional specialization; not part of the main 8–9 month commitment  
**Estimate:** 80–130 hours, roughly 5–8 weeks at 15–20 hours/week  
**Entry gate:** Phases 0–4 are demonstrable, deployed/documented, and already being used for applications.

## Goals and user value

This phase answers one bounded spatial question using StatsBomb 360 freeze frames, such as: “Does local defensive configuration at the event moment add useful information to pass-risk or pass-value estimates beyond event-only features?” Analysts could inspect pressure, passing lanes, or local superiority around selected events. A football research team benefits from an honest comparison between geometric baselines and learned models under partial-observation constraints.

The phase is not a tracking-data project. StatsBomb 360 supplies selected event-time freeze frames with visible players/areas for some matches; it does not provide continuous trajectories, velocity, full off-camera positions, or guaranteed complete coverage. All language, methods, and evaluation must respect that boundary.

## Deliverables

### Mandatory if the phase starts

- go/no-go research protocol with one primary question, user decision, success metric, comparison baseline, time box, and explicit stopping rule;
- current source/licence/attribution review plus 360 coverage and missingness inventory by competition/season/match/event type;
- documented freeze-frame parser preserving event links, teammate/opponent flags, keeper flag, visible-area geometry where available, and coordinate orientation;
- visual audit tool or notebook for overlaying freeze-frame points/visible area on a pitch;
- explicit observation model: which player locations are visible, which are absent/unknown, and which features require exclusions;
- tested classical geometric features relevant to the chosen question;
- simple event-only baseline, geometry-enhanced baseline, and at most one ML comparison on identical grouped/temporal splits;
- calibration/proper scoring and segment/coverage analysis if the target is probabilistic;
- ablation proving the incremental value—or lack of value—of 360 features over event-only inputs;
- robustness checks for player visibility, sparse frames, event type, pitch region, competition/season, and feature parameters;
- bounded platform visualization and English research note with strong limitations;
- explicit decision on whether the spatial method merits continued work.

### Candidate feature families (select only those needed)

- nearest-defender distance and defenders within declared radii;
- pressure cones based on distance/angle, clearly labelled as a proxy;
- passing-lane openness using distance to a finite pass segment/corridor;
- local numerical superiority in declared regions;
- teammate/opponent density using counts or simple kernels;
- approximate static control surfaces with stated speed/reaction assumptions;
- pass-risk/pass-value features combining event context with the above.

### Optional

- compare two classical control-surface assumptions; one interpretable boosted model; interactive visible-frame overlay. A graph neural network remains prohibited unless the entry criteria under “Risks and scope cuts” are later met through a separate ADR.

## Technical work

### WP5.0 — Go/no-go gate (4–6 hours)

Confirm the core portfolio is complete and gather current 360 file/event coverage. Select one question whose labels and baselines are supported. Define minimum sample/coverage, target event types, evaluation split, primary metric, expected analyst value, and a 5–8 week stop point. If coverage or label quality fails the threshold, publish a short feasibility note and stop the phase.

### WP5.1 — Rights, parsing, and coverage (10–16 hours)

Recheck official terms and document selected 360 scope. Parse frames into event-player observations and visible-area polygons while preserving raw/source IDs. Reconcile frame/event counts, teammate/opponent/keeper markers, coordinates, duplicates, and nulls. Overlay at least 30 frames across pitch regions/event types and compare against raw JSON. Treat players outside the frame/visible area as unknown, never absent by default.

### WP5.2 — Geometric definitions and toy validation (16–24 hours)

Choose the minimum relevant features. Define every formula, units, direction, thresholds, and edge behaviour before scaling up. Examples: point-to-segment distance for lane obstruction; count/density within radius; angular defender cones; kernel density; static arrival-time approximation. Verify each on hand-drawn synthetic scenes including no defenders, collinear points, endpoints, duplicates, boundary positions, missing keeper, and partial visible area.

Do not call a radius count “pressure” without labelling it an estimate. Do not infer velocity, orientation, intent, or unseen player location from a single frame unless a validated proxy and uncertainty are explicit.

### WP5.3 — Baseline and experiment design (10–14 hours)

Build the event-only baseline first on the exact 360-eligible population; do not compare it with a model trained on a broader population. Add geometric features in a predeclared order. Group by match and hold out later time where coverage permits. Track coverage-induced selection: 360-available events may not represent general events.

Choose a target tied to the question, such as pass completion or a bounded downstream value label, and list leakage fields. For probabilistic targets, use Brier/log loss, calibration, and discrimination; for continuous targets, define scale-aware error and uncertainty. Report sample support.

### WP5.4 — Classical/ML comparison and robustness (18–27 hours)

Start with a simple logistic/linear or rule-based model. Add at most one gradient-boosting comparison after the baseline is stable. Run ablations: event-only versus +geometry, individual feature families, and at least two plausible geometric parameter values. Examine feature effects and errors by visibility/coverage, pass length/direction, pitch region, event type, competition/season, and player density.

Improvement must be stable enough to justify added data and operational complexity, not merely positive on one fold. A null result is a valid portfolio result if the protocol and analysis are strong.

### WP5.5 — Visualization, integration, and report (14–20 hours)

Add one drill-down view that overlays visible players/area and chosen geometry on an event, plus aggregate model/ablation results. Reuse the platform API, database, styles, deployment, and experiment infrastructure. Publish limitations next to the visualization. Write the report around the research question and incremental evidence—not a catalog of spatial features.

### WP5.6 — Stop/continue decision (8–12 hours)

Reproduce the final run, review the predefined success rule, and decide: stop with a negative/null result, retain the classical feature module, or propose one follow-up. A graph method may only be proposed after simple baselines, measured incremental value, sufficient sample/coverage, an interaction-based research hypothesis, a valid evaluation target, and a separate accepted ADR estimating complexity.

## Skills demonstrated

- partial-observation and spatial-data reasoning;
- computational geometry and robust feature implementation;
- coverage/missingness analysis and selection-bias awareness;
- controlled baseline/ablation evaluation;
- calibration or regression validation under grouped/temporal splits;
- research scoping, null-result communication, and complexity justification;
- integration of a specialist module into an existing product.

## Learning objectives

Explain without AI:

- exactly what a 360 freeze frame contains and why it is not continuous tracking;
- missing, outside-visible-area, and truly absent as different states;
- point-to-segment distance, angular cones, local density, and any control-surface assumptions used;
- why a static frame cannot reliably provide velocity, orientation, or intent;
- how 360 availability can cause selection bias;
- why the event-only baseline must use the same 360-eligible population;
- what grouped/temporal validation protects in spatial modelling;
- how an ablation tests incremental information rather than absolute model quality;
- why feature thresholds/grid/kernel choices require sensitivity analysis;
- what evidence would and would not justify a graph neural network;
- why a well-supported null result demonstrates research skill.

## Manual implementation requirements

| Component | Why manual involvement matters | Knowledge built | Sufficient manual level |
|---|---|---|---|
| 360 coverage/visual audit | model code cannot reveal observation misunderstandings | partial coverage, visible area, source skepticism | inspect/annotate 30 frames and write the observation rules |
| Core geometry | incorrect geometry creates plausible but false features | vectors, distances, angles, boundaries | derive and implement/rewrite each retained feature; solve at least five scenes by hand |
| Research question and ablation | complexity must answer a decision | experimental control, incremental value | write protocol and lock comparisons before final runs |
| Robustness/error review | spatial proxies fail contextually | selection bias, sensitivity, football interpretation | personally inspect 30 errors/extremes across declared segments |
| Stop/continue decision | prevents optional research from expanding indefinitely | evidence-based scope control | author the decision against predeclared thresholds before AI editing |

Manual implementation of rendering boilerplate or numerical linear-algebra primitives is not required.

## AI-agent delegation

Agents may draft parsers/mappings after source inspection, vectorized geometric functions after formulas are written, plot layers, API/UI scaffolds, experiment/test parameterization, and report formatting. They may propose graph models only to evaluate against the explicit gate, not add one.

Review protocol:

1. validate every generated spatial feature on synthetic and visual golden scenes;
2. distinguish unknown/unseen from absent in types, features, UI, and copy;
3. lock identical eligible populations/splits before comparing feature sets;
4. test geometry invariance/direction and parameter sensitivity;
5. inspect raw frames and predictions, not just aggregate metrics;
6. make at least one manual correction to geometry/coverage/evaluation;
7. require a no-AI explanation and a written stop decision.

## Technical interview readiness

- What information does StatsBomb 360 provide, and what tracking questions can it not answer?
- How did you represent players outside the visible area?
- Derive your passing-lane openness or nearest-defender feature.
- How did you validate coordinate direction and geometric edge cases?
- Why did the event-only baseline use only 360-eligible events?
- How did coverage affect selection bias and external validity?
- Which 360 feature added stable value after ablation?
- How sensitive were results to radii/grid/kernel assumptions?
- Why did you choose a classical baseline over a graph neural network?
- What evidence would justify adding a GNN later?
- Describe a null or failed spatial hypothesis and what you learned.

## Testing and validation

- **Unit tests:** frame mapping, visible-area geometry, coordinate direction, point/segment/cone/density/control formulas, missing/unseen handling, parameter boundaries.
- **Integration tests:** source event + 360 frame through PostgreSQL/features/model/API/overlay; golden scene rendered with expected points/geometry.
- **Data-quality tests:** unique event-player frame rows; frame/event reconciliation; coordinate/flag validity; visible-area presence/shape; target-feature alignment; coverage/missingness tables.
- **Model validation:** identical eligible populations and grouped/temporal splits; simple baseline; 360 incremental ablations; calibration/proper scores or justified regression metrics; support and fold variation; parameter/coverage sensitivity.
- **Manual acceptance:** inspect 30 raw overlays and 30 errors/extremes; verify unknown players are not visualized as absent; test sparse/empty frames and attribution/limitations.
- **Reproducibility:** clean run from pinned source/commit/config recreates coverage, golden geometry, split IDs, metrics within tolerance, plots, and deployed method version.

## Portfolio artifact

- **English write-up:** “What freeze frames add—and do not add—to [chosen pass-risk/value question],” including coverage, geometry, ablations, nulls, and limitations.
- **Demo:** overlay one event, explain a geometric feature, then show event-only versus 360 ablation and an error case.
- **GitHub deliverable:** feasibility protocol, coverage report, tested geometry, locked experiment configs/results, integrated view, and stop/continue decision.
- **Draft CV claim:** “Evaluated the incremental value of StatsBomb 360 freeze-frame geometry for a bounded [pass-risk/value] question, implementing tested classical spatial features and comparing event-only and spatial models under match-grouped/temporal validation with coverage and sensitivity analysis.”
- **Interview story (problem–decision–result):** Problem—freeze-frame data invited tracking-like claims and unnecessary graph complexity. Decision—inventory partial coverage, define an observation model, validate simple geometry on synthetic scenes, and require an event-only ablation. Result—the project established whether 360 features added stable decision value and stopped or continued based on evidence rather than novelty.

Replace the bracketed question and add actual results only after the go/no-go protocol and final run.

## Definition of done

- Main portfolio was already application-ready before Phase 5 began.
- One research question, baseline, metric, minimum support, time box, success rule, and stopping rule were fixed at the gate.
- Current 360 rights/attribution and coverage were reviewed and published; all claims say freeze frame, not tracking.
- Thirty varied frames were visually audited; unknown/out-of-view semantics are explicit.
- Every retained geometry feature passes hand-worked synthetic and automated edge cases.
- Event-only and spatial models use identical eligible rows/splits; leakage review is resolved.
- At least one grouped/temporal comparison, incremental ablation, coverage/error analysis, and parameter sensitivity is complete.
- Results include support/variation and may honestly conclude no useful improvement.
- Integrated visualization exposes visible area, method/data versions, assumptions, and limitations.
- Clean reproduction, report, demo, GitHub release, CV claim, interview story, and explicit stop/continue decision exist.
- No graph neural network was added without all evidence gates and a separate ADR.

## Risks and scope cuts

| Risk | Response |
|---|---|
| coverage is too small or selective | enforce go/no-go minimum and publish feasibility note instead of forcing a model |
| frames are mistaken for tracking | observation-model tests and explicit UI/report language |
| geometric proxies overclaim pressure/control | name them proxies, show assumptions, run sensitivity/error cases |
| GNN novelty distracts from question | prohibit until classical incremental value and interaction hypothesis exist |
| optional phase delays applications | entry gate requires applications/core maintenance already active |
| many spatial ideas become a feature catalog | one primary question and only required features |
| agent-generated geometry appears plausible | toy scenes, manual derivations, visual overlays, invariance tests |

Cut first: interactive polish, extra feature families, boosting, control surfaces, extra competitions, player aggregates. Then narrow to one event type and one geometry family. Stop entirely with a documented feasibility/null report if coverage or stable incremental evidence is insufficient.

A graph neural network is considered only if: the core portfolio is complete; the research question depends on interactions a simpler representation cannot express; classical/rule/boosted baselines exist; data/coverage is adequate; a locked evaluation can measure incremental value; and an ADR justifies complexity and time. “Players form a graph” is not enough.

## Dependencies

- Phases 0–4 meet their public-release definitions of done;
- job applications and core portfolio maintenance are not waiting on this module;
- a current 360 coverage inventory supports the chosen target and split;
- event/action source links, coordinate conventions, experiment workflow, API/UI, and deployment are stable;
- current StatsBomb terms permit the intended use/publication with implemented attribution.

## Estimated effort

**80–130 hours / 5–8 weeks after the main plan.** Allocate 4–6 hours to the gate, 10–16 coverage/parsing, 16–24 geometry, 10–14 experiment design, 18–27 modelling/robustness, 14–20 integration/report, and 8–12 reproduction/decision. If the gate fails, stop after roughly 8–15 hours with a credible feasibility note.
