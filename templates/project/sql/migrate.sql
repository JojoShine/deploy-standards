BEGIN;
-- The same lock serializes both operations, including concurrent first use.
SELECT pg_advisory_xact_lock(73626017001);
CREATE TABLE IF NOT EXISTS app_schema_migrations (
    version integer PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS starter_settings (
    key text PRIMARY KEY,
    value text NOT NULL
);
INSERT INTO app_schema_migrations (version) VALUES (1) ON CONFLICT (version) DO NOTHING;
COMMIT;
