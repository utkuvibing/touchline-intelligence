# Touchline Intelligence — agent entry point

**Read this before touching anything.** It is the state of the project and the reasoning behind its
scope. Everything below is either current fact or a link to the document that owns the detail.

Last updated: 2026-08-22. M2 is complete through WP2.8, and M3 is complete through WP3.4. The
qualified `exp-20260810-wp2_8-release` is served by the production API and analyst interface; its
M2 release packet correctly remains the historical `not_served` qualification record. WP3.4 closed
after 22/22 production smoke, an isolated fresh-Neon rebuild, Railway and Vercel recovery
rehearsals, operator-confirmed rehearsal-resource decommissioning, and independent GPT-5.6 Sol
review `PASS`. Historical row-level publication remains **NOT CLEARED** and `/model/shots` remains
gated closed. Update the "Where we are" section when a work package closes; do not let it drift.

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
- Database: Neon, Frankfurt, holding the pinned four-tournament snapshot; public rows remain WC 2022 only

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
| 2.2 geometry and feature pipeline | **partial.** Slice A: distance and visible goal angle shipped with source-verified constants, full-cohort read-only evidence and 6/6 mutation verification. Slice B: coverage and annotation-encoding audit shipped (7 read-only tests, 6/6 mutations) — it **admits no feature**; the six `Uncertain` booleans are measured to be true-only annotations. The level/field decisions, training-only preprocessing and the training/serving feature contract were resolved by WP2.4 (2026-08-05). **Independent review is planned via GPT-5.6 Thinking (ChatGPT) at the final push/PR review stage and remains pending; it has not run and no `PASS` is claimed.** |
| 2.3 split and evaluation design | done — named three-way split locked (dev WC 2018 + Euro 2020 / calibration WC 2022 / tournament holdout Euro 2024), five deterministic match-grouped development folds, target-free by construction, byte-pinned match-assignment CSV and schema-validated manifest, shot-level partition proof and WP2.1 cohort set-equality over 5,606 rows, strict top-level chronology, 8/8 registered mutation contracts CAUGHT (139/139 suite-wide), full-cohort evidence in `reports/wp2.3-split-evidence.md`. Reliability binning fixed a priori at five equal-width bins without holdout labels (ADR 0004 amendment). **Independent review passed — Qwen 3.7, `PASS`, no blocking or non-blocking findings; see the review note below.** |
| 2.4 baselines and regularized logistic regression | done — constant, geometry-only and full-minus-presence logistic on the locked 2,872-row development cohort with byte-pinned artifact verification and the structural holdout lock; D5 executable rule **excluded** both presence indicators (positive ΔLL on 3/5 folds vs the ≥4 requirement), so the shipped feature set is geometry + categoricals; full logistic dominates the primary metrics (mean log loss 0.262 vs 0.302 constant; Brier 0.072 vs 0.082; ROC 0.754 vs 0.476), while the PLAN §4.1 rule names the constant as incumbent because its constructed single-bin calibration deviation (~5e-5) cannot be undercut — investigated and reported, not tuned away. Evidence: `experiments/shot_quality/exp-20260805-wp2_4-baselines/`, `reports/wp2.4-baselines-evidence.md`. 8/8 WP2.4 mutation contracts CAUGHT (147/147 suite-wide); full-cohort evidence local. New deps numpy/scikit-learn (uv.lock). **Independent review planned via GPT-5.6 Thinking (ChatGPT) at the final push/PR review stage; not run; no `PASS` claimed.** |
| 2.5 gradient boosting and controlled comparison | done pending review — one `HistGradientBoostingClassifier` over a pre-registered twelve-point grid (ADR 0011), on the identical locked 2,872-row cohort, folds and WP2.4 shipped feature columns; zero new dependencies. **The booster did not replace the logistic regression.** Measured: mean log loss 0.268004 vs 0.263358 incumbent, Brier 0.074544 vs 0.073044, ROC 0.7413 vs 0.7530 — but better calibrated (max supported deviation 0.031 vs 0.054) and more stable (cross-fold SD 0.0145 vs 0.0162), so §4.1 conditions 3 and 4 hold while 1 and 2 fail. Selected point lr=0.03/leaves=7/min_leaf=60. Chain A (WP2.4 chain extended by one step) leaves `protocol_incumbent = constant` as pre-stated; chain B is the decision of record. All four WP2.4 candidates reproduced to 12 decimals in the same process. **A first full-cohort run was invalidated** — its artifact SHA was not reproducible while every metric and prediction was; row order and `PYTHONHASHSEED` were tested and rejected, OpenMP thread count was shown to control the serialized estimator bytes, and the fix pins one thread at process start without touching the protocol (ADR 0011 remediation, dated). The replacement run reproduces byte-for-byte in a fresh subprocess launched through `touchline.boosting_bootstrap`, which pins one OpenMP thread before scikit-learn loads. A later review round split the bundle's ambiguous `shipped_candidate` into `artifact_candidate` (what it contains) and `selection_incumbent` (what won), moved the pin out of `touchline.modeling.__init__` into the launcher so importing WP2.3/WP2.4 code no longer mutates the environment, and regenerated the record once under the corrected code: all statistics and the WP2.4 gate unchanged, artifact schema 2, model pickle `1afe18f5ffd17b42...`. Linux CI then caught a genuine cross-platform provenance defect: `uv.lock` was hashed into every record but never pinned in `.gitattributes`, so a Windows checkout recorded its CRLF digest. Pinned, normalised and regenerated; statistics and estimator digest unchanged. Evidence: `experiments/shot_quality/exp-20260806-wp2_5-gradient-boosting/`, `reports/wp2.5-gradient-boosting-evidence.md`. 9/9 WP2.5 mutation contracts CAUGHT, 169/169 suite-wide (the suite must be run with TOUCHLINE_DB_URL and TOUCHLINE_FULL_COHORT_DB_URL set, or the integration and full-cohort contracts skip and are scored as MISSED); full-cohort evidence local. **Independent review: performed manually by the author on 2026-08-06, verdict `PASS`** — a human review, not the GPT-5.6/Sol model review the WP2.4 row anticipated; recorded as what actually happened. CI green on the merged head (3/3). Merged to `main` as `524296b` via squash of PR #8. |
| 2.6 bounded PyTorch MLP | done — bounded CPU/CUDA qualification, artifact and dependency boundaries recorded. **Independent Sol review: `PASS` (closed 2026-08-09).** |
| 2.7 calibration, reliability, and one-time holdout | done — frozen development base, WC2022-only Platt calibration and adoption, one supervised Euro2024 tournament-holdout execution, paired bootstrap, slices, audit evidence and model card completed; independent GPT-5.6 Sol review `PASS` recorded in ADR 0013 and the closeout evidence. |
| 2.8 reproducible calibrated release | done — development-only historical reproduction passed byte-identically in the registered environment; immutable content-hashed release `exp-20260810-wp2_8-release` qualified as `m2_qualified`, `not_served`; independent GPT-5.6 Sol review `PASS` recorded in ADR 0014 and the closeout evidence. |
| 3.1 API and model serving | done for this iteration — minimal immutable serving bundle, fail-fast singleton runtime, versioned metadata/metrics/prediction endpoints, publication-gated WC2022 historical predictions, independent WP2 golden parity, structured errors, readiness 503 semantics, Linux-image golden/corruption acceptance and 20/20 WP3.1 mutations (284/284 suite-wide) implemented and evidenced. **The project author manually approved the review gate for this iteration; no independent Sol review ran and no independent-review `PASS` is claimed.** |
| 3.2 analyst interface | done — repaired pagination and exact error-envelope validation, exhaustive mutation verification `292/292`, prior affected delta `13/13`, current repair delta `7/7`, and cumulative coverage of the current 301-contract population with no misses or skips; independent GPT-5.6 Sol delta re-review `PASS`. The analyst interface is deployed; historical publication remains **NOT CLEARED**. |
| 3.3 deployment hardening | done — protected native Git deployments, packaged migrations before admission, full readiness/liveness separation, structured request logs and IDs, exact CORS contracts, pooled runtime/direct migration separation, secret-safe configuration, Railway and Vercel production activation. |
| 3.4 deployed smoke and recovery | done — 22/22 final production smoke, isolated fresh-Neon rebuild with pinned counts and packaged-runtime checks, Railway rollback/roll-forward, Vercel Instant Rollback/Promote, rehearsal-resource decommissioning, and independent GPT-5.6 Sol closeout review `PASS`; evidence in `reports/wp3.4-deployed-smoke-and-recovery-evidence.md`. |

