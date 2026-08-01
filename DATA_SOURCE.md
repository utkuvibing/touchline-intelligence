# Data source, coverage, and dictionary

This document owns the data-source contract for Touchline Intelligence: which source revision is
used, what is actually loaded, what each current database field means, and which publication
conditions remain unresolved. Counts describe the current M0 database unless explicitly labelled as
future M1 scope.

**WP1.1 status:** source review, coverage inventory, and the current-schema dictionary are recorded.
The work package is not closed: an approved current logo asset and clarification of public row-level
data use remain release gates.

## Source and version

Data is provided by **StatsBomb** through the
[StatsBomb Open Data repository](https://github.com/statsbomb/open-data). That URL currently
redirects to `hudl/open-data`; the source README still requires attribution to StatsBomb.

| Item | Current value |
|---|---|
| Source revision | [`b0bc9f22dd77c206ddedc1d742893b3bbe64baec`](https://github.com/hudl/open-data/tree/b0bc9f22dd77c206ddedc1d742893b3bbe64baec) |
| Source revision date | 2026-05-26 |
| Selected competition-season | FIFA World Cup 2022, StatsBomb IDs `43` / `106` |
| Local cache | `data/statsbomb/b0bc9f22dd77/` — git-ignored and keyed by source revision |
| Committed provenance | [`data/provenance/competition-43-106.json`](data/provenance/competition-43-106.json) |
| Terms review | 2026-08-01 — [`docs/research/statsbomb-open-data-terms-review-2026-08-01.md`](docs/research/statsbomb-open-data-terms-review-2026-08-01.md) |

The provenance record contains the source revision and a SHA-256 for every source file read. The
download cache is not a publication artifact and is not committed. The committed files under
`data/fixtures/statsbomb/` are small synthetic test fixtures with fictional entities and deliberate
edge cases, not copied match data.

## Rights and attribution review

The following first-party sources were reviewed on 2026-08-01 at the pinned revision:

- the [Open Data README](https://github.com/hudl/open-data/blob/b0bc9f22dd77c206ddedc1d742893b3bbe64baec/README.md);
- the [StatsBomb Public Data User Agreement](https://github.com/hudl/open-data/blob/b0bc9f22dd77c206ddedc1d742893b3bbe64baec/LICENSE.pdf), internally dated 8 September 2023;
- the README's [Media Pack link](https://statsbomb.com/media-pack/).

The README permits public use for research projects and genuine interest in football analytics and
requires published/shared/distributed research, analysis, or insights to name StatsBomb as the data
source and use the StatsBomb logo. The agreement permits analysis and research and says analysis or
conclusions may be shared publicly, but prohibits providing, reproducing, or distributing the data
to third parties and prohibits commercial exploitation of the data or derived analysis. This is a
record of the source text, not legal advice.

Current attribution placement:

- the root README and this document name StatsBomb as the source;
- the deployed page renders “Data provided by StatsBomb,” protected by a frontend test and a
  deliberate mutation check;
- the M0 technical article carries the same source statement.

Two publication questions remain open:

1. **Logo:** the official Media Pack URL redirected to a Hudl StatsBomb product page on the review
   date and did not expose a clearly approved downloadable asset. Text attribution remains in place,
   but it is not represented as satisfying the separate logo requirement. Do not invent, trace, or
   extract a logo; obtain a current approved asset or written direction before the next release.
2. **Row-level public data:** the current `/shots` endpoint exposes selected recorded event fields.
   The reviewed agreement does not define whether that public API use falls within permitted public
   analysis or prohibited provision/reproduction of data. Do not expand public row-level coverage or
   publish database dumps/derived datasets until StatsBomb/Hudl clarifies the use.

The detailed evidence and exact clause references are in the dated terms-review note linked above.

## Current coverage inventory

### Source files read

The current provenance manifest covers exactly **66** files:

- `competitions.json`;
- `matches/43/106.json`;
- 64 files under `events/<match_id>.json`, one for every selected match.

The loader does **not** fetch or store lineup files or `three-sixty` files. It reads event files but
keeps Shot events only. StatsBomb event data, selected StatsBomb 360 freeze frames, and continuous
tracking are distinct products; this project has no tracking data.

### Loaded population

| Fact | Exact current value |
|---|---:|
| Competition-seasons | 1 |
| Matches | 64 |
| Match dates | 2022-11-20 to 2022-12-18 |
| Teams | 32 |
| Players represented | 431 shot takers — not a squad list |
| Stored Shot events | 1,494 |
| Non-penalty descriptive cohort | 1,430 shots |
| Goals in that cohort | 152 |
| Descriptive conversion | 10.63% |

Competition stages: 48 group-stage matches, 8 round-of-16 matches, 4 quarter-finals, 2
semi-finals, 1 third-place final, and 1 final.

Shot types: 1,382 Open Play, 64 Penalty, 46 Free Kick, and 2 Corner. Period 5 contains 41 shootout
kicks; each is typed Penalty in this snapshot. The descriptive cohort requires known `shot_type`,
`period`, and `outcome`, then excludes `shot_type = 'Penalty'` and period 5.

Current shot-field coverage is complete for player, period, minute, second, location, outcome, body
part, technique, and shot type: zero of 1,494 rows are missing any of them. The parser still preserves
optional absence as NULL because completeness in this tournament is not a source guarantee.
Recorded locations span `x = 59.0–120.0` and `y = 0.7–79.2` on StatsBomb's 120 × 80 pitch.

### M1 target is not current coverage

M1 will expand the core cohort to WC 2018, Euro 2020, WC 2022, and Euro 2024, approximately 230
matches. Only WC 2022 is loaded today. Counts for the other tournaments in PLAN/ADR 0004 remain
estimates until WP1.3 loads and WP1.4 reconciles them; they must not be presented as measured facts.

## Current physical data dictionary

The source of truth is the provisional DDL in
[`backend/src/touchline/ingest/schema.sql`](backend/src/touchline/ingest/schema.sql), the parser in
[`parse.py`](backend/src/touchline/ingest/parse.py), and the write mapping in
[`load.py`](backend/src/touchline/ingest/load.py). This dictionary describes M0, not the schema that
WP1.2 will design. The current schema has primary keys but no foreign keys, check constraints,
migrations, or justified secondary indexes.

### `competitions`

Grain: one StatsBomb competition-season, identified by the pair `(competition_id, season_id)`.

| Column | PostgreSQL type / nullability | StatsBomb source | Meaning |
|---|---|---|---|
| `competition_id` | `integer NOT NULL`, composite PK | `competition_id` | Source competition identifier. |
| `season_id` | `integer NOT NULL`, composite PK | `season_id` | Source season identifier within the competition. |
| `competition_name` | `text NOT NULL` | `competition_name` | Published competition name. |
| `season_name` | `text NOT NULL` | `season_name` | Published season label. |
| `country_name` | `text NULL` | `country_name` | Source country/region name when present. |

### `teams`

Grain: one team identity encountered as a home or away team in the selected matches.

| Column | PostgreSQL type / nullability | StatsBomb source | Meaning |
|---|---|---|---|
| `team_id` | `integer`, PK | `home_team.home_team_id` or `away_team.away_team_id` | Source team identifier. |
| `team_name` | `text NOT NULL` | `home_team.home_team_name` or `away_team.away_team_name` | Source team name; deduplicated by ID. |

### `players`

Grain: one player who took at least one stored shot. This is explicitly **not** a squad, lineup, or
appearance table and cannot supply player exposure denominators.

| Column | PostgreSQL type / nullability | StatsBomb source | Meaning |
|---|---|---|---|
| `player_id` | `integer`, PK | Shot event `player.id` | Source player identifier. |
| `player_name` | `text NOT NULL` | Shot event `player.name` | Source player name; deduplicated by ID. |

### `matches`

Grain: one StatsBomb match in the selected competition-season.

| Column | PostgreSQL type / nullability | StatsBomb source | Meaning |
|---|---|---|---|
| `match_id` | `integer`, PK | `match_id` | Source match identifier and event filename key. |
| `competition_id` | `integer NOT NULL` | `competition.competition_id` | Source competition identifier. |
| `season_id` | `integer NOT NULL` | `season.season_id` | Source season identifier. |
| `match_date` | `date NULL` | `match_date` | ISO date parsed to a database date. |
| `kick_off` | `text NULL` | `kick_off` | Source kick-off value, currently retained as text. |
| `home_team_id` | `integer NOT NULL` | `home_team.home_team_id` | Source home-team identifier. |
| `away_team_id` | `integer NOT NULL` | `away_team.away_team_id` | Source away-team identifier. |
| `home_score` | `integer NULL` | `home_score` | Recorded final home score when present. |
| `away_score` | `integer NULL` | `away_score` | Recorded final away score when present. |
| `competition_stage` | `text NULL` | `competition_stage.name` | Tournament stage when present. |

### `shots`

Grain: one source event whose `type.name` is `Shot`. `shot_id` is the StatsBomb event UUID.

| Column | PostgreSQL type / nullability | StatsBomb source | Meaning |
|---|---|---|---|
| `shot_id` | `text`, PK | Event `id` | Source event UUID, preserved verbatim. |
| `match_id` | `integer NOT NULL` | Enclosing event filename | Match containing the event. |
| `team_id` | `integer NOT NULL` | Event `team.id` | Team credited with the shot. |
| `player_id` | `integer NULL` | Optional event `player.id` | Player credited with the shot; absence remains NULL. |
| `period` | `integer NULL` | Event `period` | Source match period; period 5 is a shootout in this snapshot. |
| `minute` | `integer NULL` | Event `minute` | Source event minute. |
| `second` | `integer NULL` | Event `second` | Source event second. |
| `location_x` | `double precision NULL` | Event `location[0]` | Raw StatsBomb x coordinate; absence remains NULL. |
| `location_y` | `double precision NULL` | Event `location[1]` | Raw StatsBomb y coordinate; absence remains NULL. |
| `outcome` | `text NULL` | `shot.outcome.name` | Recorded shot outcome. |
| `body_part` | `text NULL` | `shot.body_part.name` | Recorded body part. |
| `technique` | `text NULL` | `shot.technique.name` | Recorded technique when present. |
| `shot_type` | `text NULL` | `shot.type.name` | Recorded shot type, such as Open Play or Penalty. |

Missing optional values become NULL. A present `location` that is not exactly two numeric values is
malformed and raises instead of being coerced. Required structural fields such as event ID, team, and
the shot object also raise when absent or malformed.

## Deliberate exclusions

M0 does not store non-shot events, lineups, possessions, related events, play pattern, position,
shot end location, shot freeze frames, or provider xG. Provider `shot.statsbomb_xg` is deliberately
excluded from the typed record, schema, loader, and API; a parser test protects that leakage control.

No coordinate normalization or attacking-direction transformation occurs in the raw store. Those are
future feature-engineering decisions and must not be retrofitted into source fields.

## Reproduction checks

With the pinned files already in the local cache:

```bash
uv run poe ingest --offline --reset
```

The load must reconcile source and database counts before commit. The committed provenance hashes
allow another machine to verify that it received the same bytes. `--reset` is destructive and is the
supported M0 rerun path; idempotent ingestion and a run manifest arrive in WP1.3.

Re-review the official README, agreement, and Media Pack before expanding ingestion scope and before
every public release. A changed source revision invalidates measured counts and requires regenerated
provenance and documentation in the same change.
