-- Durable, source-pinned invocation history for WP1.3's idempotent cohort ingestion.
-- Facts remain in the source-shaped tables; this records how and whether a source scope reached
-- them. `interrupted` is written only by a later invocation that owns the ingestion advisory lock.

CREATE TABLE ingestion_runs (
    run_id uuid PRIMARY KEY,
    owner_token uuid NOT NULL UNIQUE,
    source_commit text NOT NULL CHECK (source_commit ~ '^[0-9a-f]{40}$'),
    status text NOT NULL CHECK (status IN ('running', 'succeeded', 'failed', 'interrupted')),
    scopes jsonb NOT NULL CHECK (jsonb_typeof(scopes) = 'array'),
    started_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    phase_updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at timestamptz,
    owner_host text NOT NULL CHECK (btrim(owner_host) <> ''),
    owner_pid integer NOT NULL CHECK (owner_pid > 0),
    current_phase text NOT NULL CHECK (btrim(current_phase) <> ''),
    error_type text,
    error_message text,
    error_fingerprint text CHECK (error_fingerprint IS NULL OR error_fingerprint ~ '^[0-9a-f]{64}$'),
    attempted_counts jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(attempted_counts) = 'object'),
    entity_counts jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(entity_counts) = 'object'),
    CHECK (
        (status = 'running' AND finished_at IS NULL
            AND error_type IS NULL AND error_message IS NULL)
        OR (status = 'succeeded' AND finished_at IS NOT NULL
            AND error_type IS NULL AND error_message IS NULL)
        OR (status IN ('failed', 'interrupted') AND finished_at IS NOT NULL
            AND error_type IS NOT NULL AND error_message IS NOT NULL)
    ),
    CHECK (phase_updated_at >= started_at),
    CHECK (finished_at IS NULL OR finished_at >= started_at),
    CHECK (
        NOT jsonb_path_exists(attempted_counts, '$.**.statsbomb_xg')
        AND NOT jsonb_path_exists(entity_counts, '$.**.statsbomb_xg')
    )
);

CREATE TABLE ingestion_run_scopes (
    run_id uuid NOT NULL REFERENCES ingestion_runs (run_id),
    competition_id integer NOT NULL,
    season_id integer NOT NULL,
    PRIMARY KEY (run_id, competition_id, season_id),
    CHECK (competition_id > 0),
    CHECK (season_id > 0)
);
