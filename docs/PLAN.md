# Touchline Intelligence Platform — Execution Plan (v2)

**Supersedes:** `PLAN-v1-superseded.md` and `phases/phase-0..5-*.md`. Those files remain on disk as
reference; where they conflict with this document, this document wins.
**Companion:** [`TARGETING.md`](TARGETING.md) — role fit tiers, employers, artifact↔requirement mapping.

## How to read this plan

This plan is **sequenced, not scheduled.** It does not track hours or weeks. Development is heavily
AI-assisted, which makes typing speed a poor unit of progress and makes *understanding* the real
constraint.

Each milestone is therefore defined by two things:

1. **Ships** — the artifact that must exist and work.
2. **Must be able to defend** — the questions to answer unaided, before the milestone counts as done
   and before its CV claim is used.

The second list is the actual acceptance criterion. Generated code that passes tests but cannot be
explained has not completed a milestone; it has only produced files.

---

## 1. What this builds

One deployed football research product that turns StatsBomb Open Data into a validated relational
dataset, a calibrated shot-quality model, and an analyst-facing interface — with the evidence trail
that makes every number defensible.

```text
StatsBomb Open Data JSON
        │
        ▼
  versioned ingestion ──► ingestion manifest + data-quality report
        │
        ▼
   PostgreSQL ──► SQL/Python feature pipeline ──► experiments + model artifacts
        │                                              │
        └──────────────────────────────────────────► FastAPI ──► Next.js UI
                                                          │
                                                          ▼
                                              Docker + GitHub Actions ──► managed host
```

### Why this shape

Scope is driven by a scan of 30 real job postings across clubs, data providers, betting/trading and
general applied-ML. Methodology and results:
[`research/job-market-methodology.md`](research/job-market-methodology.md).

| Requirement | Essential in | Consequence |
|---|---:|---|
| Python | 30/30 | Core language throughout |
| **Written communication to non-technical audiences** | **21/30** | Cross-cutting requirement, §6 |
| SQL | 18/30 | M1 is a real SQL milestone, not an ORM wrapper |
| Statistics / uncertainty quantification | 11/30 | §5; bootstrap uncertainty is mandatory output |
| Cloud · PyTorch | 8/30 each | Managed deploy now, AWS deferred; PyTorch mandatory, §4 |
| Tracking data | 5/30 | Stretch only, §8 — no open set overlaps StatsBomb |
| Event data | 3/30 | Event data alone is not the selling point |
| TypeScript | 1/30 | Already in the profile — used, not invested in |
| dbt · orchestration · warehouse | 0–2/30 | **Out of scope**, ADR 0007 |

Two findings shaped the sequence more than any technology choice:

1. **The most reachable role shape is engineering, not data science.** M1 is therefore a first-class
   milestone, not a warm-up for the model.
2. **Personal projects count as evidence in junior/graduate postings**, several of which state it
   outright. No mid/senior posting does. Targeting follows this in `TARGETING.md`.

---

## 2. Data scope — settled, with numbers

Counted 2026-07-31 from `competitions.json` and `matches/*.json`; shot rates sampled from 12 WC 2022
and 10 Euro 2024 matches. Full counts are the first output of M1 and replace these estimates.
Recorded as **ADR 0004**.

**Every league season in StatsBomb Open Data is single-team-centric:**

| Competition-season | Matches | Team present in every match |
|---|---:|---|
| Ligue 1 2021/22 · 2022/23 | 26 · 32 | Paris Saint-Germain |
| Bundesliga 2023/24 | 34 | Bayer Leverkusen |
| La Liga 2020/21 | 35 | Barcelona |
| FIFA World Cup 2022 | 64 | — balanced, 32 teams |
| UEFA Euro 2024 | 51 | — balanced, 24 teams |

These are not league seasons; they are one club's season plus its opponents. A "chronological
holdout" inside one of them measures a single team's form curve, not football drift.

**Core cohort — balanced tournaments only:** WC 2018 + Euro 2020 + WC 2022 + Euro 2024,
≈ 230 matches.

