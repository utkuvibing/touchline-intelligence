# WP1.5 SQL analysis pack

These ten PostgreSQL queries are repository-local research artifacts over the fixed four-tournament
cohort. They are hand-written SQL: no ORM or API endpoint executes them. Run all queries from
PowerShell against the local Docker database with:

```powershell
$queries = Get-ChildItem backend/sql/wp1_5 -Filter '*.sql' |
  Where-Object Name -Match '^\d{2}_' | Sort-Object Name
$queries | Get-Content | docker exec -i touchline-postgres psql -X -v ON_ERROR_STOP=1 -U touchline -d touchline -P pager=off
```

Each query states its question, output grain, join strategy, and NULL interpretation in its header.
The checked full-cohort results and query-plan evidence live in
each query file's own header, which records its grain, join strategy, NULL behaviour and
interpretation boundary.

Important boundaries:

- The shot conversion figures are descriptive prevalence, not model evaluation or expected goals.
- Lineup membership and position intervals are source coverage, not appearances or minutes played.
- Event adjacency is source order inside a provider-defined possession, not a causal football claim.
- This pack does not expose new public row-level data. The publication gates in `DATA_SOURCE.md`
  remain open.

Data provided by StatsBomb.
