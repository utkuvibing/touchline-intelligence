# Targeting — roles, employers, and evidence mapping

**Companion to** [`PLAN.md`](PLAN.md). The plan decides what gets built; this decides who it is
built for and when to apply.

**Evidence base:** 30 real job postings scanned 2026-07-31 across four segments, plus the UK Home
Office licensed-sponsor register (142,650 rows, same date). Methodology and full frequency results:
[`research/job-market-methodology.md`](research/job-market-methodology.md).

---

## 1. Candidate profile and hard constraints

| | |
|---|---|
| Education | BSc Materials Science Engineering, 2026; university-level statistics coursework |
| Strengths | Full-stack shipping — Python, FastAPI, Streamlit, TypeScript, Next.js, React Native, Supabase; four public projects |
| Closing in this plan | SQL, model evaluation, deployment/CI, applied ML statistics, PyTorch |
| Not closing | Postgraduate degree; years of production experience |
| Location | Open to relocation — Europe and the Americas, **English-speaking workplaces only** |
| Visa | Sponsorship required |
| Applications open | End of **M3** — a live URL exists |

---

## 2. Market reality — read this before setting expectations

The football data-science segment is thinner than its public profile suggests. As of 2026-07-31:

| Source | State |
|---|---|
| `jobsinfootball.com` Data Science category | **7 postings total.** Two marketing/fan analytics, one intern, one US intern, one part-time performance analyst. **Real football modelling roles: 2.** |
| `statsperform.teamtailor.com/jobs` | **12 openings, 0 data science / ML.** |
| `sportsjobs.online` front page | **0 football DS/ML roles.** |
| `careers.arsenal.com` | 6 openings, 1 technical. |
| `sportstechjobs.com` football-analytics | 8 listings, 6 posted 1–2 years ago and closed. |
| Twelve Football | No public careers page found. |

**At any given moment, open football event/tracking modelling roles in Europe are in the single
digits.** Treating football as the only employment destination is a bottleneck, not a strategy. The
portfolio is built to read simultaneously as football analytics *and* as general applied engineering.

**But the fallback is not the easy option.** Postgraduate requirements by segment: clubs 22%,
providers 29%, betting 38%, **general applied-ML 50%**. The non-football market is larger but
*stricter* on credentials. Neither door is soft.

---

## 3. Fit tiers

**Job advertisements are wish lists, not checklists.** Postings routinely bundle every skill the team
might want across several years of the role. Hiring managers expect partial matches; the common
industry heuristic is that meeting most of the essentials is enough to apply, and underestimating
one's own fit costs more opportunities than overestimating it. The tiers below classify **fit**, not
permission — nothing here is a reason not to apply.

### Strong fit — apply first, apply broadly

Every essential requirement is either met by the finished portfolio or already in the profile.

- **Junior data engineer / analytics engineer** at sports-betting or sports-tech companies.
  Exemplar: **Football Radar — Data Engineer (Junior or Mid)** — SQL, query optimisation,
  *"a decent level of Python"*, pipelines; AWS *"a bonus, but not essential"*; no degree requirement.
  Football Radar holds a Skilled Worker licence. Currently closed; watch for reopening.
- **Junior applied-ML / data platform roles at sponsoring general tech companies.**
  Common core is Python + SQL + communication + a personal project, several stating it as required
  (Wise: *"A self-started side project(s) that you are proud to talk about"*). Germany and the
  Netherlands are the more realistic version of this route than the UK.

### Plausible fit — apply, expect to be stretched in interview

Most essentials met; one or two require either a favourable read of the portfolio or on-the-job growth.

| Role | The gap |
|---|---|
| **The FA — ML Engineer** | No degree requirement, but wants cloud ML ops and production monitoring beyond what the core ships. |
| **Sportec Solutions — Football ML Engineer** (Germany) | Python + PyTorch + SageMaker. Degree requirement is only *"abgeschlossenes Studium"*; sole language requirement *"Sehr gute Englischkenntnisse"*. **Best non-UK route.** |
| **City Football Group — Junior Data Scientist** | Python and SQL requirements are met; "time series analysis and numerical simulation" is not. Counts football work *"either as a hobby"*. |
| **Football Radar — Club Data Scientist (Junior)** | Wants tracking-data experience and *"make defensible modelling decisions, quantify your uncertainty"* — the second half is directly addressed by M2. |

### Stretch fit — apply when it appears, cost is low, expect silence

