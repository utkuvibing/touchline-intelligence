# Phase 3 — Scout Explorer

**Estimate:** 100–135 hours, roughly 6–9 weeks at 15–20 hours/week  
**Release:** deployed analyst workflow for contextual player search and comparison  
**Application milestone:** recommended broad portfolio release.

## Goals and user value

Scout Explorer helps an analyst form and investigate a shortlist using transparent, contextual player evidence. It answers “who matches this role and comparison population?” rather than claiming to replace live scouting. Users can filter players, compare per-90 and selected possession-adjusted metrics, inspect percentiles, find explainable similar profiles, and export a reproducible report.

A football organization benefits from faster initial screening, consistent comparison cohorts, visible data coverage, and auditable calculations. The developer learns how data products turn ambiguous football language into defensible definitions and usable interfaces.

## Deliverables

### Mandatory

- tested player-minute and appearance logic covering starts, substitutions, extra time, and documented dismissal/data edge cases;
- versioned player-season/team aggregation query with one declared grain;
- metric dictionary with numerator, denominator, direction, inclusion rules, limitations, and source coverage;
- per-90 metrics used only where rate interpretation is meaningful;
- minimum-minute rule with visible excluded-player counts and sensitivity example;
- documented position and role cohort taxonomy, including multi-position handling;
- comparison population encoded in every percentile result;
- percentile calculations with directionality and deterministic ties/null handling;
- no more than 10–15 carefully chosen first-release metrics;
- possession-adjusted metrics only where a football rationale and denominator validation exist;
- role-aware similarity baseline with fixed feature set, scaling, missing-data, weighting, and distance definition;
- similarity explanations showing strongest agreements/differences and cohort/sample context;
- FastAPI endpoints for filters, player profile/comparison, similarity, and report generation;
- Next.js filtering, profile, side-by-side comparison, percentile visualization, and similarity interface;
- reproducible PDF scouting report containing data scope, cohort, timestamp/version, metrics, caveats, and StatsBomb attribution;
- one usable deployment with smoke checks, typed configuration, basic logs, and documented rollback/rebuild steps.

### Recommended

- cohort/threshold sensitivity view;
- shareable URL state for filters/comparisons;
- simple caching after measuring repeated query latency;
- glossary/tooltips and mobile-readable report layout.

### Optional

- saved shortlists without complex authentication; richer radar alternatives; team-style context. Do not build recruitment recommendations, market valuation, injury prediction, or automated “best player” rankings.

## Technical work

### WP3.1 — Scouting questions and metric contract (8–12 hours)

Define two or three realistic tasks, such as finding progressive wide players in a league/season or comparing ball-winning midfield profiles. Interview substitutes may be written analyst scenarios if no professional user is available. For each metric, document event definition, grain, denominator, preferred direction, minimum support, and known context dependence. Separate observable output from evaluative claim.

### WP3.2 — Minutes, positions, and aggregation (16–21 hours)

Calculate match intervals/playing time from lineups, substitutions, periods, extra time, and dismissals where reliably available. Reconcile team/player minutes and manually inspect edge cases. Choose player-team-season as the first-release grain so transfers are not silently merged; offer a clearly labelled combined view only if needed.

Aggregate 10–15 metrics with consistent SQL grain. Use per-90 only for count-like events whose opportunity interpretation is defensible. Report raw totals and minutes alongside rates. Do not label provider events as universal football truth.

### WP3.3 — Cohorts, thresholds, and percentiles (12–16 hours)

Map observed positions into a small written taxonomy; handle multiple positions using minutes or a declared primary-role rule. Define cohort keys such as competition, season, role, and minimum minutes. Compute percentiles only within a named cohort and include cohort size, date/data version, and metric direction. Test tie and null handling. Show how changing the threshold/population moves at least one player’s percentile.

### WP3.4 — Possession adjustment (8–12 hours)

Start unadjusted. For selected defensive/off-ball counts, define a team/opponent possession opportunity proxy from available event data and state its limitations. Validate unit, direction, and extreme cases. Include both adjusted and unadjusted values; drop the adjustment if it adds ambiguity without decision value.

### WP3.5 — Explainable role-aware similarity (15–20 hours)

Build one transparent baseline: select role-specific features, orient them, transform/skew-check if necessary, scale using only the comparison cohort, apply documented weights (initially equal unless user research justifies otherwise), and calculate a common distance/cosine score. Exclude identity and target player from candidates. Require sufficient minutes and feature completeness.

Return similarity score/rank with cohort, feature contributions or standardized gaps, and warnings. Evaluate through known-player sanity cases, perturbations, stability across thresholds/seasons, and qualitative football review—not a fabricated ground-truth accuracy metric. Avoid clustering unless it answers a separate documented question.

### WP3.6 — API and analyst interface (18–24 hours)

Create paginated/filterable endpoints with constrained sort/filter fields, profile comparison, similarity, metadata/glossary, and report requests. Measure query latency before indexes/caching. Prevent SQL injection through parameterized/validated query construction.

