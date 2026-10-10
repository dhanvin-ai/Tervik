-- Intent and policy classification. SQLite applies these via create_all;
-- run this file on PostgreSQL deploys.

CREATE TABLE IF NOT EXISTS policies (
    id VARCHAR(36) PRIMARY KEY,
    project_id VARCHAR(36) NOT NULL REFERENCES projects(id),
    title VARCHAR(160) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    severity VARCHAR(20) NOT NULL DEFAULT 'high',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    version INTEGER NOT NULL DEFAULT 1,
    created_by VARCHAR(36),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_policies_project_id ON policies (project_id);

CREATE TABLE IF NOT EXISTS classifications (
    id VARCHAR(36) PRIMARY KEY,
    project_id VARCHAR(36) NOT NULL REFERENCES projects(id),
    conversation_id VARCHAR(36) NOT NULL,
    kind VARCHAR(20) NOT NULL,
    target_id VARCHAR(36),
    label VARCHAR(200) NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    evidence JSONB NOT NULL DEFAULT '[]',
    confidence DOUBLE PRECISION,
    classifier VARCHAR(20) NOT NULL DEFAULT 'llm',
    model VARCHAR(120),
    occurred_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_classifications_project_id ON classifications (project_id);
CREATE INDEX IF NOT EXISTS ix_classifications_conversation_id ON classifications (conversation_id);
CREATE INDEX IF NOT EXISTS ix_classifications_kind ON classifications (kind);
CREATE INDEX IF NOT EXISTS ix_classifications_target_id ON classifications (target_id);
CREATE INDEX IF NOT EXISTS ix_classifications_occurred_at ON classifications (occurred_at);

CREATE TABLE IF NOT EXISTS analyzed_conversations (
    project_id VARCHAR(36) NOT NULL REFERENCES projects(id),
    conversation_id VARCHAR(36) NOT NULL,
    last_event_at TIMESTAMPTZ NOT NULL,
    event_count INTEGER NOT NULL DEFAULT 0,
    config_hash VARCHAR(64) NOT NULL DEFAULT '',
    status VARCHAR(20) NOT NULL DEFAULT 'done',
    classifier VARCHAR(20) NOT NULL DEFAULT 'llm',
    error_code VARCHAR(80),
    analyzed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, conversation_id)
);
CREATE INDEX IF NOT EXISTS ix_analyzed_conversations_last_event_at ON analyzed_conversations (last_event_at);