M1 is complete: WP1.1 through WP1.6 passed their acceptance and review gates. The fixed
four-tournament cohort, idempotent conflict policy
and durable manifest lifecycle are accepted in ADR 0010. The WP1.4 read-only audit reconciles the
full cohort, reports invariants and missingness, and records completed author sampling verification.
WP1.5 adds ten hand-written, read-only analytical queries and measured full-cohort query plans; no
secondary index was retained without a recurring workload. WP1.6 pins the deterministic fixture,
the clean-build manifest proposed for Phase 2, the full-cohort reconciliation evidence and the
identical no-op rerun. Completing M1 does not clear WP1.1's two documented publication gates.

M2 is complete through WP2.8. The qualified release is the development-fitted
`full_minus_presence` logistic artifact with the pre-holdout-adopted WC2022 Platt transform, released
as `exp-20260810-wp2_8-release` with `release_status = m2_qualified` and
`serving_status = not_served` in the immutable M2 qualification packet. Euro2024 was opened once as
the tournament holdout; WP2.8's historical reproduction was development-only and did not reopen
WC2022 or Euro2024. M3 now serves that same immutable release while preserving the qualification
packet's historical status. The public API remains restricted to WC 2022.

M3 is complete through WP3.4. The qualified model API and analyst interface are live, the deployed
contract passes 22/22 smoke checks, and the isolated rebuild plus Railway/Vercel recovery paths were
performed and evidenced. The rehearsal Neon resource was decommissioned by the operator. This does
not clear the separate historical row-level publication question; `/model/shots` remains closed.

