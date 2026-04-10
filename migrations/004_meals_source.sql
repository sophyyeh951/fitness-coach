-- 為 meals 表加入 source 欄位，區分記錄來源
ALTER TABLE meals ADD COLUMN source TEXT DEFAULT 'photo';
-- source 值：'photo'（食物照片）、'nutrition_label'（營養標示）、'text'（對話文字）
