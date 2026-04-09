-- 對話歷史（讓小健記住之前的對話）
CREATE TABLE IF NOT EXISTS chat_history (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_history_created_at ON chat_history(created_at DESC);

-- 用戶基本資料（固定資訊）
CREATE TABLE user_profile (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    gender TEXT,
    birth_year INT,
    height_cm REAL,
    work_style TEXT,
    dietary_restrictions TEXT[],
    exercise_habits JSONB,
    medical_notes TEXT,
    preferences JSONB DEFAULT '{}',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 預填用戶資料
INSERT INTO user_profile (gender, birth_year, height_cm, work_style, dietary_restrictions, exercise_habits, medical_notes, preferences)
VALUES (
    'female',
    1992,
    164,
    '遠端居家辦公，久坐',
    ARRAY['無麩質'],
    '{
      "weekly_frequency": "幾乎每天",
      "schedule": [
        {"activity": "羽球", "frequency": "2-3次/週", "duration": "2-3小時"},
        {"activity": "重訓", "frequency": "其餘天數", "duration": "1小時"}
      ],
      "planned": [
        {"activity": "游泳", "start": "2026-06", "note": "預計6-7月開始學"}
      ],
      "equipment": "啞鈴(2-10kg)、壺鈴(20kg)、槓鈴(可到36kg+)、bench、翹臀圈、拉力帶"
    }'::jsonb,
    NULL,
    '{"proactive_reminders": false}'::jsonb
);

-- 短期情境筆記（自動從對話萃取）
CREATE TABLE user_context (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    expires_at DATE,
    is_active BOOLEAN NOT NULL DEFAULT true,
    source_message TEXT
);
CREATE INDEX idx_user_context_active ON user_context(is_active, expires_at);

-- 設定用戶目標：半年內體脂從 25% 降到 20%，同時增肌
INSERT INTO user_goals (goal_type, target_weight, target_body_fat, daily_calorie_target, daily_protein_target)
VALUES ('cut', NULL, 20.0, 1600, 110);
