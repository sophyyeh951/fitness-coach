-- 對話歷史（讓小健記住之前的對話）
CREATE TABLE chat_history (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    message TEXT NOT NULL
);

-- 只保留最近的對話，建立索引加速查詢
CREATE INDEX idx_chat_history_created_at ON chat_history(created_at DESC);