WC 2022 is now **measured** rather than estimated (WP0.3 loaded it in full, against pinned Open Data
commit `b0bc9f22` rather than `master`, with per-file hashes in `data/provenance/`): 1,494 shots of which
64 are penalties, leaving **1,430 non-penalty shots and 152 goals** at 10.6% conversion, with
**zero rows missing location, player, outcome, body part or technique**. The earlier 12-match
sample was low by ~18%.

Re-extrapolating the other three tournaments at the measured rate gives roughly **5,100 non-penalty
shots and ~545 goals** for the full cohort. Two source facts worth carrying forward: shootout kicks
are typed `Penalty` and live in period 5, so one `shot_type` filter excludes them; and the
five-bin reliability decision below should be re-checked against the real holdout count once the
remaining tournaments are loaded.

Binding consequences:

- **"One competition/season" is dead.** The largest single slice (WC 2022, ~1,210 shots, ~117 goals)
  leaves ~30 goals in a holdout — a calibration curve on that is noise. Multi-competition is required.
- **The holdout is a tournament holdout and is named that way.** Holding out Euro 2024 changes time
  *and* tournament composition together. That confounding is stated in the model card and write-up.
- **Single-team league seasons are excluded from the core cohort** but retained as a declared
  **selection-bias slice** — which is what makes a genuine competition-level error slice possible.
- Reliability binning follows the holdout goal count (~75 goals ⇒ 5 bins defensible, 10 bins not).
- Only the ~230 selected matches are downloaded, not the whole repository.

---

## 3. Milestones

Sequence: **M0 → M1 → M2 → M3 → M4**, then optional stretch. Each milestone's work packages may be
reordered internally; the milestones themselves may not, because each depends on the previous one's
output. Applications open at the end of **M3**.

---

### M0 — Walking Skeleton

The most important sequencing decision here: **something runs end-to-end and is publicly deployed
before any modelling begins.** v1 put the first working system near the end; that is how a project
reaches month five with nothing to show.

**M0 makes no model claims.** It proves *data → database → API → UI → deployment* and nothing else.
The "prediction" it serves is a **constant base-rate baseline**: the observed conversion rate of the
loaded cohort, returned for every shot. This is honest, trivially correct, and gives M2's real models
something to beat. There is deliberately **no train/test split and no performance claim anywhere in
M0** — publishing a knowingly mis-evaluated model, even labelled as a placeholder, is not a
placeholder, it is a wrong artifact on a public URL.

| WP | Ships |
|---|---|
| 0.1 | Repo skeleton; pinned Python and Node; lockfiles; formatter, linter, type checker; pytest + frontend test runner with one real smoke test each; Docker Compose PostgreSQL with health check and named volume; `.env.example`; typed settings |
| 0.2 | GitHub Actions: install from lockfiles, lint, type check, tests |
| 0.3 | Minimal ingest — one tournament, ~5 tables, no idempotency, no constraints yet |
| 0.4 | Constant base-rate endpoint: cohort conversion rate, computed from loaded data, no model, no split |
| 0.5 | One FastAPI endpoint + minimal Next.js **raw shot map** — real shot locations and real outcomes, no predictions plotted |
| 0.6 | App Dockerfile; GitHub Actions builds and checks the image; Vercel (frontend, free) + Railway (backend, Hobby $5/mo) + Neon (PostgreSQL, free) deploy from their own Git integrations; restrictive CORS; **first live URL**; smoke test against the deployed URLs |

**Must be able to defend:**

- What a container image is versus a running container; what the named volume and health check do.
- Which checks belong in pre-commit versus CI, and what CI catches that a local run does not.
- Why CI builds the image but does not deploy it, and what a platform token in a repository secret
  would have bought and cost.
- Why the CORS allow-list names one origin instead of using `*`, and what a browser does with the
  header's absence.
- Why the base rate is a legitimate baseline and what it would mean for a model to fail to beat it.
- Why M0 publishes no performance metric, and what would be dishonest about publishing one.
- How configuration reaches the application, and why secrets are not in Git.

**Done when:** a stranger can open a URL and see real shots on a pitch; CI is green; the README
states plainly which parts are provisional and which milestone replaces each.

---

### M1 — Data Foundation

The milestone that maps onto the most reachable role shape. SQL is written by hand here — this is
the primary skill gap being closed, and delegating it to an ORM defeats the purpose.

