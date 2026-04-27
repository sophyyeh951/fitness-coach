-- Add muscle_group tag to workouts so we can show "last 臀腿 day" as reference
-- when user starts a new strength session, and break weekly report down by part.
--
-- Values used by the app: '胸肩', '背', '臀腿', '其他'. NULL for cardio / legacy rows.

ALTER TABLE workouts ADD COLUMN IF NOT EXISTS muscle_group TEXT;

CREATE INDEX IF NOT EXISTS workouts_muscle_group_idx
    ON workouts (muscle_group, created_at DESC);
