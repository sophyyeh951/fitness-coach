-- 飲食分餐別
ALTER TABLE meals ADD COLUMN meal_type TEXT DEFAULT 'other';
-- meal_type 值：'breakfast'（早餐）、'lunch'（午餐）、'dinner'（晚餐）、'snack'（點心）、'other'

-- workouts 表已有 notes 欄位，不需要改動