WP2.2 is **partially complete**. Slice A ships the two continuous geometry features — distance to
the goal centre and the visible goal angle in a numerically stable two-post form — over exactly
WP2.1's 5,606 rows. The goal constants are verified against StatsBomb Open Data Specification v1.1
Appendix 2 rather than assumed, and the measurement found what an assumption would have hidden.
`docs/SCHEMA.md` records that the pinned revision holds exactly one event at `location_x = 120.1`
but never established its event type; the WP2.2 boundary audit measured that it is a **Shot**, and
that it is inside the model cohort.
It is handled by a bounded source-coordinate tolerance adjustment that changes the derived feature
only and raises past the measured maximum instead of clamping; the StatsBomb source is unmodified.
Evidence: [`reports/wp2.2-geometry-evidence.md`](reports/wp2.2-geometry-evidence.md); decisions:
[`docs/modeling/wp2_2-geometry-contract.md`](docs/modeling/wp2_2-geometry-contract.md).

Slice B has started with its evidence step and nothing beyond it. `docs/PLAN.md` admits context
features "only after documenting coverage", so the first increment documents coverage and admits
no feature: `backend/sql/wp2_2/03_categorical_support.sql` and `04_annotation_encoding_audit.sql`,
seven read-only full-cohort tests, and
[`reports/wp2.2-slice-b-coverage-evidence.md`](reports/wp2.2-slice-b-coverage-evidence.md). It
settles one thing and hands forward several. Settled: **none of the six `Uncertain` booleans ever
records an explicit `false`** in 33,636 field-observations, so they are true-only annotations —
absence cannot be separated from "annotated as not the case", and anything built on them is a
presence indicator, not a boolean. Neither query reads the target, because conversion rate per
level is measurable only over a cohort that contains WP2.3's holdout.

Three things were outstanding before WP2.2 could be called done. The **level and field decisions**
(`shot_type_name = 'Corner'`, `follows_dribble`, `under_pressure`/`first_time` annotation
intensity, and the `open_goal`/`one_on_one` semantics review) and **training-only preprocessing and
the training/serving feature contract** are now closed by WP2.4 (2026-08-05; see the design
decisions in `docs/modeling/wp2_4-baselines-and-logistic-contract.md` and their execution in
`reports/wp2.4-baselines-evidence.md`). The remaining outstanding item is the **independent review of
WP2.2 Slices A + B** (both were implemented by Sol, so under the policy below Sol cannot also
review them): the review is **planned via GPT-5.6 Thinking (ChatGPT) at the final push/PR review
stage and remains pending**. It has not run; no `PASS` is claimed; and `uv run poe check` passing,
the 12/12 WP2.2 mutations and the 147/147 suite-wide mutation verification are not substitutes for
it. This sentence stays here until it actually runs.

