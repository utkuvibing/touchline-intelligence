# Phase 0 — Foundations

**Time box:** 12–18 hours, maximum one calendar week  
**Release:** repository and development workflow walkthrough  
**Scope rule:** if a choice cannot affect the Phase 1 vertical slice, use a conventional default and move on.

## Goals and user value

This phase creates the smallest reliable workspace in which data and product work can proceed. The immediate user is the developer and any reviewer trying to run the project. A football organization benefits indirectly: reproducible setup, automated checks, explicit configuration, and decision records reduce the chance that analytical conclusions depend on one laptop or undocumented steps.

It does not solve football problems yet. Its value is a fast, inspectable path to solving them responsibly.

## Deliverables

### Mandatory

- documented monorepo skeleton for `backend`, `frontend`, `infra`, `docs`, `experiments`, local `data`, and generated `artifacts`;
- one pinned supported Python version and one Node.js version;
- one Python environment/package tool and one JavaScript package manager, with lockfiles;
- Docker Compose service for local PostgreSQL with health check and named volume;
- `.env.example`, typed configuration convention, and secret-handling rules;
- Python formatter/linter and type checker; TypeScript lint/format/type check;
- pytest and frontend test runner skeletons containing one meaningful smoke test each;
- pre-commit hooks for fast local checks;
- CI skeleton running install, lint, type checks, and smoke tests;
- top-level README with setup, commands, architecture link, and StatsBomb attribution placeholder;
- ADR process, experiment process, and `CLAUDE.md` in active use;
- a command matrix such as `make`, `just`, or documented package commands—choose one, not several.

### Recommended

- dependency update policy and a short troubleshooting section;
- database migration tool initialized with an empty/metadata migration only if Phase 1 will use it immediately.

### Explicitly not in this phase

Production deployment, observability platforms, authentication, model registries, orchestration, UI design work, real ingestion, and elaborate CI matrices.

## Technical work

### WP0.1 — Pin tools and repository contract (2–3 hours)

Choose versions supported by key libraries, record them in machine-readable files, create the directory skeleton, and define which generated/local files Git ignores. Add a command table for setup, lint, type check, test, database start/stop, and clean operations. Do not add libraries “for later.”

### WP0.2 — Local PostgreSQL and configuration (2–3 hours)

Create one Compose service with an explicit PostgreSQL image version, health check, port, named volume, and values supplied through local environment configuration. Add typed backend settings and a safe example environment file. Confirm a developer can start the database and make a trivial connection; no football tables are required.

### WP0.3 — Quality toolchain (3–4 hours)

Configure format/lint/type/test tools with small, readable rule sets. Add one backend settings or health smoke test and one frontend rendering smoke test. Pre-commit should finish quickly; slow integration tests remain separate.

### WP0.4 — CI skeleton (2–3 hours)

Run deterministic installs from lockfiles and the same checks used locally. Use one operating system and supported runtime per language. Cache only if installs are materially slow. CI may start PostgreSQL only if the smoke test genuinely uses it.

### WP0.5 — Governance and onboarding rehearsal (3–5 hours)

Verify ADR and experiment templates, review `CLAUDE.md`, add the README and attribution placeholder, then test setup from a clean clone or fresh temporary directory. Record every missing instruction; fix only blockers. Capture a short terminal walkthrough.

## Skills demonstrated

- repository and environment management;
- Docker-based local development;
- baseline Python and TypeScript engineering discipline;
- automated testing and CI foundations;
- configuration and secrets hygiene;
- architecture governance and scope control;
- AI-agent operating discipline.

## Learning objectives

By the end of the week, explain without AI:

- why lockfiles and pinned runtimes reduce “works on my machine” failures;
- the difference between formatting, linting, static type checking, and tests;
- why secrets do not belong in Git and how environment configuration reaches an application;
- what a container, image, volume, health check, and port mapping each do;
- what CI verifies that a local run does not;
- why an ADR should record consequences and a review trigger;
- why a green skeleton is useful but is not evidence of product correctness;
- why Phase 0 is capped at one week.

## Manual implementation requirements

| Component | Why manual involvement matters | Knowledge built | Sufficient manual level |
|---|---|---|---|
| Runtime/tool choice note | prevents cargo-cult stack selection | compatibility, reproducibility, trade-offs | read primary docs, select versions, and write a one-paragraph rationale |
| Compose database service | makes later database failures diagnosable | container lifecycle, volumes, ports, health | write or substantially rewrite the service and explain every field |
| One smoke test per app | establishes what a test actually asserts | arrange/act/assert and failure signals | write both tests and intentionally break each once |
| Clean-setup rehearsal | exposes hidden machine assumptions | onboarding and reproducibility | personally follow only the README in a clean location and record gaps |

