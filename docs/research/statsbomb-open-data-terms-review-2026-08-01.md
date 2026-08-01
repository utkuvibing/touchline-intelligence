# StatsBomb Open Data terms review — 2026-08-01

**Review date:** 2026-08-01
**Purpose:** record the first-party terms checked for M1/WP1.1. This is a source record, not legal
advice and not a conclusion about an unaddressed use case.

## Sources reviewed

The former `statsbomb/open-data` URL currently redirects to the official
[`hudl/open-data`](https://github.com/hudl/open-data) repository. On the review date, its `master`
tip was [`b0bc9f22dd77c206ddedc1d742893b3bbe64baec`](https://github.com/hudl/open-data/tree/b0bc9f22dd77c206ddedc1d742893b3bbe64baec),
committed 2026-05-26. The following are the primary sources reviewed at that revision:

1. [Repository README](https://github.com/hudl/open-data/blob/b0bc9f22dd77c206ddedc1d742893b3bbe64baec/README.md)
2. [StatsBomb Public Data User Agreement (`LICENSE.pdf`)](https://github.com/hudl/open-data/blob/b0bc9f22dd77c206ddedc1d742893b3bbe64baec/LICENSE.pdf), which identifies itself as last updated 8 September 2023
3. The README's [Media Pack link](https://statsbomb.com/media-pack/)

## What the sources say

### Permitted purpose

The README says that certain leagues are freely available for public use “for research projects and
genuine interest in football analytics.” The agreement's §1.1 describes access to the service for
analysis, research, and shared ideas and understanding of the data. Its opening text also says that
analysis or conclusions created from the data may be shared publicly, while making clear that they
are not necessarily StatsBomb's opinions or analytical insights. [README](https://github.com/hudl/open-data/blob/b0bc9f22dd77c206ddedc1d742893b3bbe64baec/README.md) · [agreement, p. 1](https://github.com/hudl/open-data/blob/b0bc9f22dd77c206ddedc1d742893b3bbe64baec/LICENSE.pdf)

### Data redistribution and commercial use

The agreement is explicit that the user may not “edit, distort, distribute, reproduce, sell or in
any way provide” the data to an external or third party (§1.2.1). It also prohibits commercial
exploitation of the data or analysis derived from the service (§1.2.2). Section 7 separately says
that the data is StatsBomb property and prohibits modifying, transferring, distributing, licensing,
selling, or otherwise exploiting it except as expressly permitted or with prior written consent.
[Agreement, pp. 1 and 4](https://github.com/hudl/open-data/blob/b0bc9f22dd77c206ddedc1d742893b3bbe64baec/LICENSE.pdf)

Accordingly, this review records no permission to redistribute raw JSON, derived datasets, database
dumps, or data-bearing fixtures. It also records no conclusion about whether a particular public
portfolio, API response, screenshot, or employment-related activity is commercial exploitation: the
agreement does not define those cases in the text reviewed. Obtain clarification from StatsBomb/Hudl
before relying on a broader interpretation.

### Attribution and logo

For published, shared, or distributed research, analysis, or insights, the README says to state the
data source as StatsBomb and use the StatsBomb logo. The agreement is stronger: §1.4 requires the
user to accredit any publication of analysis formed from StatsBomb data with the StatsBomb brand
logo. [README](https://github.com/hudl/open-data/blob/b0bc9f22dd77c206ddedc1d742893b3bbe64baec/README.md) · [agreement, p. 2](https://github.com/hudl/open-data/blob/b0bc9f22dd77c206ddedc1d742893b3bbe64baec/LICENSE.pdf)

The README points to the Media Pack for that logo. On 2026-08-01, that URL redirected to a Hudl
StatsBomb product page rather than a standalone media-pack asset. This review therefore confirms the
logo requirement but does not claim that the current linked page provides a downloadable or
redistributable logo asset. Preserve the existing text attribution and resolve the current logo asset
or obtain written direction before the next public release.

## Boundaries retained by this project

- Attribute the source as **StatsBomb** wherever this project publishes research, analysis, or
  insights, and retain visible logo treatment once a current approved asset is confirmed.
- Keep downloaded Open Data, database dumps, and other data-bearing artifacts out of Git unless
  written permission establishes that publication path.
- Describe StatsBomb Open Data as event data. The repository separately lists selected StatsBomb 360
  files; neither source reviewed grants a basis to describe those freeze frames as continuous tracking
  data.

## Review trigger

Re-check the official README, agreement, and Media Pack link before first M1 ingestion that expands
scope and before every public release. Record any changed text, repository revision, or written
clarification here or in its successor note.
