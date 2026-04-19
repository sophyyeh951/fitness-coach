-- migrations/006_user_sessions.sql
CREATE TABLE IF NOT EXISTS user_sessions (
    user_id TEXT PRIMARY KEY,
    mode    TEXT NOT NULL,
    draft   JSONB NOT NULL DEFAULT '{}',
    expires_at TIMESTAMPTZ NOT NULL
);

-- Automatically clean up expired sessions
CREATE INDEX IF NOT EXISTS idx_user_sessions_expires ON user_sessions(expires_at);
