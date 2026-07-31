# Touchline Intelligence Platform — Execution Plan

## Product vision

Touchline Intelligence Platform is one evolving football research and decision-support product: it turns StatsBomb Open Data into validated relational data, reproducible models, analyst-facing APIs, and useful interfaces. Each phase extends the same data and product foundation; phases are not standalone portfolio demos with duplicated pipelines.

The platform is for analysts, scouts, and research teams who need to understand where data came from, trust how metrics were calculated, and inspect model limitations before using an output in a football decision.

### Success principles

1. Ship a narrow end-to-end path before adding breadth.
2. Prefer transparent baselines and trustworthy evaluation to impressive model names.
3. Make data lineage, assumptions, and limitations visible.
4. Use AI agents for leverage while retaining human ownership of methodology and quality.
5. Produce an interview-ready artifact at the end of every phase.

## Personal learning context

The developer already has experience shipping Python, FastAPI, Streamlit, TypeScript, Next.js, React Native, Supabase, and AI-assisted projects. This plan deliberately concentrates effort on the current gaps: SQL and relational modelling, football event data, statistics, leakage-aware evaluation, production ML, automated testing, CI/CD, deployment, and explaining code written with AI assistance.

The aim is not to stop using AI. The aim is to become an AI-native engineer who defines problems precisely, challenges generated implementations, designs meaningful tests, makes targeted manual changes, and can defend every important decision without an agent present.

## Target job families

- Research Engineer
- Football Data Scientist / Sports Data Scientist
- Applied Machine Learning Engineer
- Data Product Engineer
- Football Intelligence Engineer / Sports Analytics Engineer

The strongest evidence for football analytics roles will be Phases 2–4. The strongest evidence for data-product roles will be Phases 1–3. Research-engineering credibility becomes materially stronger in Phase 4.

## Scope labels

- **Mandatory:** required to pass the phase definition of done.
- **Recommended:** high value, but may move to the next phase if the time box is threatened.
- **Optional:** attempted only after mandatory work is complete and documented.

## Architecture overview

The initial architecture is intentionally conventional:

```text
StatsBomb Open Data JSON
          |
          v
versioned ingestion command ---> ingestion manifest + data-quality report
          |
          v
      PostgreSQL
          |
          +----> SQL/Python feature pipelines ---> experiment records + model artifacts
          |                                      |
          |                                      v
          +---------------------------------> FastAPI
                                                   |
                                                   v
                                          Next.js/TypeScript UI
```

One repository contains:

```text
backend/                 Python package, FastAPI, ingestion, features, modelling
frontend/                Next.js and TypeScript application
infra/                   local Docker and later deployment configuration
scripts/                 thin, documented developer entry points
tests/                   only if a test cannot live naturally under backend/frontend
docs/                    plan, phase notes, reports, ADRs, data and model cards
experiments/             versioned configs, results index, and plot metadata
artifacts/               local/generated models and plots; large outputs ignored by Git
data/                    local raw/interim data; ignored except metadata/small fixtures
```

Phase 0 may adjust names once, before application code exists. Later structural changes require an ADR. There is one FastAPI backend, one Next.js frontend, one PostgreSQL database, and simple commands or scheduled jobs. No distributed or orchestration platform is planned.

## Phase map

| Phase | Indicative weeks | Mandatory outcome | Release |
|---|---:|---|---|
| 0. Foundations | 1 | Reproducible development and governance skeleton | Repository tour and green CI skeleton |
| 1. Data Foundation | 2–6 | Idempotent StatsBomb-to-PostgreSQL path with quality evidence | Data engineering case study |
| 2. Shot Quality Engine | 7–14 | Evaluated xG baseline and comparison model exposed through API/UI | **Earliest credible job-application release** |
| 3. Scout Explorer | 15–23 | Deployed, contextual player exploration and explainable similarity | **Strong general portfolio release** |
| 4. Action Value Lab | 24–34 | Reproducible xT/VAEP research module with reference comparison | Research-engineering release |
| Integration/buffer | distributed, up to 4 weeks | Fixes, reports, demos, interview rehearsal | Final 8–9 month portfolio package |
| 5. Spatial Intelligence | after main plan, 5–8 weeks | One bounded 360 research question | Optional specialization release |

The week numbers are sequencing guides, not promises. At 15 hours per week, use the upper estimates and cut recommended work. Phase 5 is not part of the main 8–9 month commitment.

## Dependencies and gates

```text
Phase 0 -> Phase 1 -> Phase 2 -> Phase 3
                         |          |
                         +----------+-> Phase 4 -> optional Phase 5
```

- Phase 1 owns canonical identifiers, coordinate conventions, provenance, and data-quality rules used by every later phase.
- Phase 2 establishes leakage-aware experiment and model-serving patterns.
- Phase 3 reuses the same database, API, frontend, and deployment path.
- Phase 4 requires reliable event ordering and possession semantics from Phase 1, plus experiment discipline from Phase 2. It need not wait for every Phase 3 enhancement, but the public Phase 3 release should be stable first.
- Phase 5 begins only when the main portfolio is deployed, documented, and already suitable for applications.

## Eight-to-nine-month timeline

### Month 1: foundations and data orientation

Complete Phase 0, read the official data specification, inspect a small raw sample manually, draw the first schema, and load one match end to end.

### Month 2: reliable data foundation

Complete the scoped ingestion, constraints, idempotency tests, quality report, SQL query pack, and first data-engineering write-up.

