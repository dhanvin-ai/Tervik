-- Read API keys, alert metrics, and plan retention. SQLite gets new columns
-- automatically on startup; run this file on PostgreSQL deploys.

CREATE TABLE IF NOT EXISTS api_keys (
    id VARCHAR(36) PRIMARY KEY,
    project_id VARCHAR(36) NOT NULL REFERENCES projects(id),
    name VARCHAR(120) NOT NULL DEFAULT 'default',
    prefix VARCHAR(20) NOT NULL,
    key_hash VARCHAR(64) NOT NULL UNIQUE,
    created_by VARCHAR(36),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_api_keys_project_id ON api_keys (project_id);

ALTER TABLE alert_rules ADD COLUMN IF NOT EXISTS metric VARCHAR(30);
ALTER TABLE alert_rules ADD COLUMN IF NOT EXISTS target VARCHAR(200);
ALTER TABLE plans ADD COLUMN IF NOT EXISTS retention_days INTEGER;
