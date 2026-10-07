-- Phase 2 additive migration. Safe to run on a Phase 1 database.
-- SQLite applies these via create_all; run this file on PostgreSQL deploys.

ALTER TABLE projects ADD COLUMN IF NOT EXISTS org_id VARCHAR(36) REFERENCES organizations(id);
ALTER TABLE projects ADD COLUMN IF NOT EXISTS settings JSONB DEFAULT '{}';

CREATE TABLE IF NOT EXISTS organizations (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS accounts (
    id VARCHAR(36) PRIMARY KEY,
    email VARCHAR(320) NOT NULL UNIQUE,
    password_hash VARCHAR(256) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS memberships (
    org_id VARCHAR(36) NOT NULL REFERENCES organizations(id),
    account_id VARCHAR(36) NOT NULL REFERENCES accounts(id),
    role VARCHAR(20) NOT NULL DEFAULT 'member',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, account_id)
);

CREATE TABLE IF NOT EXISTS sessions (
    id VARCHAR(36) PRIMARY KEY,
    account_id VARCHAR(36) NOT NULL REFERENCES accounts(id),
    org_id VARCHAR(36) REFERENCES organizations(id),
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_sessions_token ON sessions (token_hash);

CREATE TABLE IF NOT EXISTS environments (
    id VARCHAR(36) PRIMARY KEY,
    project_id VARCHAR(36) NOT NULL REFERENCES projects(id),
    name VARCHAR(80) NOT NULL DEFAULT 'production',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, name)
);

CREATE TABLE IF NOT EXISTS credentials (
    id VARCHAR(36) PRIMARY KEY,
    project_id VARCHAR(36) NOT NULL REFERENCES projects(id),
    environment_id VARCHAR(36) REFERENCES environments(id),
    name VARCHAR(120) NOT NULL DEFAULT 'default',
    prefix VARCHAR(16) NOT NULL,
    key_hash VARCHAR(64) NOT NULL UNIQUE,
    scope VARCHAR(20) NOT NULL DEFAULT 'ingest',
    created_by VARCHAR(36),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ
);

ALTER TABLE events ADD COLUMN IF NOT EXISTS org_id VARCHAR(36);
ALTER TABLE events ADD COLUMN IF NOT EXISTS environment VARCHAR(80) DEFAULT 'production';
ALTER TABLE events ADD COLUMN IF NOT EXISTS schema_version INTEGER DEFAULT 2;
ALTER TABLE events ADD COLUMN IF NOT EXISTS ingested_at TIMESTAMPTZ DEFAULT now();

CREATE TABLE IF NOT EXISTS ingestion_jobs (
    project_id VARCHAR(36) NOT NULL,
    event_id VARCHAR(200) NOT NULL,
    state VARCHAR(20) NOT NULL DEFAULT 'pending',
    retry_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at TIMESTAMPTZ,
    error_code VARCHAR(80),
    environment VARCHAR(80) NOT NULL DEFAULT 'production',
    payload JSONB NOT NULL DEFAULT '{}',
    mirror_state VARCHAR(20) NOT NULL DEFAULT 'pending',
    mirror_attempts INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, event_id)
);
CREATE INDEX IF NOT EXISTS ix_jobs_state ON ingestion_jobs (state);

CREATE TABLE IF NOT EXISTS usage_records (
    project_id VARCHAR(36) NOT NULL,
    event_id VARCHAR(200) NOT NULL,
    bytes INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, event_id)
);

CREATE TABLE IF NOT EXISTS payload_objects (
    key VARCHAR(320) PRIMARY KEY,
    project_id VARCHAR(36) NOT NULL,
    digest VARCHAR(64) NOT NULL,
    size INTEGER NOT NULL DEFAULT 0,
    content_type VARCHAR(120) NOT NULL DEFAULT 'application/json',
    retention_deadline TIMESTAMPTZ,
    content TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_records (
    id VARCHAR(36) PRIMARY KEY,
    org_id VARCHAR(36) NOT NULL REFERENCES organizations(id),
    account_id VARCHAR(36),
    action VARCHAR(80) NOT NULL,
    resource VARCHAR(200) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Phase 5: customer-defined behavior rules.
CREATE TABLE IF NOT EXISTS behavior_rules (
    id VARCHAR(36) PRIMARY KEY,
    project_id VARCHAR(36) NOT NULL REFERENCES projects(id),
    name VARCHAR(120) NOT NULL,
    kind VARCHAR(30) NOT NULL,
    pattern VARCHAR(500),
    tool VARCHAR(200),
    severity VARCHAR(20) NOT NULL DEFAULT 'high',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    version VARCHAR(20) NOT NULL DEFAULT '1',
    created_by VARCHAR(36),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Phase 6: configured intents and discovered topics.
CREATE TABLE IF NOT EXISTS intents (
    id VARCHAR(36) PRIMARY KEY,
    project_id VARCHAR(36) NOT NULL REFERENCES projects(id),
    name VARCHAR(120) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    examples JSONB NOT NULL DEFAULT '[]',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    version VARCHAR(20) NOT NULL DEFAULT '1',
    created_by VARCHAR(36),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS semantic_clusters (
    id VARCHAR(36) PRIMARY KEY,
    project_id VARCHAR(36) NOT NULL REFERENCES projects(id),
    key VARCHAR(64) NOT NULL,
    label VARCHAR(200) NOT NULL DEFAULT '',
    label_override VARCHAR(200),
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    merged_into VARCHAR(36),
    member_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, key)
);

CREATE TABLE IF NOT EXISTS semantic_memberships (
    cluster_id VARCHAR(36) NOT NULL REFERENCES semantic_clusters(id),
    conversation_id VARCHAR(36) NOT NULL,
    score DOUBLE PRECISION NOT NULL DEFAULT 0,
    PRIMARY KEY (cluster_id, conversation_id)
);