Build a workflow: define context → filter candidates → inspect profile → compare two players → request similar profiles → export. Prefer clear dot/range/bar displays over radar charts that obscure scale; if a radar is used, make cohort and direction explicit. Support empty/small cohorts and loading/error states.

### WP3.7 — PDF and deployment (13–18 hours)

Generate PDF from the same versioned data contract as the UI. Include player/team/season, minutes, selected cohort and size, metric definitions, percentiles, similarity explanation where relevant, generated date, dataset/model/code version, limitations, and attribution. Test text overflow and missing values.

Deploy one backend, frontend, and PostgreSQL using the simplest viable provider/approach selected near this work package. Apply migrations, seed a bounded public dataset, configure secrets, add structured application logs/request IDs, health/readiness endpoints, smoke test, and basic backup/rebuild documentation. No Kubernetes or multi-cloud.

### WP3.8 — Product validation and release (10–12 hours)

Have at least two reviewers (football-aware peers if possible) attempt the written scenarios without guidance. Record confusion and task completion, fix only high-impact issues, reproduce a report from clean data, and publish a narrated demo, limitations, CV claim, and interview story.

## Skills demonstrated

- analytical SQL, player aggregation, and denominator design;
- football metrics, roles, and contextual reasoning;
- statistical standardization, percentiles, similarity, and sensitivity;
- explainable ranking/retrieval rather than black-box recommendation;
- API/query design, TypeScript product delivery, and PDF generation;
- deployment, migrations, configuration, logging, and smoke testing;
- analyst-centred product thinking and responsible decision support.

## Learning objectives

Explain without AI:

- why player minutes and transfers determine aggregation grain;
- when per-90 rates are meaningful and when opportunity/context breaks them;
- how minimum-minute thresholds trade sample reliability against selection bias;
- why a percentile has no meaning without its comparison population;
- how ties, skew, direction, and cohort size affect percentile interpretation;
- what possession adjustment tries to control and why event-based possession is imperfect;
- how standardization, feature selection, weighting, and distance shape “similarity”;
- why nearest does not mean equally good, transferable, affordable, or recruitable;
- how to evaluate similarity when no labelled ground truth exists;
- why deployment migrations/config/logs matter even for a portfolio product;
- why an attractive scouting report can still mislead without version, definitions, support, and caveats.

## Manual implementation requirements

| Component | Why manual involvement matters | Knowledge built | Sufficient manual level |
|---|---|---|---|
| Minutes calculation and reconciliation | wrong exposure corrupts every per-90 result | event/lineup timelines, intervals, edge cases | write/rewrite interval SQL/Python, hand-check five matches including substitutions/extra time |
| Metric dictionary and aggregation SQL | definitions are the product | grain, denominators, football interpretation | author definitions and core query for at least eight metrics before AI review |
| Cohort/percentile calculation | contextual comparison is central to honest scouting | populations, ranks, ties, sensitivity | implement/rewrite calculation and manually verify a small ordered example |
| Possession adjustment | easy to cargo-cult a formula | opportunity adjustment and assumptions | derive one adjustment, validate extremes, and decide whether evidence supports keeping it |
| Similarity baseline | feature/weight choices encode judgment | scaling, distance, explanation, evaluation without labels | implement a small version from formulas, then use libraries for production; run perturbation cases |
| User review synthesis | agents cannot substitute for analyst confusion | product discovery and prioritization | observe two scenario attempts and personally choose fixes/cuts |

Manual work need not include hand-coding PDF layout engines or every UI control.

## AI-agent delegation

Agents may draft aggregation scaffolds after definitions, CRUD/filter endpoints, SQL query builders, TypeScript components, charts, PDF templates, deployment configuration, logging middleware, fixtures, and test parameterization.

Review protocol:

1. human approves every metric definition, cohort, threshold, feature, weight, and label;
2. generated queries are checked for grain multiplication, parameterization, nulls, and transfer handling;
3. calculations are compared with small manual examples and independent SQL/Python checks;
4. UI copy avoids causal, qualitative, or recruitment claims unsupported by data;
5. PDFs are visually inspected from golden cases and missing/extreme cases;
6. deployment secrets/logs are inspected for leakage;
7. developer makes at least one meaningful change to metric, similarity, query, or product flow and explains the full scenario unaided.

## Technical interview readiness

- How did you calculate player minutes, and which edge cases remain?
- What is the grain of your player aggregates, especially for transfers?
- Why can per-90 metrics mislead?
- How do minimum minutes and cohort definitions change percentiles?
- Walk through one possession-adjusted metric and its assumptions.
- What does an 85th percentile mean in your interface?
- How did you define and evaluate player similarity without labelled “similar” pairs?
- What happens if a similarity feature is highly skewed or missing?
- Why did you choose these role features and weights?
- How do you explain a similarity result to a scout?
- How did you prevent slow or unsafe filter queries?
- Describe the deployed data/migration/configuration path and a rollback or rebuild.
- What would require human scouting before acting on this product's output?

## Testing and validation