| WP | Ships |
|---|---|
| 1.1 | StatsBomb README and licence review with the date recorded; attribution placement; `DATA_SOURCE.md`; coverage inventory; data dictionary |
| 1.2 | ERD; migrations; keys, foreign keys, uniqueness and check constraints |
| 1.3 | Idempotent ingestion of the 230-match cohort: transactions, source-key upserts, run manifest (source version, scope, counts, status, errors) |
| 1.4 | Data-quality suite and reconciliation report — source counts ↔ table counts, bounds, referential integrity, coverage, missingness |
| 1.5 | **SQL analysis pack** — 10 queries hand-written without an ORM, including one window function; `EXPLAIN` on two, before and after any index |
| 1.6 | Deterministic fixture data; integration test; clean-rebuild reproducibility run |

**Must be able to defend:**

- The grain of every table, and how a join can silently multiply rows.
- Inner versus left join; how `NULL` behaves in comparisons and aggregates.
- What guarantees a rerun cannot duplicate rows, and what happens when a load fails halfway.
- Which checks are database constraints and which are pipeline tests, and why each sits where it does.
- What each index costs, and what evidence justified adding it.
- Why event data, StatsBomb 360 freeze frames, and continuous tracking are three different things.
- Draw the schema from memory and explain one complex join and one upsert.

**Done when:** loading the same source twice changes no counts; a malformed file fails visibly and
preserves the declared transaction guarantee; the 10 queries return results at their stated grain.

---

### M2 — Shot Quality Engine

| WP | Ships |
|---|---|
| 2.1 | Cohort SQL, target definition, exclusions, penalty policy, **feature availability table** — every feature classified available / unavailable / uncertain at prediction time |
| 2.2 | Geometry — distance to goal centre, visible goal angle (numerically stable two-post form), hand-computed test cases, mirrors and bounds; context features added only after documenting coverage |
| 2.3 | **Split design (§5.3)** — named three-way split, group disjointness and chronology proven by tests |
| 2.4 | Base-rate baseline, geometry-only baseline, regularized logistic regression; coefficient and odds interpretation |
| 2.5 | One gradient-boosting model, small declared search space, same locked splits |
| 2.6 | **PyTorch MLP (mandatory, §4)** |
| 2.7 | Calibration (reliability table with counts), error analysis across ≥6 supported slices, **bootstrap uncertainty** and fold dispersion, model card |
| 2.8 | Experiment records, reproducible training command, artifact metadata, clean-run metric reproduction |

Statistics (§5) is taken inside these work packages, after the diagnostic, and only for topics the
diagnostic did not clear.

**Must be able to defend:**

- Derive the distance and visible-angle features, and name the edge cases that break a naive formula.
- How sigmoid and log-odds connect features to a probability; why log loss is the natural loss.
- Brier versus log loss; why accuracy is the wrong metric here; why AUC can look reassuring anyway.
- **Calibration versus discrimination**, and which one a chance-valuation use case depends on.
- Why random row splitting leaks, what grouped validation protects, and what the tournament holdout
  is confounded with.
- Why the base rate needs no correction here, and what resampling would do to a calibrated output (§5.4).
- How preprocessing leakage was prevented, and how the API's features stay identical to training's.
- Which errors were systematic, and how sample size shaped that conclusion.
- Why this is not StatsBomb's xG model.

**Done when:** match IDs never cross folds; the holdout was opened once; every candidate reports on
identical locked rows; calibration was fitted without holdout labels; and no forbidden feature
(outcome, post-shot, provider xG) is in the feature set.

---

### M3 — Analyst Interface & Serving

The profile's strongest differentiator. Across 30 postings the full-stack + interface + design
combination is requested in exactly one role — but almost no analytics portfolio has it, and it is
the cheapest quality signal available here.

| WP | Ships |
|---|---|
| 3.1 | FastAPI: model metadata and metrics, filtered historical shots, prediction for a validated input; model version in every response; structured errors; no arbitrary query exposure |
| 3.2 | Next.js analyst view: pitch and shot map, filters, shot detail panel, calibration/reliability view, sample sizes, **limitations and StatsBomb attribution visible on the page** |
| 3.3 | Deployment hardening: app Docker image, GitHub Actions build→deploy, migrations on boot, health and readiness endpoints, structured logs with request IDs, secret handling |
| 3.4 | Smoke tests against the deployed instance; documented rebuild and rollback |

