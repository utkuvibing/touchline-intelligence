# Data source, coverage, and dictionary

This document owns the source revision, measured core-cohort coverage, and physical field meanings.
The ordered SQL migrations and loader are the implementation source of truth. WP1.1 through WP1.6
are complete. WP1.4's read-only scoped reconciliation report records whether the database audit
actually executed; author manual sampling verification passed on 2026-08-02. WP1.6's clean-rebuild
record pins the exact succeeded database run proposed as the Phase 2 input. The two publication
gates below remain open and are not cleared by milestone completion.

## Source, rights, and attribution

Data is provided by **StatsBomb** through the
[StatsBomb Open Data repository](https://github.com/statsbomb/open-data).

| Item | Value |
|---|---|
| Pinned revision | [`b0bc9f22dd77c206ddedc1d742893b3bbe64baec`](https://github.com/hudl/open-data/tree/b0bc9f22dd77c206ddedc1d742893b3bbe64baec) |
| Revision date | 2026-05-26 |
| Internal core cohort | WC 2018 `43/3`; Euro 2020 `55/43`; WC 2022 `43/106`; Euro 2024 `55/282` |
| Public API scope | FIFA World Cup 2022, competition `43`, season `106` |
| Local cache | `data/statsbomb/b0bc9f22dd77/`, git-ignored and revision-keyed |
| Provenance | [`data/provenance/core-cohort.json`](data/provenance/core-cohort.json) |
| Terms review | 2026-08-01 — the repository README and the linked Public Data User Agreement PDF at the pinned revision |

The reviewed README requires StatsBomb attribution and logo use for published analysis. Text
attribution is present in the repository, deployed page, and published material. Two release gates
remain unresolved: the Media Pack did not expose a clearly approved downloadable logo, and the
agreement did not clearly resolve whether a public row-level API is permitted analysis or prohibited
redistribution. Do not invent a logo, publish database dumps, or expand public row-level coverage
until StatsBomb/Hudl clarifies those points. This is a source-text review, not legal advice.

Update 2026-08-24: after the Media Pack page was retired from statsbomb.com, the official
Hudl StatsBomb wordmark SVG served by statsbomb.com itself was retrieved through a dated
web.archive.org capture of that domain and stored unmodified as
[`assets/statsbomb-logo.svg`](assets/statsbomb-logo.svg) for README attribution; no logo was
invented or altered, and the row-level publication gate is unchanged.

The committed fixture files are synthetic, fictional test data. They are not copied match data.

## Measured source inventory

The core-cohort provenance manifest covers **465 files**: one competitions file, four match files,
230 event files, and 230 lineup files. No `three-sixty` file is read. The `shot.freeze_frame` arrays
described below are embedded in event files; they are not StatsBomb 360 data and are not continuous
tracking.

| Entity / fact | Exact four-tournament value |
|---|---:|
| Competitions / seasons / selected pairs | 2 / 4 / 4 |
| Matches / match-team roles | 230 / 460 |
| Teams / distinct players | 54 / 1,989 |
| Lineups / memberships | 460 / 11,062 |
| Position intervals / cards | 9,615 / 825 |
| Possessions | 39,262 |
| Events | 843,050 |
| Directed related-event references | 1,227,110 |
| Shots | 5,829 |
| Embedded shot freeze-frame actors | 78,866 |
| Internal eligible non-penalty descriptive rows / goals | 5,606 / 507 |
| Public WC 2022 descriptive cohort | 1,430 shots, 152 goals, 10.63% |
| Public WC 2022 shot rows | 1,494 |

| Tournament | Matches | Events | Relations | Shots | Memberships | Freeze actors |
|---|---:|---:|---:|---:|---:|---:|
| WC 2018 (`43/3`) | 64 | 227,825 | 344,808 | 1,706 | 2,886 | 22,092 |
| Euro 2020 (`55/43`) | 51 | 192,664 | 280,004 | 1,289 | 2,345 | 17,159 |
| WC 2022 (`43/106`) | 64 | 234,637 | 330,844 | 1,494 | 3,244 | 20,327 |
| Euro 2024 (`55/282`) | 51 | 187,924 | 271,454 | 1,340 | 2,587 | 19,288 |

Every event identifier is unique, and event indexes are contiguous within each match. Position
source data contains 17 intervals whose `to` value precedes `from`; the loader preserves those
values and does not invent a chronology rule. Event position ID `0` is a measured source category
labelled `Substitute`, so sparse category IDs are treated as opaque rather than assumed positive.
Four player IDs have name variants and one player has
a country-label variant. IDs define identity; labels are preserved where their row grain permits it.

Provider xG occurs in the source shot objects. It is removed recursively before JSON reaches a typed
record, is absent from every typed column, and is prohibited in `events.type_data` by a database
check. It is also absent from staging, manifest payloads, and conflict fingerprints. It is never
persisted.

One raw event coordinate exceeds the nominal 120-by-80 scale by 0.1: Euro 2024, competition `55`,
season `282`, Romania–Ukraine, match `3938638`, event
`78116cc8-afbe-4bae-975b-57ce6983d045` has `location_x = 120.1`. It is exactly one event in the
pinned four-tournament cohort. Migration 0007 accepts the measured raw value without claiming the
nominal pitch scale is 120.1. Values below 0 or above 120.1 remain invalid; y, shot-end and embedded
freeze-frame bounds remain unchanged. Future model features must distinguish raw stored coordinates
from any later normalized or geometry-safe representation.

WP2.2 measured that this event is a **Shot** inside the model cohort — a `Corner` shot type, so the
recorded location is the corner arc where the goal line meets the touchline. Its raw coordinate is
unchanged by modelling: `touchline.features.geometry` applies a bounded source-coordinate tolerance
adjustment for the derived distance and angle only, admissible up to `120.1 + 1e-12` and raising
beyond it. The measured evidence for that adjustment is in
[`reports/wp2.2-geometry-evidence.md`](reports/wp2.2-geometry-evidence.md), and the constants it
relies on are declared in `backend/src/touchline/features/geometry.py`.

## Pitch and goal coordinate system

Source: **StatsBomb Open Data Specification v1.1, Appendix 2 "Locations"** (`doc/` directory of the
pinned Open Data repository), checked **2026-08-03**. Appendix 2 carries the coordinate system as
diagrams rather than prose, so the values are recorded here rather than left implicit in modelling
code.

| Feature | Coordinates | Page |
|---|---|---|
| Pitch | `(0,0)` to `(120,80)`, centre spot `(60,40)` | 35 |
| Penalty spot (attacking) | `(108,40)` | 35 |
| Goalmouth, ground | `(120, 36, 0)` and `(120, 44, 0)` | 36 |
| Goalmouth, crossbar | `(120, 36, 2.67)` and `(120, 44, 2.67)` | 36 |

The body text corroborates the scale independently ("the center of the field is (60,40)"; shot
`end_location` examples `(120, 50)` and `(120, 32.5, 1.2)`).

**The specification states nothing about direction of play.** Whether coordinates are recorded from
the attacking team's perspective is therefore established empirically, not cited: WP2.2 measured 9
shots of 5,606 below the halfway line and a minimum `location_x` of 48.1. No direction transform is
applied.

## Relational / JSONB boundary

Shared event identity, ordering, clock, attribution, possession, flags, play pattern, position,
duration, and location are typed relational columns. Shot details used by the existing API and model
plan are typed in `shots`. Heterogeneous non-shot type-specific objects stay in `events.type_data`
as JSONB after shared fields and provider xG are removed. Shot events must have NULL `type_data`.
This avoids a giant sparse table while keeping stable, cross-event fields queryable and constrained.

Missing optional source values remain NULL. Present malformed structures raise; for example, a
location must be exactly two numeric values. Raw provider coordinates are preserved without
clamping, rounding or direction normalization.

WP1.4 quality reporting treats the future shot cohort's player, period, location, outcome,
body-part, technique and shot-type fields as zero-tolerance: their missingness is a validation error,
not an imputation opportunity. Generic-event and lineup NULLs are reported with their denominators
and rates only; they do not imply a source-completeness or position-chronology rule.

Category checks enforce only bidirectional ID/name consistency observed inside the scoped snapshot
for shot outcome/body part/technique/type and event play pattern/position. They do not claim
completeness against an external provider taxonomy. Event-player to lineup-membership coverage is
joined at `(match_id, team_id, player_id)` and remains an observation; neither a match event nor
lineup membership is converted into appearance or minutes evidence.

## Physical data dictionary

The seven ordered SQL migrations in `backend/src/touchline/ingest/migrations/` own grains,
relationships, keys and constraints, and they are the implementation source of truth for the
physical schema. The table
below maps every persisted data column to its source meaning; generated identity columns and the
migration ledger are implementation metadata.

| Table | Columns and meanings |
|---|---|
| `competitions` | `competition_id` source ID; `competition_name` label; `country_name` optional source region. |
| `seasons` | `season_id` source ID; `season_name` label. |
| `competition_seasons` | `(competition_id, season_id)` selected source pairing. |
| `teams` | `team_id` source ID; `team_name` canonical label encountered in match metadata. |
| `players` | `player_id` source ID; `player_name` canonical collected label. This is now the selected slice's lineup/event player dimension, not only shot takers. |
| `matches` | `match_id`; competition/season FKs; optional `match_date`, `kick_off`, scores and `competition_stage`; required home/away team IDs. |
| `match_teams` | `(match_id, team_id)` participant; `role` is `home` or `away`. |
| `lineups` | `(match_id, team_id)` lineup document grain. |
| `lineup_memberships` | Match/team/player identity plus source `jersey_number`, row-level `player_name`, optional nickname, and optional country ID/name. Membership is not proof of minutes played. |
| `lineup_positions` | Membership FK; 1-based `source_order`; optional position ID/name, periods, interval-valued `from_time`/`to_time`, and start/end reasons. Rows preserve source ordering and anomalous chronology. |
| `lineup_cards` | Membership FK; 1-based `source_order`; card type plus optional reason, period, and interval-valued time. |
| `possessions` | `(match_id, possession_id)` and optional possessing `team_id`, measured consistently within each match-possession. |
| `events` | UUID `event_id`; `match_id`; 1-based `event_index`; optional period/timestamp/minute/second; optional team/player/possession attribution; optional `under_pressure`, `off_camera`, `out`, `counterpress`; optional play-pattern and position ID/name; optional duration and x/y location; event type ID/name; sanitized non-shot `type_data` JSONB. |
| `event_relations` | Match plus directed source and related event UUIDs and 1-based source ordering. Direction is preserved; reciprocity is not assumed. |
| `shots` | One-to-one `event_id`; constant relational discriminator `event_type_name = 'Shot'`; optional outcome, body-part, technique, and shot-type ID/name pairs; optional 2D/3D end location; optional key-pass event FK; optional `aerial_won`, `follows_dribble`, `first_time`, `open_goal`, `one_on_one`, `deflected`, `redirect`, `saved_off_target`, and `saved_to_post` flags. No provider xG. |
| `shot_freeze_frame_players` | Shot event FK; 1-based source order; optional player and position attribution; teammate flag; optional x/y location for an actor embedded in `shot.freeze_frame`. This is not tracking or StatsBomb 360. |

## Reproduction and deployment boundary

With the pinned files cached locally:

```bash
uv run poe ingest --offline --reset
```

The command rebuilds through migrations 0001–0007 and loads all entities. Normal invocations do not
require `--reset`: identical rows are no-ops, changed source facts are rejected, and every run is
recorded. Parsed source rows, exact scoped reconciliation and the successful manifest transition
commit atomically; handled failures record only sanitized terminal evidence after rollback.

The 2026-08-02 clean rebuild and identical rerun are recorded in
[`reports/wp1.6-clean-rebuild.json`](reports/wp1.6-clean-rebuild.json). The clean-build manifest
`a30ac223-d7a0-4386-800a-06d1ef249645`, pinned source commit, exact scope, provenance SHA-256,
migration checksums, counts and quality-report hashes form the Phase 2 input evidence. A future
rebuild may replace the UUID only through an explicit evidence update with equivalent source,
scope, provenance and canonical counts; consumers must not silently select “latest succeeded”.

The repository migration does **not** migrate the live Neon database automatically. Applying code,
applying schema, loading the full source, and verifying live endpoint results are separate release
operations, each run deliberately by an operator.
