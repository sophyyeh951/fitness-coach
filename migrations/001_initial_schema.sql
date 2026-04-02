-- Run this in Supabase SQL Editor to create all tables

-- 飲食記錄
CREATE TABLE meals (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    photo_url TEXT,
    food_items JSONB NOT NULL DEFAULT '[]',
    total_calories REAL NOT NULL DEFAULT 0,
    protein REAL NOT NULL DEFAULT 0,
    carbs REAL NOT NULL DEFAULT 0,
    fat REAL NOT NULL DEFAULT 0,
    ai_response TEXT
);

-- 訓練記錄
CREATE TABLE workouts (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    workout_type TEXT NOT NULL,
    exercises JSONB NOT NULL DEFAULT '[]',
    duration_min INT,
    estimated_calories REAL,
    notes TEXT
);

-- 身體數據（Apple Health + PICOOC）
CREATE TABLE body_metrics (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    date DATE NOT NULL UNIQUE,
    weight REAL,
    body_fat_pct REAL,
    muscle_mass REAL,
    bmi REAL,
    steps INT,
    active_calories REAL,
    resting_heart_rate INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 每日彙總
CREATE TABLE daily_summary (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    date DATE NOT NULL UNIQUE,
    total_calories_in REAL,
    total_protein REAL,
    total_carbs REAL,
    total_fat REAL,
    total_calories_out REAL,
    steps INT,
    workout_summary TEXT,
    ai_advice TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 目標設定
CREATE TABLE user_goals (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    goal_type TEXT NOT NULL CHECK (goal_type IN ('cut', 'bulk', 'maintain')),
    target_weight REAL,
    target_body_fat REAL,
    daily_calorie_target REAL,
    daily_protein_target REAL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