WP2.3 locks the named three-way split before any model exists: development is WC 2018 + Euro 2020
(115 matches), calibration is WC 2022 (64 matches), and Euro 2024 (51 matches) is the tournament
holdout, locked from WP2.3 onward and **not blind** — WP2.1's published reconciliation already
exposed descriptive per-tournament goal counts, and WP2.2 recorded exploratory viewing of outcome
rates; the contract document states that history rather than claiming otherwise. Five deterministic
match-grouped development folds of 23 matches each are produced by a pure, target-free function
(`touchline.modeling.splits`); the fold semantics are explicitly **not** temporal or
forward-chaining. The split is proven over the full cohort by exact set equality with WP2.1's
cohort query and a per-shot partition proof (5,606 unique shot ids, zero unassigned), and locked
artifacts are the byte-pinned assignment CSV and a schema-validated manifest containing no goal
counts. Reliability binning is fixed a priori at five equal-width bins from label-free scale only;
ADR 0004 carries a 2026-08-04 amendment superseding its earlier outcome-conditioned rationale.
Decisions: [`docs/modeling/wp2_3-split-and-evaluation-contract.md`](docs/modeling/wp2_3-split-and-evaluation-contract.md);
evidence: [`reports/wp2.3-split-evidence.md`](reports/wp2.3-split-evidence.md).

## 3. Documents that own the detail

| Document | Owns |
|---|---|
| [`docs/PLAN.md`](docs/PLAN.md) | Milestones, data scope, validation design, and per-milestone "must be able to defend" lists |
| `docs/TARGETING.md` *(local only, git-ignored)* | Role fit tiers, employers, visa reality, artifact↔requirement mapping |
| [`DATA_SOURCE.md`](DATA_SOURCE.md) | Source revision, dated terms review, current coverage inventory, data dictionary, publication gates |
| [`CONTEXT.md`](CONTEXT.md) | Canonical domain terms and meanings |
| [`docs/SCHEMA.md`](docs/SCHEMA.md) | ERD, table grain, migration lifecycle, constraints, and validation boundaries |
| [`docs/adr/`](docs/adr/) | Decisions that are expensive to reverse, with the evidence and the review trigger |
| [`docs/modeling/wp2_7-calibration-and-holdout-contract.md`](docs/modeling/wp2_7-calibration-and-holdout-contract.md) | WP2.7 frozen-base, adoption, holdout, and audit contract |
| `docs/research/job-market-methodology.md` *(local only, git-ignored)* | How scope was decided from 30 real job postings |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Hosts, cost, environment variables, order of operations, failure modes |
| [`CLAUDE.md`](CLAUDE.md) | Standing working agreement for AI agents on this repo |
| [`README.md`](README.md) | Public project introduction — what it is, features, architecture, quick start, credits |
| [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) | Full command matrix, testing contract, ingestion internals, endpoint semantics, current limitations |

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

**Deferral closed.** WP2.3 (the locked three-way split and evaluation design) has received its
independent review. Reviewer model: **Qwen 3.7** — an independent reviewer, not the implementing
model, so the self-review prohibition above is satisfied. Verdict: **`PASS`**, with **no blocking
findings and no non-blocking findings**; recommendation: ready to merge. The reviewer inspected the
implementation and the evidence packet, ran the 28 WP2.3 unit and integration tests, the 12
full-cohort tests and the 42 database-safety tests, independently recomputed the
`data/model/wp2_3_match_assignments.csv` SHA-256, and verified that the bytecode regression test
catches the historical stale-`pyc` bug. Recorded on 2026-08-04 against head
`b8ba8f1ffeb22b0db7813d2f8518d8b8adea8ef3` (PR #6). WP2.2's two slices remain deferred, as stated
in §2 above.

**WP2.6 close.** WP2.6 is closed with the independent Sol review recorded as `PASS` on 2026-08-09.

**WP2.7 close.** WP2.7 closed after the actual implementation and evidence received an independent
GPT-5.6 Sol review `PASS`; ADR 0013 and the WP2.7 closeout record the accepted gate.

**WP2.8 close.** WP2.8 closed after its real development-only reproduction and release packet
received an independent GPT-5.6 Sol review `PASS`; ADR 0014 and the WP2.8 closeout record the gate.

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
- WP2.7 has its own mandatory independent `sol_reviewer` gate. Its real Euro2024 access is limited
  to the single supervised `wp2-7-holdout` execution; post-run checks are synthetic, fixture, or
  metadata-only and must not reload Euro2024 rows or labels.
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
