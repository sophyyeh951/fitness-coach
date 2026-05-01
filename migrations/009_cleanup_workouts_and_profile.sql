-- migrations/009_cleanup_workouts_and_profile.sql
--
-- One-time cleanup before the 8-week PPL program starts (2026-05-04):
-- 1. Backfill workouts.muscle_group from workout_type / exercises content
-- 2. Normalize inconsistent workout_type labels ('休息日' → '休息')
-- 3. Update user_profile equipment to current reality (no barbell, dumbbells max 20kg/side)
--
-- NOT included: row deduplication. A handful of rows look duplicated
-- (e.g. 2026-02-02 chest press appears twice). Will verify with user
-- before deleting.

-- ---- 1. Normalize workout_type ----
UPDATE workouts SET workout_type = '休息' WHERE workout_type = '休息日';

-- ---- 2. Backfill muscle_group ----
-- Direct mapping from workout_type
UPDATE workouts SET muscle_group = '臀腿'
  WHERE muscle_group IS NULL AND workout_type IN ('臀腿', '腿');

UPDATE workouts SET muscle_group = '胸肩'
  WHERE muscle_group IS NULL AND workout_type IN ('胸肩', '胸', '肩');

UPDATE workouts SET muscle_group = '背'
  WHERE muscle_group IS NULL AND workout_type IN ('背', '拉');

-- '上半身' / '全身' / '重訓': inspect exercises array to decide
-- - has 划船/硬舉 → 背
-- - has 胸推/肩推/飛鳥/上胸 → 胸肩
-- - has 深蹲/分腿/臀推/RDL → 臀腿
-- - else → 其他
UPDATE workouts SET muscle_group = '背'
  WHERE muscle_group IS NULL
    AND workout_type IN ('上半身', '全身', '重訓')
    AND exercises::text ~ '划船|硬舉';

UPDATE workouts SET muscle_group = '胸肩'
  WHERE muscle_group IS NULL
    AND workout_type IN ('上半身', '全身', '重訓')
    AND exercises::text ~ '胸推|肩推|飛鳥|上胸|側平舉';

UPDATE workouts SET muscle_group = '臀腿'
  WHERE muscle_group IS NULL
    AND workout_type IN ('上半身', '全身', '重訓')
    AND exercises::text ~ '深蹲|分腿|臀推|RDL|登階|提踵';

UPDATE workouts SET muscle_group = '其他'
  WHERE muscle_group IS NULL
    AND workout_type IN ('上半身', '全身', '重訓', '其他');

-- Cardio / rest stays NULL (correct behavior)

-- ---- 3. Update equipment in user_profile ----
UPDATE user_profile
SET exercise_habits = jsonb_set(
        exercise_habits,
        '{equipment}',
        '"可調式啞鈴 2-20kg/支、20kg 壺鈴、bench、翹臀圈、拉力帶（無槓鈴、無彈力帶、無單槓）"'::jsonb
    ),
    updated_at = now()
WHERE id = (SELECT id FROM user_profile ORDER BY id LIMIT 1);
