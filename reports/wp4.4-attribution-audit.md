# WP4.4 attribution audit

**Audit date:** 2026-08-25
**Scope:** M4 WP4.4 — repository, deployed interface, published outputs. This report records the
pre-release provider-terms re-check required by `docs/PLAN.md` §10 and doubles as the WP4.4 working
evidence record. It is not legal advice and does not clear any unresolved release gate.

## Terms re-check — recorded as of 2026-08-25

Prior full review: an internal first-party terms review dated 2026-08-01, kept as a local
historical record under `docs/research/` and deliberately not published; its public-facing
conclusions are mirrored in [DATA_SOURCE.md](../DATA_SOURCE.md). This re-check verifies the same
first-party sources at the project's pinned revision; nothing in them was found to have changed at
that revision.

### 1. Open Data repository README

- **Source:** [README at pinned revision `b0bc9f22dd77c206ddedc1d742893b3bbe64baec`](https://github.com/hudl/open-data/blob/b0bc9f22dd77c206ddedc1d742893b3bbe64baec/README.md), fetched from the raw file URL on 2026-08-25.
- **Version/date exposed by the source:** none beyond the pin itself — the README carries no
  independent version number or date; its identity is the commit revision.
- **Requirement confirmed unchanged:** for published research, analysis or insights based on the
  data, state the data source as **StatsBomb** and use the logo, which the README says is available
  in its Media Pack.

### 2. Public Data User Agreement (`LICENSE.pdf`)

- **Source:** [`LICENSE.pdf` at the same pinned revision](https://github.com/hudl/open-data/blob/b0bc9f22dd77c206ddedc1d742893b3bbe64baec/LICENSE.pdf), confirmed present and served (161 KB) on 2026-08-25.
- **Version/date exposed by the source:** the file's embedded PDF metadata explicitly exposes the
  title **"StatsBomb Public Data User Agreement"**. No version identifier or date was extractable
  from the document itself at review time (the PDF body text is not recoverable by this review's
  tooling), so both are recorded as **not stated** rather than inferred.
- **Historical observation, carried forward as such:** the dated 2026-08-01 first-party review
  recorded the document self-declaring "last updated 8 September 2023". That statement belongs to
  the earlier review; it was not re-verified here and is not re-asserted as today's finding.

## Attribution matrix

Every location below was verified on 2026-08-25. Form is text unless noted.

| Location | Form | Verification | Result |
|---|---|---|---|
| Repository `README.md` | Logo + text | Inspected tracked file: official wordmark (`assets/statsbomb-logo.svg`) linked to the Open Data repository; pinned-commit statement; "does not reproduce StatsBomb's proprietary xG model" notice | Present |
| `DATA_SOURCE.md` | Text | Inspected tracked file: source/rights section, pinned revision, terms-review dates (2026-08-01; logo-provenance update 2026-08-24) | Present |
| `MODEL_CARD.md` | Text | Inspected tracked file: source section names StatsBomb Open Data at the pinned commit and states the model is not StatsBomb's proprietary xG | Present |
| Deployed frontend ([live page](https://touchline-intelligence.vercel.app)) | Logo + text | Text credit verified by live fetch 2026-08-25 ("SOURCE AND TERMS — Data provided by StatsBomb through the StatsBomb Open Data repository"), plus "Not StatsBomb xG" limitations card and closed-publication-gate notice. The unmodified logo (`frontend/public/statsbomb-logo.svg`, byte-identical to `assets/statsbomb-logo.svg`) is rendered above that credit on this branch; **live logo confirmation is pending post-merge deployment** | Text present (live); logo pending deploy |
| API HTTP surface | Text | Inspected code: OpenAPI summary names StatsBomb Open Data (`main.py`), coordinate fields labelled "StatsBomb pitch coordinate"; responses label the coordinate system `"StatsBomb"` | Present |
| Quality report (CLI artifact) | Text | Inspected code: `attribution = "Data provided by StatsBomb."` (`backend/src/touchline/quality.py`), rendered by `poe quality`; this is an offline report, not an HTTP response | Present |
| Source-ingestion module | Text | Inspected code: `backend/src/touchline/ingest/source.py` docstring carries the provider credit and repository URL | Present |
| WP4.1 technical write-up | Text | Inspected tracked article: closing line credits StatsBomb with link; §8 states non-equivalence to StatsBomb's xG; §9 notes on-page attribution | Present |
| WP4.2 stakeholder summary | Text | Inspected tracked article: closing line "Data provided by StatsBomb."; body states the model is not StatsBomb's xG and models no tracking | Present |
| `LICENSE` / repo licence posture | Text | Inspected file: source-available read-only publication notice; match data remains governed by StatsBomb/Hudl's own agreement | Present |
| Demo video (WP4.3) | — | **Postponed — audit item pending WP4.3.** Per the WP4.3 rights precheck (2026-08-24), production proceeds deployed-state-only with visible attribution on every capture; this audit must be extended before any video publication | Pending |

## Logo asset status

The tracked asset [`assets/statsbomb-logo.svg`](../assets/statsbomb-logo.svg) is stored unmodified
per the [DATA_SOURCE.md](../DATA_SOURCE.md) update of 2026-08-24 — the official Hudl StatsBomb
wordmark SVG retrieved through a dated web.archive.org capture after the Media Pack page was
retired. No logo was invented or altered. The agreement's accreditation requirement (§1.4 per the
2026-08-01 review) is met in the repository by logo + text together. On this branch the same
unmodified asset is served from `frontend/public/statsbomb-logo.svg` and rendered beside the text
credit in the deployed interface's source-and-terms footer; live confirmation of that addition is
pending post-merge deployment, so the surface is recorded as partially verified above.

## Unresolved gates restated

1. **Row-level historical publication stays closed.** Neither reviewed source resolves whether
   publishing row-level historical probabilities is permitted analysis or prohibited redistribution;
   `/model/shots` remains fail-closed and this audit changes nothing about that.
2. **Redistribution boundary unchanged by WP4.4.** The existing public `/shots` surface of recorded
   World Cup 2022 source facts remains exactly as deployed while the redistribution question is
   unresolved; this work package expands neither its scope nor its schema. Historical model
   predictions via `/model/shots` remain closed. Raw source JSON, database dumps and derived
   data-bearing artifacts are not part of the published repository; committed fixtures remain
   synthetic.
3. **Product descriptions stay separated.** Event data, event-embedded shot freeze frames,
   StatsBomb 360 and continuous tracking are described as distinct products everywhere they appear.

## WP4.4 change record (working evidence)

Implemented 2026-08-25 against `origin/main` at `cb3d69b`, per the approved plan in
`.scratch/wp4.4-plan.md`:

- Force-tracked the three methodology contracts cited by the model card:
  `wp2_1-cohort-and-leakage-contract.md`, `wp2_2-geometry-contract.md`,
  `wp2_3-split-and-evaluation-contract.md` (each screened for private material before publishing;
  all three carry their own "Data provided by StatsBomb." attribution).
- Fixed five measured link/tracking defects (three GitHub-dead contract links in `MODEL_CARD.md`;
  wrong-depth Model Card link in the WP4.2 summary; ADR 0006 reference in `docs/DEPLOYMENT.md`
  reworded to prose).
- Bounded model-card header pass: status/header text and cross-links to the two WP4 articles only;
  metrics, counts, hashes, identifiers, cohort definitions, limitations and historical claims are
  byte-identical (verified by diff review).
- README finalized to the honest M4 state (demo video postponed) with links to both published
  articles; both articles' draft banners flipped to published-in-repository.
- Added `scripts/check_docs_links.py` (manual; documented for contributors in `AGENTS.md`'s common
  commands) so the tracked-relative-link property this audit depends on stays checkable.

## Revision 2 — review fixes (2026-08-25)

Applied against review findings on `codex/wp4.4-closeout`, keeping WP4.4 scope unchanged:

1. The prior-review citation above no longer links the untracked internal research note.
2. The checker's public documentation point moved to tracked `AGENTS.md` (the earlier draft cited
   the local-only development guide).
3. The deployed-interface matrix row and logo-status section now record the added unmodified logo
   and mark the surface partially verified: text confirmed live, logo confirmed on branch pending
   post-merge deployment.
4. The redistribution gate statement states the `/shots` and `/model/shots` boundary precisely;
   the WP4.1 write-up's limitation item was reworded to say specifically that historical row-level
   model predictions remain closed while the descriptive WC2022 outcome map stays public.

WP4.4 completion remains **not** claimed; independent review and the remaining milestone gates are
still open.
