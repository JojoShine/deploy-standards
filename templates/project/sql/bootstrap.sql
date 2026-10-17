BEGIN;
SELECT pg_advisory_xact_lock(73626017001);
-- Requires migration first. Existing business values are deliberately preserved.
INSERT INTO starter_settings (key, value) VALUES ('welcome', 'Deployment starter')
ON CONFLICT (key) DO NOTHING;
COMMIT;
