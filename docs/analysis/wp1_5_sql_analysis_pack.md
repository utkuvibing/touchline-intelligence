# WP1.5 SQL analysis pack: checked results and query plans

**Run date:** 2026-08-02

**Source revision:** `b0bc9f22dd77c206ddedc1d742893b3bbe64baec`

**Scope:** the accepted four-tournament cohort (World Cup 2018, Euro 2020, World Cup 2022,
Euro 2024)

**Database used for evidence:** PostgreSQL 17.10, local Docker, 230 matches and 843,050 events

The executable pack is in [`backend/sql/wp1_5/`](../../backend/sql/wp1_5/). Each query declares
its output grain, joins, NULL behaviour, and interpretation boundary in the file header. The pack
is a repository-local analysis artifact; it adds no ORM, API route, public row-level output, or
model claim.

## What the ten queries demonstrate

| # | Question | Output grain | Main SQL evidence |
|---:|---|---|---|
| 1 | Competition coverage | competition-season | pre-aggregation, `UNION`, `LEFT JOIN` |
| 2 | Match event counts | match | independent child aggregates avoid join multiplication |
| 3 | Team results | competition-season-team | `UNION ALL`, conditional aggregates, score NULL preservation |
| 4 | Home/away and score checks | loaded cohort | correlated `EXISTS`, paired-NULL check |
| 5 | Descriptive shot prevalence | competition-season | explicit eligibility filters and filtered aggregate |
| 6 | Player recorded shot volume | player | typed shot/event join; no appearance denominator |
| 7 | Event-type distribution | event type | aggregate plus a window denominator |
| 8 | Event missingness | event type | `FILTER` and descriptive NULL coverage |
| 9 | Lineup participation evidence | competition-season | evidence reduced before `LEFT JOIN`; no minutes inference |
| 10 | Event immediately before a shot | preceding event type | `LAG` partitioned by match and possession |

The fixture integration test runs every file inside a PostgreSQL read-only transaction and asserts
the named grain and boundary contracts. Three deliberate mutations prove that tests detect removal
of the penalty exclusion, loss of memberships with no supporting evidence, and reversal of source
event order.

## Checked full-cohort results

Query 1 reconciled to the loaded relational tables:

| Tournament | Matches | Teams | Events | Recorded shots |
|---|---:|---:|---:|---:|
| World Cup 2018 | 64 | 32 | 227,825 | 1,706 |
| Euro 2020 | 51 | 24 | 192,664 | 1,289 |
| World Cup 2022 | 64 | 32 | 234,637 | 1,494 |
| Euro 2024 | 51 | 24 | 187,924 | 1,340 |

Query 4 returned 230 matches and zero missing home roles, missing away roles, incomplete score
pairs, or matches without a score.

Query 5 reproduced the accepted descriptive cohort exactly:

| Tournament | Eligible non-penalty shots | Goals | Conversion |
|---|---:|---:|---:|
| World Cup 2018 | 1,638 | 135 | 8.24% |
| Euro 2020 | 1,234 | 122 | 9.89% |
| World Cup 2022 | 1,430 | 152 | 10.63% |
| Euro 2024 | 1,304 | 98 | 7.52% |
| **Total** | **5,606** | **507** | **9.04%** |

These are observed outcomes, not predictions. The total percentage is calculated here from the
evaluated numerator and denominator only; it is not the M2 training-split baseline.

Query 7 returned 35 event types. The three largest recorded categories were Pass (240,103), Ball
Receipt* (226,924), and Carry (192,243); Shot accounted for 5,829 events. Query 8 showed why
missingness must be interpreted by event type: for example, all 226,924 Ball Receipt* events lack a
recorded duration, while all typed Shot events in this cohort have the inspected generic fields.
The query reports that contrast but does not invent a universal completeness threshold.

Query 9 returned the following source-evidence coverage. These are not appearances or minutes:

| Tournament | Memberships | With position interval | With recorded event | With neither |
|---|---:|---:|---:|---:|
| World Cup 2018 | 2,886 | 1,790 | 1,787 | 1,096 |
| Euro 2020 | 2,345 | 1,576 | 1,572 | 769 |
| World Cup 2022 | 3,244 | 1,995 | 1,996 | 1,246 |
| Euro 2024 | 2,587 | 1,589 | 1,591 | 989 |

Query 10 evaluated all 5,829 Shot events with usable source order and possession identity. The most
common immediately preceding recorded types were Carry (1,890), Ball Receipt* (1,522), Pressure
(828), Ball Recovery (574), and Duel (522); 441 Shots were first in their recorded possession.
This is adjacency in provider order, not causality or an attacking-sequence model.

## `EXPLAIN (ANALYZE, BUFFERS, SETTINGS)` evidence

Plans were measured on the full loaded cohort, not the small test fixture. Timings are local,
cache-sensitive observations; planner shape, row counts, buffer use, spill, and index size carry
more weight than a single elapsed time.

### Query 7: event-type distribution, candidate index before/after

Before a candidate index, PostgreSQL reused the `(event_id, event_type_name)` uniqueness index for a
parallel index-only scan:

```text
Parallel Index Only Scan using events_id_type_unique on events
  rows=281017 loops=3, Heap Fetches=0, shared hit=13967
Finalize GroupAggregate -> WindowAgg -> Sort
Planning Time: 3.915 ms
Execution Time: 105.573 ms
planner total cost: 33907.70
```

Inside a transaction, a candidate `events (event_type_name)` index was created, the same query was
measured, its size was read, and the transaction was rolled back:

```text
Parallel Index Only Scan using wp15_candidate_events_type_idx on events
  rows=281017 loops=3, Heap Fetches=0, shared hit=63 read=718
Finalize GroupAggregate -> WindowAgg -> Sort
Planning Time: 0.716 ms
Execution Time: 67.291 ms
planner total cost: 13383.67
candidate index size: 5776 kB
ROLLBACK
```

The narrow index materially lowers this one aggregation's planner cost and buffer footprint, but it
serves no production path and only one query in a manually run analysis pack. Keeping it would add
about 5.6 MiB plus write, vacuum, and ingestion maintenance for a one-off local speed-up. The
candidate was therefore rejected and no durable secondary index or migration was added.

### Query 10: ordered event sequence

```text
Seq Scan on events: 843050 rows
Sort Key: match_id, possession_id, event_index
Sort Method: external merge, Disk: 25400 kB
WindowAgg: 843050 rows
Subquery filter: 5829 Shot rows, 837221 rows removed
shared hit=5306 read=27536, temp read=3175 written=3188
Planning Time: 2.197 ms
Execution Time: 1143.838 ms
```

The external sort is the dominant work. The query is an explicit full-cohort sequence exercise,
not a serving query or scheduled workload. A three-column ordering index would be substantially
larger and impose ongoing write cost; no recurring latency requirement exists, so no candidate was
promoted. If this sequence becomes a production or repeated modelling input, that changed workload
is the trigger to remeasure an index on `(match_id, possession_id, event_index)`.

## Limitations

- Official match scores are source facts; query 3's points are a conventional summary, not a
  reconstruction of tournament advancement rules.
- Player shot conversion is shown only beside its raw numerator and denominator. It is not adjusted
  for role, opponent, minutes, selection, or shot quality.
- Generic-event NULL rates mix event types with different source shapes and are not data-quality
  failures by themselves.
- Lineup membership, position intervals, and recorded events remain distinct evidence. None is
  silently promoted to an appearance or minutes played.
- The publication questions in `DATA_SOURCE.md` remain unresolved; this work does not expand the
  deployed row-level API.

Data provided by StatsBomb.