### Months 3–4: Shot Quality Engine

Build the baseline before boosting. Add grouped and temporal evaluation, calibration, error slices, model card, API endpoint, shot-map UI, and a recorded demo. Start targeted applications only after this release is reproducible and public-facing.

### Months 5–6: Scout Explorer

Build minutes and player aggregates, defend comparison cohorts, add transparent similarity and filters, generate a report, deploy the coherent product, and prepare the strongest general portfolio walkthrough.

### Months 7–8: Action Value Lab

Implement possession segmentation and xT, study VAEP assumptions, compare a bounded implementation with socceraction, investigate discrepancies, and publish a research report integrated into the platform.

### Month 9: consolidation buffer

Resolve high-value issues, pin reproducible demo data, improve onboarding, rehearse interview explanations, update CV materials, and apply. Begin Phase 5 only if these are already complete.

## Weekly time allocation (15–20 hours)

| Work type | Hours/week | Purpose |
|---|---:|---|
| Implementation and debugging | 8–11 | One thin, testable work package at a time |
| Manual learning and derivation | 3–4 | SQL exercises, statistical reasoning, paper reproduction, handwritten explanations |
| Testing and validation | 2–3 | Behavioural, data, model, integration, and reproducibility checks |
| Documentation and portfolio | 1–2 | Decision notes, results, screenshots, demo narrative |

Reserve one session each week for work without AI autocomplete: write or modify a core query/function, predict test outcomes, and explain the result aloud. End each week with a runnable state or explicitly documented blocker.

## Portfolio release points and application readiness

| Milestone | Evidence | Application posture |
|---|---|---|
| End Phase 1 | schema, ingestion rerun proof, SQL analysis, data-quality report | Useful supporting evidence for junior data roles; not yet the flagship |
| End Phase 2 | xG report, grouped/temporal evaluation, model card, API/UI demo | **Earliest credible point** for football analytics and applied-ML applications |
| End Phase 3 | deployed analyst workflow, contextual metrics, explainable similarity, PDF report | **Recommended point for broad active applications** |
| End Phase 4 | paper-led implementation, reference comparison, ablations, discrepancy analysis | Strong research-engineering and advanced sports analytics evidence |
| End Phase 5 | bounded 360 spatial study | Optional specialization, not a prerequisite for applications |

No CV claim is used until the corresponding test evidence, report, and demo exist. Claims use scoped dataset sizes and measured results, never implied production users or club adoption.

## Release quality bar

Every phase release must include:

- a tagged or clearly identified GitHub state;
- reproducible setup and run commands;
- a short English write-up describing problem, decision, evidence, and limitations;
- a screenshot, recording, or live demo;
- automated tests appropriate to the phase;
- an updated limitations section and relevant ADRs;
- a CV claim and a rehearsed problem–decision–result interview story.

## Main risks

| Risk | Early signal | Response |
|---|---|---|
| AI-generated code is not understood | cannot explain a query/function or predict failure modes | require problem spec, tests, one manual change, and teach-back before merge |
| SQL learning is bypassed by ORM code | all analysis happens in pandas | write and explain canonical joins/aggregations in SQL first |
| Football definitions drift | “possession,” “pressure,” or “role” lacks a written definition | maintain data dictionary and assumption notes with examples |
| Evaluation leaks match/player/time information | suspiciously strong validation or unstable holdout results | grouped and temporal splits, leakage checklist, feature availability review |
| Product breadth outruns reliability | several half-working modules, no stable release | stop feature work and pass the current phase definition of done |
| Open Data coverage limits claims | comparisons mix incompatible competitions or sparse 360 matches | publish coverage table; scope conclusions to observed data |
| Deployment becomes a side project | cloud configuration consumes more than one week | use one simple service or record a local demo; defer optimization |
| Burnout at 15–20 hours/week | repeated carry-over and skipped documentation | plan 80% capacity, use consolidation weeks, cut recommended work |

## Scope guardrails

Do not add Kubernetes, microservices, dbt, Dagster, Airflow, MLflow, a feature store, Kafka, distributed processing, graph neural networks, multiple clouds, multiple football data providers, complex authentication, a custom design system, or LLM product features in early phases.

Before adding any technology, record an ADR answering:

1. Which observed problem does it solve?
2. Why is the current solution insufficient?
3. What operational and learning complexity does it add?
4. What measurable portfolio or learning value justifies it?

The default scope cut order is: visual polish, extra filters, extra competitions, extra model families, automation convenience, then an entire optional module. Never cut data provenance, leakage controls, core tests, limitations, or reproducibility to preserve feature count.

## Data rights and evidence boundaries

Before first ingestion and before every public release, review the current [StatsBomb Open Data repository README](https://github.com/statsbomb/open-data) and its linked licence. The current repository guidance requires published/shared/distributed work to state StatsBomb as the source and use the StatsBomb logo. Keep the required attribution in the repository, application, reports, and demos as applicable, and record the review date.

Document exactly which competitions, seasons, matches, event files, and 360 files are present. Open Data event data, selected StatsBomb 360 freeze frames, and full tracking data are different products. A freeze frame is a partial snapshot around an event, not continuous player tracking; no report may imply otherwise.

## Plan maintenance

At each phase boundary, spend no more than two hours comparing estimate to actual, recording cuts, and updating the next phase. Material architecture or methodology changes require an ADR. Estimates are ranges because learning and data-quality discoveries are uncertain; missed estimates should trigger scope decisions, not hidden overtime.

