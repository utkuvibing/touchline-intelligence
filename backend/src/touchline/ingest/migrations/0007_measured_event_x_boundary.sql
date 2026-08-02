-- Preserve the raw pinned-source coordinate observed once in the approved four-tournament cohort.
-- This is a measured source-coordinate acceptance boundary, not a claim that the nominal
-- StatsBomb pitch scale is 120.1. All other coordinate constraints remain unchanged.

ALTER TABLE events
    DROP CONSTRAINT events_location_x_bounds,
    ADD CONSTRAINT events_location_x_measured_source_bounds
        CHECK (location_x IS NULL OR location_x BETWEEN 0.0 AND 120.1);