**Must be able to defend:**

- How training and serving features are guaranteed identical, and what a golden-case test proves.
- The full path from a code push to a running deployed version, and how to roll it back.
- What the health and readiness endpoints actually check.
- How filter queries are kept safe and bounded.
- What drift would look like here, what is *not* monitored, and why that was an acceptable trade.

**Done when:** deployed API and offline model agree on golden cases; the UI plots golden shots
correctly; a rebuild from an empty database is documented and has been performed once.

---

### M4 — Release & Communication

| WP | Ships |
|---|---|
| 4.1 | Technical write-up in English — problem, split diagram, calibration, slices, model choice, limitations |
| 4.2 | **Non-technical stakeholder summary** — the "explain this to a coach" artifact (§6) |
| 4.3 | Demo video in English + screenshots |
| 4.4 | README, repo tidy, final model card, attribution audit |
| 4.5 | CV rewrite against `TARGETING.md`; application list; tracking sheet |

**Must be able to defend:** every claim in §6's CV list, out loud, without notes — and the
limitations section as fluently as the results.

---

## 4. PyTorch — mandatory, bounded

**Decision (ADR 0005).** Hands-on PyTorch experience is a *learning objective*. It is not
conditional on deep learning outperforming classical models, and not conditional on tracking data
existing. It is mandatory inside M2 (WP2.6).

**Specification.**

- A small MLP written with `Dataset`, `DataLoader` and `nn.Module` — not a wrapper library.
- **Identical cohort, identical features, identical saved split IDs, identical metrics** as the
  classical baselines. The artifact's value is the fair comparison, not the model.
- Reproducible training: seeded (torch, numpy, python), config-driven, one experiment record in
  `experiments/` following `docs/experiments/README.md`.
- Reported on the same table as the others: log loss, Brier, discrimination, calibration.
- **It does not need to become the production model.** Losing is an expected, publishable result.

**Pre-registered hypothesis**, written before any run: on ~4,700 rows of tabular data with ~10
features, the MLP is not expected to beat regularized logistic regression. It is expected to match
it or fall slightly short, with worse calibration stability across folds.

### 4.1 Production-model selection rule — pre-registered

**This rule is fixed before any experiment output is viewed.** It exists so that the selection
cannot be rationalised after seeing which model happened to win.

A candidate replaces the incumbent (regularized logistic regression) only if **all four** hold on
the development folds — never on the holdout:

1. **Lower mean log loss**, by a margin exceeding the incumbent's own cross-fold standard deviation.
2. **Lower or equal mean Brier score.**
3. **No worse calibration**: maximum absolute deviation between predicted and observed rate, across
   bins with adequate support, does not increase.
4. **Not less stable**: cross-fold standard deviation of log loss does not increase.

If the four are not jointly satisfied, the incumbent is kept and the comparison is published as-is.
Ties go to the simpler, more interpretable model. **The holdout is never used for selection** — it
is opened once, after selection, to report the chosen model's performance.

**Concepts to be explainable unaided:** tensors and autograd; what `Dataset`/`DataLoader` do and
**why shuffling must not break the match-grouped split**; `nn.Module.forward`; `BCEWithLogitsLoss`
being log loss; optimizer and learning rate; epoch versus batch; how overfitting appears in a
training curve; early stopping; and why small tabular problems usually favour the simpler model.

**Still evidence-based:** whether a larger sequence or spatial deep-learning phase is ever opened.
The tracking research effectively closes it — the open tracking universe is ~20 matches, with the
only cleanly-licensed set at 7. Seven matches cannot train a sequence model, and that is the written
answer if asked.

---

## 5. Statistics — translation, not a course

**Starting position:** an engineering graduate with completed university-level statistics
coursework. This is not a beginner track and there is no introductory block. The goal is to
**translate an existing statistical foundation into defensible football-ML evaluation** — the gap is
ML-specific application, not the underlying mathematics.

### 5.1 Diagnostic first, before M2 WP2.3

Write a one-paragraph answer to each topic in §5.2 from memory, without assistance.
**Anything already explainable and applicable is skipped.** Only unanswered or shaky items enter the
just-in-time queue. Expect roughly half to be skipped.