One hard blocker, usually a credential or years of production experience. Worth applying because
blockers are sometimes soft and a strong portfolio occasionally overrides them.

- **Arsenal — Research Engineer.** The irony of this scan: on *technology* it is the closest match in
  all 30 postings — Python, SQL and **TypeScript** essential, *"Eye for design"* essential,
  *"track record designing scalable applications"* essential, PyTorch only desirable. The full-stack
  + TS + visualisation combination is requested in **exactly one** posting, and it is this one.
  Sole blocker: *"Advanced qualification in a quantitative discipline"*.
- **Stats Perform Data Scientist** (MSc/PhD + 3 years + neural architecture design),
  **Liverpool Lead Data Scientist** (MSc/PhD + 5 years), **Zalando Senior Applied Scientist**
  (PhD + 3 years).

### Not viable — do not spend effort

Blocked by something the portfolio cannot change.

| Employer / role | Blocker |
|---|---|
| PSG · SkillCorner | Require French. |
| Wise · SentiLink · Smartodds | State **no visa sponsorship** outright. |
| Chelsea FC | Holds **International Sportsperson** licence only — can sponsor players, not data scientists. |
| SkillCorner · Swish · Second Spectrum | Absent from the UK sponsor register entirely. |
| SkillCorner Computer Vision Scientist | 3+ years production CV/DL **and** French. |

---

## 4. Employers — sponsorship, remote, language

Skilled Worker licence status verified against the Home Office register, 2026-07-31.

| Employer | Licence | Remote | Notes |
|---|---|---|---|
| Football Radar | ✅ | Partial | Strong-fit target. Betting + club services — the bridge segment. |
| Sportec Solutions (DE) | n/a — Germany | ? | **Best non-UK route.** English sufficient. |
| The FA | ✅ | Hybrid | Plausible fit, no degree requirement. |
| City Football Group | ✅ | *"partial remote working is permitted"* | Plausible fit. |
| Hudl | ✅ | *"we're open to remote candidates"* | Most remote-friendly. |
| Liverpool FC | ✅ | Lead DS role *"or fully remote"* | Stretch (seniority). |
| Arsenal | ✅ | On-site, matchday flexibility expected | Stretch (degree). |
| Brentford | ✅ | **"No working from home possible"** | |
| Brighton · Man City · Premier League · Catapult · Genius Sports | ✅ | varies | |
| Smartodds | ✅ (licence) | — | States **no sponsorship** despite holding one. |
| Chelsea FC | ⚠️ International Sportsperson only | — | Not viable. |
| SkillCorner · Swish · Second Spectrum | ❌ absent | — | Not viable. |

### Visa arithmetic — the practical constraint is salary, not licence

UK Skilled Worker, rules read 2026-07-31:

- General threshold: **£41,700**, or the occupation's going rate, whichever is higher.
- SOC 2433 (statisticians / data scientists) going rate: **£55,100**.
- New-entrant discount (under 26, or switching from Student/Graduate): the higher of **£33,400** and
  70% of the going rate → **≈ £38,570**.

Football Radar Graduate DS starts at £28,800 — below threshold; only an offer in the upper half of
its range clears. Brentford's £36,000 floor also fails. Postings that clear comfortably want 3+ years
or a postgraduate degree.

**Junior + UK sponsorship is a narrow corridor.** Not closed, but it depends on a first offer above
~£38.5k. **Germany deserves proportional effort, not backup status.**

---

## 5. Artifact ↔ requirement mapping

What each piece of the build is evidence *for*. Also the justification record for `PLAN.md` §7.

| Requirement | Essential in | Evidence produced | Milestone |
|---|---:|---|---|
| Python | 30/30 | Entire codebase | all |
| **Written communication (non-technical)** | **21/30** | Stakeholder summary + demo video per release | M4, cross-cutting |
| SQL | 18/30 | Hand-written query pack, `EXPLAIN` analysis, schema + constraints | M1 |
| Statistics / uncertainty | 11/30 | Calibration, proper scores, bootstrap CIs, fold dispersion, `docs/derivations/` | M2 |
| Cloud / deployment | 8/30 | Docker image, GitHub Actions build→deploy, managed host, health checks, logs | M0, M3 |
| PyTorch / deep learning | 8/30 | MLP under identical cohort/split/metrics, with a pre-registered selection rule | M2 WP2.6 |
| Data visualisation | 5/30 | Shot map, reliability plots, analyst interface | M3 |
| CI/CD | 3/30 | GitHub Actions from the first milestone | M0 |
| Docker | 2/30 | Local Postgres + app image | M0, M3 |
| Event data | 3/30 | 230-match cohort, provenance, quality report | M1 |
| Football knowledge | 4/30 E, 7/30 D | Shot geometry, penalty policy, error slices, stakeholder summary | M2, M4 |
| Full-stack / interface design | 1/30 | FastAPI + Next.js analyst view | M3 |
| **Tracking data** | **5/30** | ⚠️ **Not produced by the core.** Stretch only (`PLAN.md` §8) | stretch or gap |

