# Touchline Intelligence Platform — Agent Instructions

> **Start with [`AGENTS.md`](AGENTS.md).** It carries the current state of the project, the
> non-negotiable rules, and pointers to the documents that own each detail. This file is the
> standing working agreement; `AGENTS.md` is where the project actually stands today.

## Purpose and developer context

Build one modular football research and decision-support product that turns raw StatsBomb Open Data into reliable data, models, APIs, and analyst interfaces. The developer is transitioning from Materials Science into football analytics and has full-stack experience but is deliberately learning SQL, relational modelling, statistics, production ML, testing, CI/CD, deployment, and football data. Optimize for understanding and credible evidence, not feature count.

## Current source of truth

- Read `docs/PLAN.md` and the active file under `docs/phases/` before proposing work.
- Follow accepted ADRs under `docs/adr/`.
- Update relevant docs and add/supersede an ADR when architecture or research methodology changes.
- Do not silently expand scope or add technologies.

## Technical and repository conventions

- One repository, one FastAPI backend, one Next.js/TypeScript frontend, one PostgreSQL database.
- Python and JavaScript versions, package managers, command runner, formatters, linters, type checks, migrations, and test commands are pinned in Phase 0 and then used consistently.
- Configuration comes from typed settings and environment variables; commit `.env.example`, never secrets.
- Keep raw-source provenance and ingestion manifests. Use migrations and constraints; do not edit production schemas by hand.
- Prefer clear domain code and measured queries to premature abstractions or speculative performance work.

## Testing and definition of done

- Test behaviour and invariants, not coverage numbers. Include unit, integration, data-quality, model-validation, manual-acceptance, and reproducibility checks appropriate to the feature.
- A core feature is done only when its success criteria pass, failure paths are tested, docs/limitations are updated, generated output is inspected, and the developer can explain it without an agent.
- Keep a small deterministic fixture dataset. Never make ordinary tests depend on live network data.
- Do not weaken tests, data constraints, leakage controls, or metric definitions merely to make CI pass.

## AI-agent workflow

For every important feature:

1. Ask for or write a short problem definition.
2. Define inputs, outputs, success criteria, and non-goals.
3. Record material architecture/research decisions.
4. Propose an implementation in reviewable increments.
5. Require critical human review; flag uncertainty instead of inventing facts.
6. Add or improve behavioural tests.
7. Run and inspect validation.
8. Leave room for at least one meaningful human modification.
9. Document limitations and trade-offs.
10. Ensure the developer can teach back the final implementation.

Agents may draft boilerplate, CRUD, UI scaffolds, repetitive mappings, Docker/CI, test skeletons, docs formatting, and refactors. Humans own problem framing, football/statistical definitions, schema reasoning, split/leakage decisions, metric interpretation, test adequacy, final review, and release claims. Never equate generated code or passing syntax checks with correctness.

## Manual-learning requirements

Respect the active phase's manual requirements. In particular, the developer must personally write/explain representative SQL joins and constraints, shot geometry and logistic-regression reasoning, validation splits and calibration, cohort/percentile/similarity definitions, possession/xT/VAEP logic, and any spatial assumptions. AI can critique and test these; it should not erase the learning step.

## StatsBomb rules

- Before ingestion and every public release, re-read the current StatsBomb Open Data README and linked licence; record the date checked.
- Attribute StatsBomb as the data source and use its logo wherever the current terms require, including repository, app, reports, and distributed media.
- Document competition/season/match coverage and source-file version/manifest.
- Distinguish Open Data events, selected StatsBomb 360 freeze frames, and full tracking data. Never call 360 freeze frames tracking data or make unsupported availability/coverage claims.
- Do not redistribute data or generated artifacts unless current terms permit it.

## Experiment rules

- Follow `docs/experiments/README.md`; do not add MLflow or a tracking server without an ADR based on an observed problem.
- Record experiment ID/date, Git commit, dataset/query version, population, features, target, split, config, seed, metrics, calibration, artifacts, notes, and decision.
- Compare on locked populations/splits, retain simple baselines, prevent leakage, and do not tune repeatedly on the final temporal holdout.

## Scope guardrails

Do not add Kubernetes, microservices, dbt, Dagster, Airflow, MLflow, feature stores, Kafka, distributed processing, graph neural networks, multiple clouds/data providers, complex authentication, a custom design system, or LLM features without a documented requirement and accepted ADR. An addition must name the observed problem, current limitation, added complexity, and justified learning/portfolio value.

When a time box is threatened, cut visual polish, extra filters, extra data coverage, and extra model families before provenance, tests, evaluation integrity, limitations, or reproducibility. Phase 5 is optional; the core portfolio must be complete first.
