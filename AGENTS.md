# Touchline Intelligence — agent entry point

**Read this before touching anything.** It is the state of the project and the reasoning behind its
scope. Everything below is either current fact or a link to the document that owns the detail.

Last updated: 2026-08-01, M0 complete. Update the "Where we are" section when a work package
closes; do not let it drift.

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
| 1.1 source review, attribution, coverage inventory, data dictionary | in progress — documentation recorded; logo and public row-level use remain release gates |

M1 has started with WP1.1. The remaining M1 work is the full four-tournament cohort, a real schema
with constraints and migrations, idempotent ingestion, data-quality reporting, and the SQL analysis
pack. Do not treat WP1.1 as closed while its two publication gates remain unresolved.

## 3. Documents that own the detail

| Document | Owns |
|---|---|
| [`docs/PLAN.md`](docs/PLAN.md) | Milestones, data scope, validation design, and per-milestone "must be able to defend" lists |
| [`docs/TARGETING.md`](docs/TARGETING.md) | Role fit tiers, employers, visa reality, artifact↔requirement mapping |
| [`DATA_SOURCE.md`](DATA_SOURCE.md) | Source revision, dated terms review, current coverage inventory, data dictionary, publication gates |
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
2. **`players` is not a squad list.** WP0.3 reads shot events only, so a player exists only if they
   took a shot — 431 rows for WC 2022 against roughly 830 in the squads. Any per-player denominator
   from that table is wrong in a way that still looks plausible.

The holdout is called a **tournament holdout**, not a temporal one, because holding out a later
tournament changes time and competition composition together. Say so rather than glossing it.

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