---

## 6. CV claims, gated by evidence

No claim is used before its milestone's report, demo, **and defence list** are complete. Insert real
counts and measured metrics only after the final locked run.

| After | Claim |
|---|---|
| M0 | Built and deployed a containerised Python/FastAPI + Next.js application with PostgreSQL and GitHub Actions CI. |
| M1 | Designed a PostgreSQL football-event schema and idempotent ingestion pipeline over a documented 230-match StatsBomb Open Data cohort, enforcing provenance, relational constraints, count reconciliation and automated data-quality checks. |
| M2 | Built a calibrated shot-quality model on a versioned cohort, comparing a logistic baseline, gradient boosting and a PyTorch MLP under identical match-grouped splits and a locked tournament holdout, with calibration, error slicing and bootstrap uncertainty. |
| M3 | Served the model through a versioned FastAPI contract and a TypeScript analyst interface, deployed via Docker and GitHub Actions with health checks, structured logging and a documented rebuild path. |
| M4 | Published technical and non-technical write-ups and a recorded demo covering methodology, calibration and documented limitations. |

Never imply club adoption, production users, or that this reproduces StatsBomb's proprietary xG.

---

## 7. Application waves

**Wave 1 — end of M3.** A live URL exists. Target strong fit exclusively, plus any open
graduate-scheme deadline that would otherwise expire. Volume over selectivity.

**Wave 2 — after M4.** Write-ups and demo exist. Add plausible fit, continue strong fit, and send
stretch-fit applications whenever one appears — they cost little and blockers are sometimes soft.

**Standing rule:** applications wait for the portfolio to be *deployed*, not *finished*. Those are
different moments and only the first one matters.

---

## 8. Known gaps and the honest answer to each

Interviewers ask about absences. These are prepared answers, not apologies.

| Gap | Answer |
|---|---|
| **No tracking data** | The open tracking universe is ~20 matches; the only cleanly-licensed set (DFL/IDSSE, CC-BY 4.0) is 7 matches, and no open tracking set overlaps StatsBomb at match level. Seven matches cannot support a modelling claim. If the stretch module ran, it is a method demonstration, not a result. **Never call StatsBomb 360 freeze frames tracking data.** |
| **Deep learning is not the production model** | It was implemented and evaluated on identical splits, features and metrics, against a selection rule fixed before any results were seen. On ~4,700 tabular rows the expected outcome was that it would not win, and that was written down in advance. Choosing the simpler calibrated model is the decision; the comparison is the evidence. |
| **No AWS / cloud platform** | Deployment is Docker + GitHub Actions + a managed target: real containerisation, real CI/CD, real migrations and health checks. Provider specifics are a configuration layer over the same concepts, deliberately deferred rather than half-learned. |
| **No postgraduate degree** | Point at the evidence trail: pre-registered holdout, named three-way split, calibration without holdout contamination, documented limitations. Several junior postings explicitly accept personal projects as evidence. |
| **Single-team bias in some data** | Raise it before being asked. Knowing that every StatsBomb league season is one club's season — and excluding those from the core cohort while keeping them as a declared selection-bias slice — is the strongest data-literacy signal in the project. |
| **No resampling for class imbalance** | Deliberate. The output is a calibrated probability with no decision threshold, and the base rate (~8–10%) is moderate. Resampling and class weighting shift the effective prior and distort the probability distribution, which is the exact thing being measured. They are appropriate tools elsewhere — thresholded decisions, severe imbalance, or paired with recalibration — just not here. |
| **Limited football domain depth** | Football knowledge is *desirable* in most scanned postings, not essential; the stakeholder summary is the demonstration. Be straightforward that domain depth is in progress. |

---

## 9. Maintenance

Re-scan postings before each application wave; the market is small enough that a handful of new
openings materially changes the picture. Update §4 when a sponsorship or language fact changes.
When a gap in §8 closes, move it into §5.
