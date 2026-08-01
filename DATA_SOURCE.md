# Data source, coverage, and dictionary

This document owns the source revision, measured WC 2022 coverage, and physical field meanings.
The ordered SQL migrations and loader are the implementation source of truth. WP1.1 and WP1.2 are
complete; WP1.3 has not started.

## Source, rights, and attribution

Data is provided by **StatsBomb** through the
[StatsBomb Open Data repository](https://github.com/statsbomb/open-data).

| Item | Value |
|---|---|
| Pinned revision | [`b0bc9f22dd77c206ddedc1d742893b3bbe64baec`](https://github.com/hudl/open-data/tree/b0bc9f22dd77c206ddedc1d742893b3bbe64baec) |
| Revision date | 2026-05-26 |
| Selected slice | FIFA World Cup 2022, competition `43`, season `106` |
| Local cache | `data/statsbomb/b0bc9f22dd77/`, git-ignored and revision-keyed |
| Provenance | [`data/provenance/competition-43-106.json`](data/provenance/competition-43-106.json) |
| Terms review | 2026-08-01; [evidence note](docs/research/statsbomb-open-data-terms-review-2026-08-01.md) |

The reviewed README requires StatsBomb attribution and logo use for published analysis. Text
attribution is present in the repository, deployed page, and published material. Two release gates
remain unresolved: the Media Pack did not expose a clearly approved downloadable logo, and the
agreement did not clearly resolve whether a public row-level API is permitted analysis or prohibited
redistribution. Do not invent a logo, publish database dumps, or expand public row-level coverage
until StatsBomb/Hudl clarifies those points. This is a source-text review, not legal advice.

The committed fixture files are synthetic, fictional test data. They are not copied match data.

## Measured source inventory

The provenance manifest covers **130 files**: one competitions file, one match file, 64 event files,
and 64 lineup files. No `three-sixty` file is read. The `shot.freeze_frame` arrays described below are
embedded in event files; they are not StatsBomb 360 data and are not continuous tracking.

| Entity / fact | Exact WC 2022 value |
|---|---:|
| Competition / season pairs | 1 |
| Matches / match-team roles | 64 / 128 |
| Teams | 32 |
| Lineups / memberships | 128 / 3,244 |
| Distinct players | 829 |
| Position intervals / cards | 2,958 / 228 |
| Memberships without a position interval | 1,249 |
| Possessions | 11,121 |
| Events / event types | 234,637 / 33 |
| Events with a location | 232,512 |
| Events with player and position attribution | 233,529 |
| Directed related-event references | 330,844 |
| Non-reciprocal directed references | 107,528 |
| Orphan, cross-match, or duplicate references | 0 |
| Shots | 1,494 |
| Shots with embedded freeze-frame arrays / actors | 1,436 / 20,327 |
| Shot end locations: 2D / 3D | 464 / 1,030 |
| Key-pass references | 1,039, all same-match Pass events |
| Non-penalty descriptive cohort | 1,430 shots, 152 goals, 10.63% |

Every event identifier is unique, and event indexes are contiguous within each match. Position
source data contains 17 intervals whose `to` value precedes `from`; the loader preserves those
values and does not invent a chronology rule. Event position ID `0` is a measured source category
labelled `Substitute`, so sparse category IDs are treated as opaque rather than assumed positive.
Four player IDs have name variants and one player has
a country-label variant. IDs define identity; labels are preserved where their row grain permits it.

Provider xG occurs on all 1,494 source shots as `shot.statsbomb_xg`. It is removed recursively before
JSON reaches a typed record, is absent from every typed column, and is prohibited in `events.type_data`
by a database check. It is never persisted.

Only WC 2022 is loaded by this work package. The WC 2018, Euro 2020, WC 2022, and Euro 2024 cohort,
idempotent upserts, conflict policy, and ingestion-run manifest remain WP1.3 work.

## Relational / JSONB boundary

Shared event identity, ordering, clock, attribution, possession, flags, play pattern, position,
duration, and location are typed relational columns. Shot details used by the existing API and model
plan are typed in `shots`. Heterogeneous non-shot type-specific objects stay in `events.type_data`
as JSONB after shared fields and provider xG are removed. Shot events must have NULL `type_data`.
This avoids a giant sparse table while keeping stable, cross-event fields queryable and constrained.

Missing optional source values remain NULL. Present malformed structures raise; for example, a
location must be exactly two numeric values. Raw coordinates remain on StatsBomb's 120 by 80 pitch;
no direction normalization is performed.

## Physical data dictionary

[`docs/SCHEMA.md`](docs/SCHEMA.md) owns grains, relationships, keys, and constraints. The table below
maps every persisted data column to its source meaning; generated identity columns and the migration
ledger are implementation metadata.

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

The command rebuilds through migrations 0001–0005, loads all entities, compares every table count
with the parsed source inside the same transaction, and commits only on an exact match. The loader
remains intentionally non-idempotent; `--reset` is the supported local rerun until WP1.3.

The repository migration does **not** migrate the live Neon database automatically. Applying code,
applying schema, loading the full source, and verifying live endpoint results are separate release
operations. See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).