### 5.2 Topics, taken at the point of use

Never as a phase that blocks implementation. The deliverable for a topic that is *not* skipped is a
short worked example or derivation in `docs/derivations/`.

| Topic | Likely gap? | Taken during |
|---|---|---|
| Logistic regression **as a probability model** — log-odds, coefficient and odds interpretation, why maximum likelihood gives log loss | applied form, not theory | M2 WP2.4 |
| **Grouped and temporal validation** — group disjointness, what a tournament holdout is confounded with | ML-specific, likely new | M2 WP2.3 |
| **Data leakage** — feature availability at prediction time; preprocessing fitted on training only | ML-specific, likely new | M2 WP2.1–2.2 |
| **Log loss and Brier score** — what each measures, why accuracy is wrong here | new naming, familiar mathematics | M2 WP2.7 |
| **Calibration versus discrimination** | ML-specific, likely new | M2 WP2.7 |
| **Bootstrap model comparison** — resampled intervals, fold dispersion | resampling familiar; ML application likely new | M2 WP2.7 |
| Overfitting and regularization — L1/L2, bias–variance in practice | partly familiar | M2 WP2.4–2.5 |
| **Class balance and meaningful baselines** (§5.4) | likely new | M2 WP2.1 |

Bootstrap comparison is mandatory output, not optional analysis: uncertainty quantification is
essential in 11 of 30 scanned postings and in 75% of the betting segment, quoted directly as
*"quantify your uncertainty"*. A model that reports point estimates does not demonstrate it.

### 5.3 The split, named explicitly

v1 said calibration should be fitted on "an appropriate held-out fold". That word carried too much
weight. The split is:

```text
dev matches         → GroupKFold(match_id) → hyperparameter search + feature selection + model selection
calibration set     → matches disjoint from dev → calibration fitting ONLY
tournament holdout  → later tournament → OPENED ONCE, after selection, for the final report
```

**Rules, in the definition of done:** the holdout evaluation is pre-registered, run once, and
reported whatever it shows. No feature that is unknown at the moment of the shot. Provider xG never
enters the feature set.

### 5.4 Class balance — the actual reasoning

The non-penalty conversion rate in this cohort is roughly 8–10%. That is **moderate imbalance, not
extreme**, and it is exactly the regime where logistic regression and gradient boosting estimate
probabilities well without intervention.

**Decision for this project: no SMOTE, no `class_weight`, no threshold tuning.** The reasons are
specific, not doctrinal:

- The output of this system is a **calibrated probability**, not a class label. There is no decision
  threshold, so nothing to rebalance *for*.
- Both techniques change the effective class prior the model is fitted against, which shifts the
  predicted probability distribution away from the observed base rate. Since calibration is a
  headline deliverable here, introducing a known distortion and then correcting for it adds a step
  that buys nothing.
- At ~420 positive cases there is no minority-class starvation problem that resampling would solve.

**What is *not* being claimed:** these are not invalid techniques. Class weighting is reasonable when
the deliverable is a thresholded decision and one error type is genuinely costlier; resampling can
help under severe imbalance (base rates in the fractions of a percent) or with algorithms sensitive
to class ratios. Both can be combined with a subsequent recalibration step that recovers much of the
probability quality. They are declined here because this project's output type and base rate make
them unnecessary — that is the argument, and it is the one to give if challenged.

The practical risk this note exists to prevent: most tutorials on "imbalanced classification"
recommend resampling reflexively, and applying that advice to a calibration-focused project
introduces a distortion that is easy to miss and hard to explain later.

---

## 6. Written communication — cross-cutting, not a phase

70% of scanned postings list communication to non-technical audiences as essential — second only to
Python, ahead of SQL. Code does not demonstrate it.

**Every milestone release produces all four:**

1. a short **technical write-up** in English (problem → decision → evidence → limitations);
2. a **non-technical stakeholder summary** — the "explain it to a coach" version: what the number
   means, where it is trustworthy, where it is not, and what should not be done with it;
3. **screenshots, a live demo, or a short English demo video**;
4. a **CV claim** plus a rehearsed problem–decision–result **interview story**.