- **Unit tests:** minute intervals; per-90/adjustment formulas; metric direction; percentile ties/nulls/small cohorts; scaling/distance/contribution; filters; report formatting helpers.
- **Integration tests:** fixture events/lineups through aggregate views; API filters/pagination/profile/similarity; UI contract; PDF generation; migrations against deployment-like PostgreSQL.
- **Data-quality tests:** unique player-team-season grain; nonnegative/plausible minutes; team/player reconciliation tolerances; metric numerators compatible with denominators; cohort sizes; no impossible percentiles; source coverage/exclusions.
- **Model/analytical validation:** similarity perturbation and stability; threshold/cohort sensitivity; adjusted-versus-unadjusted comparison; known-player qualitative cases with written expectations and disagreement notes.
- **Manual acceptance:** complete two or three scouting scenarios; manually recalculate five player metrics and percentiles; inspect ten similarity lists; inspect PDFs; test empty/small cohorts, transferred players, mobile/desktop basics, and visible attribution.
- **Reproducibility:** clean database/manifest creates the same aggregates, cohort membership, golden comparison, and PDF content (excluding declared timestamps); deployed version identifies data/code/model versions.

Tests should protect calculation contracts and decision context, not merely confirm endpoints return 200.

## Portfolio artifact

- **English write-up:** “Designing an explainable player-scouting explorer: cohorts, context, and similarity,” with sensitivity examples and user-review findings.
- **Demo/live artifact:** deployed scenario-driven walkthrough plus a 5–7 minute recording and sample attributed PDF.
- **GitHub deliverable:** aggregation/metric definitions, tested API/UI, similarity evaluation notes, deployment/rebuild guide, and versioned sample report.
- **Draft CV claim:** “Designed and deployed a football Scout Explorer that converts validated event data into player-team-season metrics, contextual role percentiles, and explainable similarity results, with tested FastAPI/Next.js workflows and versioned PDF reports.”
- **Interview story (problem–decision–result):** Problem—raw per-90 leaderboards compared players across incompatible roles, minutes, and environments. Decision—make cohort, threshold, metric definitions, and similarity contributions explicit, then validate calculations and analyst scenarios. Result—users can form and audit a shortlist through one deployed workflow while seeing the support and limitations behind every comparison.

Add real reviewer/task/latency numbers only after release measurement.

## Definition of done

- Minutes and aggregates pass automated reconciliation plus at least five hand-checked matches/players.
- Every exposed metric has a definition, grain, direction, denominator, source, and limitation.
- First release exposes at most 15 purposeful metrics and clearly shows totals/minutes with rates.
- Every percentile and similarity result includes its cohort/role/season/data version and adequate cohort size.
- Minimum-minute and at least one cohort sensitivity example are published.
- Any possession adjustment is justified, tested, labelled, and shown beside unadjusted context; unsupported adjustments are removed.
- Similarity is deterministic, role-aware, excludes the query player, handles missingness, explains major feature gaps, and has documented stability/sanity review.
- Written analyst scenarios can be completed in the deployed product; empty/error states do not mislead.
- PDF values match UI/API golden cases and include definitions, versions, limitations, and attribution.
- Deployment health/smoke tests pass; migrations, secrets, logs, and rebuild/rollback path are documented.
- Write-up, recording/live link, GitHub release, CV claim, and interview story are complete.
- Developer explains the metric/cohort/similarity/deployment path without AI.

## Risks and scope cuts

| Risk | Response |
|---|---|
| incorrect minutes silently corrupt all rates | interval fixtures, reconciliation, hand checks before UI work |
| “role” becomes an arbitrary label | small documented taxonomy, multi-position policy, sensitivity notes |
| percentiles imply universal quality | always display cohort, support, direction, and raw value |
| similarity becomes subjective feature soup | role-specific feature card, baseline, perturbations, explanation, no success claims without evidence |
| possession adjustment exceeds data support | show unadjusted values and drop adjustment if validation is unclear |
| UI/PDF polish delays deployment | use simple components/templates and one coherent scenario |
| deployment/tool choice expands architecture | one provider/path, one-week cap for first deploy, no auth unless required |
| AI-generated football labels sound authoritative | human review of every definition and limitation |

Cut first: saved lists/auth, visual polish/radar variants, share links, caching, additional roles, more than 10–15 metrics, combined-team views, possession adjustments beyond one or two, PDF themes. Keep correct minutes, explicit cohorts, transparent baseline similarity, one analyst flow, attributed PDF, and a usable deployment.

## Dependencies

- Phase 2 public vertical slice is stable and its API/frontend/deployment patterns are reusable;
- Phase 1 lineups, substitutions, periods, players, teams, competitions/seasons, and event types are validated;
- enough player-minute and event coverage for declared cohorts;
- current StatsBomb usage/attribution check;
- a deployment choice can be made from current cost/availability constraints near WP3.7, documented if architectural.

## Estimated effort

**100–135 hours / 6–9 weeks.** Approximate allocation: 10 hours problem/metric design, 18–23 minutes/aggregates, 20–28 cohorts/adjustment/similarity learning, 18–24 API/UI, 13–18 PDF/deployment, 10–14 validation, and 7–8 documentation/demo. If over nine weeks, reduce metrics and polish; do not weaken contextual definitions or deployment usability.