The developer need not hand-author formatter boilerplate, lockfile contents, or every CI line.

## AI-agent delegation

Agents may draft directory scaffolding, configuration files, Compose/CI/pre-commit YAML, README formatting, and test-runner setup. For each draft, the developer must:

1. compare tool versions with official compatibility documentation;
2. remove unused dependencies and unexplained settings;
3. run every documented command;
4. inspect a deliberate failing check before accepting it;
5. explain the Compose and CI flow aloud;
6. make at least one targeted manual improvement, such as a health check or clearer failure message.

No agent may turn a one-week foundation into a platform-engineering project.

## Technical interview readiness

- How do you make a Python/TypeScript repository reproducible for a new developer?
- What is the difference between a container image and a running container?
- Why use a named PostgreSQL volume locally, and when would you reset it?
- Which checks belong in pre-commit versus CI?
- How would you diagnose a test that passes locally but fails in CI?
- Why did you choose a monorepo for Touchline Intelligence?
- How do you review AI-generated infrastructure configuration?
- Which foundation work did you deliberately defer, and why?

## Testing and validation

- **Unit tests:** one real backend configuration/health behaviour and one frontend component behaviour.
- **Integration tests:** database connection/health check if it can remain small and deterministic.
- **Data-quality tests:** not applicable yet; verify only that no real data is accidentally committed.
- **Model validation:** not applicable.
- **Manual acceptance:** from clean state, install dependencies, start PostgreSQL, run both apps or skeleton commands, run all checks, and stop services using README instructions.
- **Reproducibility:** a second clean setup uses lockfiles and yields the same green check suite; record runtime versions in the demo.

Tests must fail for a demonstrated reason when their protected behaviour is broken. Coverage percentage is not a Phase 0 acceptance criterion.

## Portfolio artifact

- **English write-up:** “The one-week foundation for a reproducible football analytics platform,” emphasizing decisions and exclusions.
- **Demo:** 2–3 minute recording showing clone/setup, database health, local checks, CI, and documentation navigation.
- **GitHub deliverable:** tagged `phase-0` state or equivalent release with green CI and onboarding README.
- **Draft CV claim:** “Established a reproducible Python/FastAPI and Next.js monorepo with containerized PostgreSQL, typed configuration, automated quality checks, and CI, time-boxing platform setup to one week.”
- **Interview story (problem–decision–result):** Problem—an eight-month solo project could accumulate inconsistent tooling and opaque agent changes. Decision—pin a minimal toolchain, define shared commands and AI review rules, and validate a clean setup. Result—a reviewer can reproduce the skeleton and see failures in CI before football functionality is added.

## Definition of done

- Phase duration is no more than seven calendar days and 18 focused hours.
- A clean setup following only the README succeeds.
- PostgreSQL becomes healthy and persists a trivial test value across container restart.
- Local and CI lint, type, and smoke-test commands pass.
- A deliberately introduced lint/test error is caught locally and in the relevant CI job.
- No secret, raw dataset, or generated large artifact is tracked.
- `CLAUDE.md`, ADRs, and experiment rules are linked from the README.
- The developer can explain the toolchain and its omissions without AI.
- The write-up and demo are saved or published.

## Risks and scope cuts

| Risk | Response |
|---|---|
| package-manager/version debate consumes time | choose a supported conventional option and document it in one paragraph |
| generated YAML is accepted without understanding | annotate/rewrite key sections and induce one controlled failure |
| CI and local commands diverge | centralize commands and have CI call them |
| too many tools before real code exists | each dependency must support a mandatory Phase 0 deliverable |
| Windows/path differences cause hidden failures | use documented cross-platform commands or state the supported local path clearly |

Cut first: dependency automation, advanced caching, coverage upload, CI matrices, commit-message enforcement, database admin UI, frontend styling. Do not cut lockfiles, clean setup, secret handling, smoke tests, or the one-week cap.

## Dependencies

- Git, Docker with Compose, and supported local runtime installation capability;
- access to GitHub or the chosen Git host for CI;
- this plan and accepted ADRs;
- no application code or football dataset is required.

## Estimated effort

**12–18 hours / one week at 15–20 hours per week.** Suggested split: 3 hours deliberate learning, 8–11 hours implementation, 2–3 hours validation, and 1 hour documentation/demo. Stop at the time box even if recommended polish remains.

