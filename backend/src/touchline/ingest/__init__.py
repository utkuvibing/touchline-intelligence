"""StatsBomb Open Data ingestion.

Current internal scope: the fixed four-tournament cohort with normalized lineup, event and shot
facts. The schema is versioned under ``migrations`` and production ingestion is idempotent,
source-pinned and auditable. Public row-level queries remain restricted to World Cup 2022.
"""
