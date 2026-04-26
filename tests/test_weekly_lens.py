"""Unit tests for weekly_lens directive selection."""
from __future__ import annotations
from collections import Counter

import pytest

from app.reports import weekly_lens


def _wk(
    *,
    actual_strength: int = 0,
    planned_strength: int = 4,
    non_rest_count: int = 0,
    workout_breakdown: Counter | None = None,
    days_with_meals: int = 0,
    avg_kcal: float = 0.0,
    avg_deficit: float = 0.0,
    days_protein_met: int = 0,
    metrics: list[dict] | None = None,
    max_weight_per_exercise: dict | None = None,
) -> dict:
    return {
        "meals": [],
        "workouts": [],
        "metrics": metrics or [],
        "actual_strength": actual_strength,
        "planned_strength": planned_strength,
        "non_rest_count": non_rest_count,
        "workout_breakdown": workout_breakdown or Counter(),
        "days_with_meals": days_with_meals,
        "avg_kcal": avg_kcal,
        "avg_deficit": avg_deficit,
        "days_protein_met": days_protein_met,
        "max_weight_per_exercise": max_weight_per_exercise or {},
    }


def test_workout_lens_flags_missed_strength():
    this_week = _wk(actual_strength=0, planned_strength=4, non_rest_count=3)
    last_week = _wk(actual_strength=1, planned_strength=4, non_rest_count=3)
    out = weekly_lens.pick_workout_lens(this_week, last_week)
    assert "0/4" in out
    assert "少 4 次" in out
    assert "上週 1" in out
    assert "→" in out  # AI directive marker


def test_workout_lens_celebrates_meeting_target():
    this_week = _wk(actual_strength=4, planned_strength=4, non_rest_count=4)
    last_week = _wk(actual_strength=3, planned_strength=4, non_rest_count=3)
    out = weekly_lens.pick_workout_lens(this_week, last_week)
    assert "4/4" in out and "達標" in out
    assert "進階方向" in out


def test_workout_lens_empty_when_no_strength_planned():
    this_week = _wk(planned_strength=0, actual_strength=0)
    last_week = _wk(planned_strength=0, actual_strength=0)
    assert weekly_lens.pick_workout_lens(this_week, last_week) == ""


def test_diet_lens_includes_both_angles_for_ai_to_choose():
    this_week = _wk(days_with_meals=7, avg_kcal=1381, days_protein_met=7)
    last_week = _wk(days_with_meals=7, avg_kcal=1500, days_protein_met=4)
    out = weekly_lens.pick_diet_lens(this_week, last_week)
    assert "1381" in out
    assert "蛋白質達標 7/7" in out
    assert "上週 1500" in out
    assert "改進空間較大" in out  # AI told to pick the angle with more headroom
    assert "100% 達標" in out  # protein-perfect note triggered, AI told to skip it


def test_diet_lens_empty_when_no_meals_logged():
    this_week = _wk(days_with_meals=0)
    last_week = _wk(days_with_meals=0)
    assert weekly_lens.pick_diet_lens(this_week, last_week) == ""


def test_body_lens_flags_single_bf_reading():
    metrics = [
        {"date": "2026-04-20", "weight": 53.0, "body_fat_pct": 25.5, "muscle_pct": 42.0},
        {"date": "2026-04-26", "weight": 53.7, "body_fat_pct": None, "muscle_pct": None},
    ]
    this_week = _wk(metrics=metrics)
    last_week = _wk(metrics=[])
    out = weekly_lens.pick_body_lens(this_week, last_week)
    assert "+0.7kg" in out  # weight delta shows
    assert "1 次讀數" in out  # bf flagged as insufficient
    assert "PICOOC" in out  # advises more measurements


def test_body_lens_marks_noise_range():
    metrics = [
        {"date": "2026-04-20", "weight": 53.0, "body_fat_pct": 25.5},
        {"date": "2026-04-26", "weight": 53.2, "body_fat_pct": 25.7},
    ]
    this_week = _wk(metrics=metrics)
    last_week = _wk(metrics=[])
    out = weekly_lens.pick_body_lens(this_week, last_week)
    assert "波動範圍內" in out


