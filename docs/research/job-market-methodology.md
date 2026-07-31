# Job-market requirement scan — methodology and results

**Date of scan:** 2026-07-31 · **Sample:** 30 job postings · **Purpose:** ground the scope decisions
in [`../PLAN.md`](../PLAN.md) and the fit tiers in [`../TARGETING.md`](../TARGETING.md) in observed
demand rather than general industry advice.

This is a summary of methodology and headline results. It is not a dataset release: postings are
third-party copyrighted text, so requirement wording is quoted only in short fragments where the exact
phrasing carries the finding.

---

## 1. Method

**Segments.** Four, chosen because the portfolio is intended to read as football analytics *and* as
general applied engineering:

1. Clubs and national teams
2. Data providers
3. Betting and trading
4. General applied-ML (non-football, same technical core)

At least five postings per segment. Closed and archived postings were included and marked as such —
excluding them would bias the sample toward whatever happened to be open on one day, which in this
market is very few things.

**Coding rules.** Each requirement was coded `essential` where the posting listed it under a required
or essential heading, `desirable` where listed as preferred, desirable or nice-to-have, and neither
where a technology appeared only as a description of the team's existing stack. This distinction
matters: several tools appear in stack descriptions far more often than in candidate requirements.

**Sponsorship verification.** Rather than inferring from posting text, the UK Home Office register of
licensed sponsors (142,650 rows, downloaded 2026-07-31) was checked directly for each named employer,
and salary thresholds were read from current GOV.UK Skilled Worker guidance and the Immigration Rules
Appendix Skilled Occupations.

---

## 2. Limitations

State these before using the numbers.

- **n = 30.** Percentages are indicative, not precise. A difference of one or two postings is noise.
- **Single point in time.** The market is small enough that a handful of new openings shifts the
  picture; re-scan before each application wave.
- **Coding involves judgement**, particularly where a posting mixes requirements and responsibilities
  in one list.
- **Segment sizes are unequal**, and the general applied-ML segment is a deliberately narrow slice of
  a very large market chosen for comparability, not representativeness.
- **Link rot is severe.** Two postings encountered during the scan returned HTTP 404 within the same
  session, which is why findings were recorded as quoted text rather than references.

---

## 3. Headline finding: market volume

Before any requirement analysis — the football modelling segment is thinner than its public profile
suggests. On the scan date:

| Source | Observed |
|---|---|
| `jobsinfootball.com` Data Science category | 7 postings; 2 were genuine football modelling roles |
| `statsperform.teamtailor.com/jobs` | 12 openings, none in data science or ML |
| `sportsjobs.online` front page | no football DS/ML roles |
| `careers.arsenal.com` | 6 openings, 1 technical |
| `sportstechjobs.com` football-analytics | 8 listings, 6 posted 1–2 years earlier and closed |

Open football event or tracking modelling roles in Europe appear to be in the single digits at any
given moment. This is the single most consequential finding for planning: a portfolio aimed
exclusively at football is aimed at a very narrow target.

---

## 4. Requirement frequency

Out of 30 postings.

| Requirement | Essential | Desirable |
|---|---:|---:|
| Python | 30 | 0 |
| **Written communication to non-technical audiences** | **21** | 2 |
| SQL / relational databases | 18 | 4 |
| Statistics, probability, uncertainty quantification | 11 | 1 |
| Cloud platform (AWS / Azure / GCP) | 8 | 5 |
| PyTorch / deep-learning framework | 8 | 2 |
| Data visualisation | 5 | 2 |
| Tracking data | 5 | 4 |
| Football domain knowledge | 4 | 7 |
| Event data | 3 | 2 |
| CI/CD | 3 | 2 |
| Docker / containerisation | 2 | 2 |
| Data warehouse | 2 | 3 |
| Orchestration (Airflow / Dagster) | 1 | 1 |
| TypeScript / JavaScript | 1 | 0 |
| Notebooks / Jupyter | ~1 | 0 |
| dbt | **0** | **0** |

### Four results that changed decisions

**Communication ranks second, above SQL.** At 21 of 30 essential, written communication to
non-technical audiences is the most consistent requirement after Python itself. Postings phrase it
concretely — one asks for results communicated *"typically in writing, and often to a less technical
audience"*. Code does not evidence this; a written artifact does. It became a cross-cutting mandatory
requirement rather than an optional write-up.

**dbt is absent, and notebooks are near-absent.** Widely-cited general data-engineering figures put
dbt in a majority of postings; in this sample it appears in none. Several postings additionally ask
for the *opposite* of notebook-centric work, requesting production-quality code rather than analysis
scripts, and pipelines rather than research prototypes. The plan's existing bias toward reproducible
commands over notebooks was correct.

**Tracking data is requested more often than event data** (5 essential versus 3). A portfolio built
solely on event data therefore addresses the less-demanded half of the pair — worth knowing, and
worth stating plainly rather than obscuring.

**Football knowledge is mostly desirable; the technical core is what gates.** Four postings list it as
essential against seven as desirable. The practical reading is that Python, statistics and
communication open the door and football knowledge differentiates between otherwise-equal candidates.

---

## 5. Credentials, evidence and sponsorship

**Postgraduate requirements**, by segment: clubs 22%, providers 29%, betting 38%, general applied-ML
50%. The non-football segment — often assumed to be the easier fallback — is the strictest on formal
credentials. Overall, 10 of 30 postings require a postgraduate degree or an "advanced qualification".

**Personal projects are explicitly accepted as evidence** in five postings, one requiring
*"a self-started side project(s) that you are proud to talk about"* and another counting football data
work undertaken *"as a hobby"*. Every such posting is at junior or graduate level; no mid or senior
posting in the sample treats personal projects as qualifying evidence. This bounds who a portfolio can
realistically persuade.

**Sponsorship.** Most named UK employers in the sample hold Skilled Worker licences. One club holds an
International Sportsperson licence only — it can sponsor players but not technical staff — and three
companies were absent from the register entirely, which is not discoverable from posting text.

The binding constraint is salary rather than licence status. The general threshold is £41,700 or the
occupation's going rate, whichever is higher; the going rate for the relevant occupation code is
£55,100. A new-entrant discount reduces this to roughly £38,570. Several graduate-level postings in
this market advertise floors below that figure, so the offer must land in the upper part of its range
to be sponsorable. Postings that clear the threshold comfortably generally require three or more years
of experience or a postgraduate degree.

---

## 6. How these results are used

- Scope inclusions and exclusions: [`../adr/0007-scope-exclusions-on-market-evidence.md`](../adr/0007-scope-exclusions-on-market-evidence.md)
- Deployment depth: [`../adr/0006-deployment-approach.md`](../adr/0006-deployment-approach.md)
- PyTorch inclusion: [`../adr/0005-bounded-pytorch-artifact.md`](../adr/0005-bounded-pytorch-artifact.md)
- Fit tiers and application waves: [`../TARGETING.md`](../TARGETING.md)

**Job advertisements are wish lists, not checklists.** They bundle everything a team might want across
the life of a role. These frequencies describe what employers *ask for* in aggregate; they do not
define a threshold any individual candidate must clear before applying.

## 7. Refresh

Re-run before each application wave. The volume finding in §3 is the most time-sensitive; the
requirement frequencies in §4 are more stable.
