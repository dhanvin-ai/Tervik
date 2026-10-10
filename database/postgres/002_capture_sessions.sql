-- Session/event capture API: conversation sessions and end-user profiles.
-- SQLite applies these via create_all; run this file on PostgreSQL deploys.

CREATE TABLE IF NOT EXISTS conversation_sessions (
    project_id VARCHAR(36) NOT NULL REFERENCES projects(id),
    id VARCHAR(200) NOT NULL,
    conversation_id VARCHAR(36) NOT NULL,
    user_id VARCHAR(200),
    user_data JSONB NOT NULL DEFAULT '{}',
    session_metadata JSONB NOT NULL DEFAULT '{}',
    client_config VARCHAR(200),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, id)
);
CREATE INDEX IF NOT EXISTS ix_conversation_sessions_conversation_id ON conversation_sessions (conversation_id);
CREATE INDEX IF NOT EXISTS ix_conversation_sessions_user_id ON conversation_sessions (user_id);
CREATE INDEX IF NOT EXISTS ix_conversation_sessions_started_at ON conversation_sessions (started_at);

CREATE TABLE IF NOT EXISTS end_users (
    project_id VARCHAR(36) NOT NULL REFERENCES projects(id),
    user_id VARCHAR(200) NOT NULL,
    traits JSONB NOT NULL DEFAULT '{}',
    first_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, user_id)
);