def test_body_lens_empty_when_no_metrics():
    this_week = _wk(metrics=[])
    last_week = _wk(metrics=[])
    assert weekly_lens.pick_body_lens(this_week, last_week) == ""


def test_workout_lens_includes_weight_progression_when_overlap_exists():
    this_week = _wk(
        actual_strength=4, planned_strength=4, non_rest_count=4,
        max_weight_per_exercise={"硬舉": 40, "肩推": 6, "深蹲": 50},
    )
    last_week = _wk(
        actual_strength=3, planned_strength=4,
        max_weight_per_exercise={"硬舉": 36, "肩推": 6, "深蹲": 45},
    )
    out = weekly_lens.pick_workout_lens(this_week, last_week)
    assert "重量進步" in out
    assert "硬舉" in out and "36" in out and "40" in out  # biggest gainer surfaces
    assert "肩推 持平" in out  # zero-delta wording


def test_diet_lens_uses_per_day_actual_deficit():
    this_week = _wk(days_with_meals=7, avg_kcal=1381, avg_deficit=250, days_protein_met=4)
    last_week = _wk(days_with_meals=7, avg_kcal=1500, avg_deficit=80, days_protein_met=4)
    out = weekly_lens.pick_diet_lens(this_week, last_week)
    assert "+250" in out  # actual deficit, not naive (avg - TDEE)


def test_diet_lens_classifies_in_range_deficit_as_on_target():
    # 316 was the real-world example that AI was flagging as 過大
    this_week = _wk(days_with_meals=7, avg_deficit=316, days_protein_met=4)
    last_week = _wk(days_with_meals=7, avg_deficit=200, days_protein_met=4)
    out = weekly_lens.pick_diet_lens(this_week, last_week)
    assert "達標" in out
    assert "禁止解讀為過大或不足" in out


def test_diet_lens_classifies_high_deficit_as_excess():
    this_week = _wk(days_with_meals=7, avg_deficit=500, days_protein_met=4)
    last_week = _wk(days_with_meals=7, avg_deficit=400, days_protein_met=4)
    out = weekly_lens.pick_diet_lens(this_week, last_week)
    assert "偏高" in out
    assert "流失肌肉" in out


def test_diet_lens_classifies_low_deficit_as_insufficient():
    this_week = _wk(days_with_meals=7, avg_deficit=80, days_protein_met=4)
    last_week = _wk(days_with_meals=7, avg_deficit=100, days_protein_met=4)
    out = weekly_lens.pick_diet_lens(this_week, last_week)
    assert "偏低" in out
    assert "進度慢" in out


def test_diet_lens_pivots_to_forward_looking_when_both_on_target():
    # User's actual scenario: 316 deficit (達標) + 7/7 protein (perfect)
    this_week = _wk(days_with_meals=7, avg_deficit=316, days_protein_met=7)
    last_week = _wk(days_with_meals=7, avg_deficit=300, days_protein_met=7)
    out = weekly_lens.pick_diet_lens(this_week, last_week)
    assert "前瞻性" in out
    assert "不要硬挑毛病" in out
    # Should NOT contain "改進空間較大" — that's the problem-finding directive
    assert "改進空間較大" not in out


def test_day_burn_prefers_apple_watch_active_calories():
    # Has watch data + workout estimate — watch wins (no double-count)
    burn = weekly_lens._day_burn(
        active_cal=400,
        day_workouts=[{"workout_type": "羽球", "estimated_calories": 300}],
    )
    assert burn == weekly_lens.BASE_TDEE + 400


def test_day_burn_falls_back_to_workout_estimate():
    burn = weekly_lens._day_burn(
        active_cal=0,
        day_workouts=[{"workout_type": "羽球", "estimated_calories": 300}],
    )
    assert burn == weekly_lens.BASE_TDEE + 300


def test_day_burn_excludes_rest_workouts():
    burn = weekly_lens._day_burn(
        active_cal=0,
        day_workouts=[{"workout_type": "休息日", "estimated_calories": 0}],
    )
    assert burn == weekly_lens.BASE_TDEE


@pytest.mark.asyncio
async def test_generate_insight_returns_none_when_all_lenses_empty():
    out = await weekly_lens.generate_weekly_insight("", "", "")
    assert out is None
