# Touchline Intelligence — agent entry point

**Read this before touching anything.** It is the state of the project and the reasoning behind its
scope. Everything below is either current fact or a link to the document that owns the detail.

Last updated: 2026-08-02, WP2.1 complete. Update the "Where we are" section
when a work package closes; do not let it drift.

---

## 1. What this is, and what it is for

A football research and decision-support product built on
[StatsBomb Open Data](https://github.com/statsbomb/open-data): validated relational data, a
calibrated shot-quality model, an analyst interface.

**The purpose is not the product. It is employment.** This is a portfolio built to survive a
technical interview and get its author hired into football analytics or general applied ML. Every
scope decision follows from that, which is why some obviously-useful features are absent and some
apparently-minor documentation is mandatory.

The consequence you most need to internalise: **an impressive artifact that cannot be defended is
worse than a small one that can**, because the failure happens after the CV screen, which is the
most expensive place for it to happen. Do not add capability the author cannot explain unaided.

## 2. Where we are

**M0 (walking skeleton) is complete and deployed.**

- Frontend: https://touchline-intelligence.vercel.app (Vercel, free)
- API: https://touchline-intelligence-production.up.railway.app (Railway Hobby, EU West)
- Database: Neon free tier, Frankfurt, holding the pinned WC 2022 snapshot

| WP | State |
|---|---|
| 0.1 repo, tooling, Docker Compose Postgres, typed settings | done |
| 0.2 GitHub Actions | done — three jobs, all green |
| 0.3 StatsBomb WC 2022 ingestion | done |
| 0.4 descriptive prevalence endpoint | done |
| 0.5 read-only shot endpoint + raw shot map | done |
| 0.6 deployment | done — 18/18 deployed smoke checks pass |
| 1.1 source review, attribution, coverage inventory, data dictionary | done — two unresolved publication questions remain explicit release gates |
| 1.2 relational schema, ERD, ordered migrations, constraints | done — full approved schema and ingestion implemented; independent Sol review and CI passed |
| 1.3 fixed cohort, idempotent ingestion, run manifest | done — full-source acceptance, mutation verification, independent Sol review and CI passed |
| 1.4 data-quality suite and reconciliation report | done — full-cohort report, author sampling verification, mutation verification and independent Sol review passed |
| 1.5 SQL analysis pack and measured query plans | done — 10 read-only queries, full-cohort results, two measured plans and rejected speculative index; focused tests, mutation verification and independent Sol review passed |
| 1.6 deterministic fixture, integration proof, clean rebuild | done — fixture byte pinning, network-free two-clean-build proof, full-cohort clean rebuild and no-op rerun, release evidence, mutation verification and independent Sol review passed |
| 2.1 model cohort, target, exclusions, penalty and leakage contract | done — versioned read-only SQL, full-cohort reconciliation, feature availability review, mutation verification and independent Sol review passed |

M1 is complete: WP1.1 through WP1.6 passed their acceptance and review gates. The fixed
four-tournament cohort, idempotent conflict policy
and durable manifest lifecycle are accepted in ADR 0010. The WP1.4 read-only audit reconciles the
full cohort, reports invariants and missingness, and records completed author sampling verification.
WP1.5 adds ten hand-written, read-only analytical queries and measured full-cohort query plans; no
secondary index was retained without a recurring workload. WP1.6 pins the deterministic fixture,
the clean-build manifest proposed for Phase 2, the full-cohort reconciliation evidence and the
identical no-op rerun. Completing M1 does not clear WP1.1's two documented publication gates.

M2 has started. WP2.1 fixes the internal model-development population at 5,606 eligible
non-penalty shots and 507 goals, keeps all 223 penalties and own-goal events visible in separate
reconciliation evidence, and records an available/uncertain/unavailable decision for every proposed
feature family. It creates no split, model, or performance claim; those begin in later M2 work
packages. The public API remains restricted to WC 2022.

## 3. Documents that own the detail

| Document | Owns |
|---|---|
| [`docs/PLAN.md`](docs/PLAN.md) | Milestones, data scope, validation design, and per-milestone "must be able to defend" lists |
| [`docs/TARGETING.md`](docs/TARGETING.md) | Role fit tiers, employers, visa reality, artifact↔requirement mapping |
| [`DATA_SOURCE.md`](DATA_SOURCE.md) | Source revision, dated terms review, current coverage inventory, data dictionary, publication gates |
| [`CONTEXT.md`](CONTEXT.md) | Canonical domain terms and meanings |
| [`docs/SCHEMA.md`](docs/SCHEMA.md) | ERD, table grain, migration lifecycle, constraints, and validation boundaries |
| [`docs/adr/`](docs/adr/) | Decisions that are expensive to reverse, with the evidence and the review trigger |
| [`docs/research/job-market-methodology.md`](docs/research/job-market-methodology.md) | How scope was decided from 30 real job postings |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Hosts, cost, environment variables, order of operations, failure modes |
| [`CLAUDE.md`](CLAUDE.md) | Standing working agreement for AI agents on this repo |
| [`README.md`](README.md) | Setup, commands, current limitations |

`.scratch/` holds planning records and is git-ignored. Durable decisions are promoted to
`docs/adr/`; nothing in `.scratch/` is authoritative.

## 4. Rules that are not negotiable

These exist because breaking them silently produces something that looks right and is not.

**No unevaluated number is presented as a result.** There is no model yet. The `/baseline` endpoint
returns a *descriptive prevalence* — the conversion rate of the loaded data — and says so in its own
payload. It is explicitly **not** the baseline that M2 models are compared against: that one is
estimated from the training split alone and scored on validation and holdout rows under the same
log loss, Brier and calibration protocol as every candidate. Using the full-cohort rate as a
holdout prediction would leak the holdout's own outcomes into it.

**The map encodes recorded outcomes only.** Every marker is the same size; there is no colour ramp.
Size-by-value and gradients are how expected-goals maps draw a model output, and using either here
would imply a chance-quality estimate that does not exist.

**Provider xG is never ingested.** It is the strongest leakage vector for the M2 model, and the
cheapest guarantee it never reaches a feature set is for it not to be in the database. A parser test
asserts this.

**Missing data stays missing.** Missing optional values become NULL; malformed structure raises. A
shot with no recorded technique is a real source condition; a location present but not exactly two
numbers means the file is not what the parser thinks it is, and coercing it would hide the
misunderstanding behind a plausible row. The base-rate cohort excludes rows with unknown shot type,
period or outcome rather than letting SQL's three-valued logic drop some silently and score others
as definite misses.

**StatsBomb 360 freeze frames are not tracking data** and are never described as such. Event data,
freeze frames and continuous tracking are three different products.

**Attribution is a licence obligation**, not decoration. It appears in the repository, the deployed
page and any published output, and a test fails if it is removed.

The 2026-08-01 review in [`DATA_SOURCE.md`](DATA_SOURCE.md) leaves two publication gates open: the
official Media Pack link no longer exposes a clearly approved logo asset, and the agreement does not
define the current public row-level `/shots` use against its data-redistribution restriction. Text
attribution is not represented as clearing the logo requirement. Do not expand published row-level
data or claim the terms review is resolved until the author obtains current written direction.

## 5. How tests work here

Tests protect **named contracts**, not coverage. Coverage percentage is not an acceptance criterion.

The important part: `scripts/verify_tests_fail.py` breaks each protected behaviour once and asserts
the tests notice. Run it after adding a contract, and **add the new contract to it**:

```bash
uv run python scripts/verify_tests_fail.py
```

It has already caught three tests that passed for the wrong reason — a liveness test blind to an
invisible regression, a secret-leak test using a substring blocklist the real error did not happen
to contain, and a read-only test that set up its own transaction and never exercised the production
code. A green suite proves the tests pass, not that they would fail if the behaviour broke.

Integration tests need PostgreSQL and skip without `TOUCHLINE_DB_URL`. They run inside a dedicated
PostgreSQL schema that is created and dropped around each test, so a destructive reset cannot touch
a developer's loaded data. CI provides a service container.

## 6. Data, and the two things about it that surprise people

The snapshot is **pinned to a StatsBomb commit SHA**, not `master` — Open Data is a live repository
and unpinned counts have no shelf life. Per-file hashes live in `data/provenance/`.

Two facts that shaped the cohort design and are easy to get wrong:

1. **Every league season in StatsBomb Open Data is single-team-centric.** Ligue 1 2021/22 is
   PSG in all 26 matches; Bundesliga 2023/24 is Leverkusen in all 34; La Liga 2020/21 is Barcelona
   in all 35. A chronological holdout inside one of them measures that club's form curve, not
   football drift. Tournaments are complete and balanced, so the core cohort is tournaments only.
   See [ADR 0004](docs/adr/0004-cohort-scope-and-validation-design.md).
2. **Lineup membership is not an appearance.** The original shot-only `players` table had 431 shot
   takers and looked deceptively complete. WP1.2 now collects 829 lineup/event players and 3,244
   match-team memberships, but 1,249 memberships have no position interval. Neither membership nor
   dimension presence proves minutes played; using either as an exposure denominator is still wrong.

The holdout is called a **tournament holdout**, not a temporal one, because holding out a later
tournament changes time and competition composition together. Say so rather than glossing it.

## Model routing and independent review

- Luna handles low-risk, mechanical, repetitive, and tightly scoped work.
- Terra is the default implementation model for normal engineering work.
- Sol handles architecture, methodology, difficult debugging, security and data-integrity
  decisions, and final high-risk judgement.
- Every substantive change not implemented by Sol must receive an independent Sol review after
  tests pass and before it is called complete.
- The reviewer must inspect the actual diff, acceptance criteria, tests, and known limitations.
- A model must not review or approve its own work under the label of an independent review.
- Documentation-only changes may skip mandatory Sol review only when they cannot affect behaviour,
  methodology, release claims, or agent instructions.
- Review results must be reported honestly as `PASS`, `PASS WITH REQUIRED FIXES`, or `FAIL`.
- A `PASS` claim must not be made unless the review actually ran.

## Bounded review protocol

Reviews must preserve correctness, security, data integrity, leakage protection,
reproducibility, and evidence quality without reopening implementation unnecessarily.

- Terra performs routine implementation and localized repairs.
- Sol is reserved for architecture, security, leakage, migrations, data integrity,
  methodology, and independent final judgment.
- Development uses focused tests.
- Full-cohort acceptance and full mutation verification run once after stabilization.
- Expensive suites rerun only when a change touches the behavior they protect.
- Final review uses a stable evidence packet and the actual diff.
- Findings are classified as blocker, release-required, or non-blocking.
- Only blocker and release-required findings are fixed during final review.
- A finding is release-required only if shipping without it would make an existing
  acceptance claim false, unreproducible, insecure, or materially misleading.
- After repairs, run affected tests and perform one delta-based re-review.
- When acceptance evidence is complete, no blocker remains, and the reviewer returns
  PASS, stop. Record non-blocking findings for later work.
- After commit, make no file changes; only push and verify the remote SHA.

## 7. Working agreement

Scope changes come from the author, not from an agent's judgement that something would be nice.
When asked for a narrow correction pass, do exactly what is listed.

Report outcomes honestly. If a check was skipped, say so. If a test fails, show the output. Do not
call something complete before it has actually run — "the code is written" and "it works deployed"
are different claims and only the second one counts for WP0.6.

Commit messages are long and reasoned on purpose: what was wrong and why the change is right, not
just what changed. The git history is part of the portfolio and is expected to be read.

---

Data provided by StatsBomb.