A CV claim is not used before its evidence, report, demo, *and* the milestone's "must be able to
defend" list are all complete. Claims cite measured cohort sizes and metrics, never implied
production users or club adoption.

---

## 7. Scope guardrails

**Out of scope, decided on evidence (ADR 0006, ADR 0007):**

- **dbt** — 0 of 30 postings. General data-engineering surveys do not describe this market.
- **Orchestration (Airflow/Dagster)** and **warehouse (Snowflake/BigQuery)** — 1–2 of 30, high setup
  cost, no payoff here.
- **AWS/Azure in the core roadmap** — deployment is Docker + GitHub Actions + one managed target.
  A cloud provider may be added later only for clear learning or targeting value, via an ADR.
- **v1 Phase 3 (Scout Explorer), Phase 4 (Action Value Lab), Phase 5 (360 Spatial)**.
- Kubernetes, microservices, feature stores, Kafka, multiple data providers, complex auth,
  a custom design system.

**Cut-first order when a milestone runs long:** visual polish → extra filters → extra context
features → extra model variants → extra error slices → the stretch tracking module.

**Never cut:** provenance and attribution, idempotency, the named three-way split, leakage controls,
calibration, uncertainty, core tests, limitations, reproducibility, the PyTorch artifact, the
non-technical summary, or any milestone's "must be able to defend" list.

---

## 8. Stretch — tracking module

Entered **only** when M0–M4 are complete, deployed and documented. Tracking is requested in 17% of
postings — more often than event data — so the gap is real, but it does not precede the core.

Constraints established by research:

- **No open tracking dataset overlaps StatsBomb Open Data at match level.** A combined
  "StatsBomb events + open tracking" artifact is impossible; the module stands on its own data.
- **DFL/IDSSE (Bassek et al. 2025)** is the only cleanly licensed option: 7 matches, 25 Hz,
  **CC-BY 4.0**, event-synchronised by the publisher — which matters, because from-scratch
  event↔tracking synchronisation is a research problem in its own right.
- `kloppy` (BSD-3) materially reduces parsing and coordinate work.
- Store Parquet. **Do not load tracking into PostgreSQL.**
- Licence care: PFF FC terms could not be verified (HTTP 530 at check time) — write no code against
  it until the actual agreement is read. Metrica has no formal licence: use, do not redistribute.
- If it does not happen, the gap is stated plainly in `TARGETING.md` rather than papered over.

**A StatsBomb 360 freeze frame is not tracking data and is never presented as such.**

---

## 9. Risks

| Risk | Early signal | Response |
|---|---|---|
| Generated code is not understood | cannot answer a milestone's defence list | the defence list is the gate; no CV claim until it passes |
| Diagnostic clears a topic that was not solid | a metric is reported but cannot be explained on demand | reopen that topic at the point of failure; the diagnostic filters, it does not certify |
| Holdout reopened after a poor result | the urge to "try one more thing" | pre-registered, opened once, reported as-is |
| Selection rationalised after seeing results | criteria discussed only post-hoc | §4.1 rule is fixed before any run |
| PyTorch artifact expands | scope creeping past the MLP comparison | ship the comparison as specified and stop |
| Deployment consumes M3 | repeated environment firefighting | fall back to the M0 managed target; defer hardening |
| Interface becomes a design project | styling before function | one pitch view, one detail panel, plain components |
| Applications wait for perfection | M4 slipping repeatedly | applications open at end of M3 |
| Licence or attribution mistake | any public release without a dated check | dated pre-release checklist; §8 licence flags |

---

## 10. Data rights

Re-read the StatsBomb Open Data README and its linked licence before first ingestion and before
every public release; record the date. Attribute StatsBomb as the source and carry the logo wherever
current terms require — repository, deployed app, reports, demo video.

Document exactly which competitions, seasons and matches are present. Open Data event data,
StatsBomb 360 freeze frames, and continuous tracking data are three different things, and no output
may blur them. Do not redistribute source or derived data unless current terms permit it.

---

## 11. Maintenance

At each milestone boundary, record what was cut and why, and adjust the next milestone. Material
methodology changes get an ADR. Planning records live in `.scratch/` (git-ignored); anything durable
is promoted to `docs/adr/` or `docs/research/`.
