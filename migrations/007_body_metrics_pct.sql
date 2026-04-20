-- migrations/007_body_metrics_pct.sql
-- Store muscle as percentage (canonical), drop bmi and muscle_mass.
-- Fat mass and muscle mass are derived on display: mass = weight × pct / 100.

ALTER TABLE body_metrics ADD COLUMN IF NOT EXISTS muscle_pct REAL;

-- Best-effort backfill: rows where muscle_mass looks like a percentage (< 70)
-- almost certainly came from the /身體 flow storing pct into the mass column.
-- Real muscle mass for an adult is typically 20–60 kg; percentages are 20–60%.
-- The overlap is narrow, but for this single-user DB we tolerate a few misses.
UPDATE body_metrics
SET muscle_pct = muscle_mass
WHERE muscle_pct IS NULL
  AND muscle_mass IS NOT NULL
  AND muscle_mass < 70;

ALTER TABLE body_metrics DROP COLUMN IF EXISTS muscle_mass;
ALTER TABLE body_metrics DROP COLUMN IF EXISTS bmi;
