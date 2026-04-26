"""Tests for pick_coach_lens — picks the most salient angle for the daily summary."""
from __future__ import annotations


def test_no_signal_returns_empty():
    from app.reports.coach_lens import pick_coach_lens
    assert pick_coach_lens(
        today_meals=[],
        today_workouts=[],
        today_metrics=None,
        recent_summaries=[],
    ) == ""


def test_late_heavy_dinner_lens():
    """Dinner > 50% of day's intake → mention concentration."""
    from app.reports.coach_lens import pick_coach_lens
    meals = [
        {"meal_type": "breakfast", "total_calories": 200, "protein": 15},
        {"meal_type": "lunch",     "total_calories": 300, "protein": 20},
        {"meal_type": "dinner",    "total_calories": 900, "protein": 60},
    ]
    out = pick_coach_lens(meals, [], None, [])
    assert "晚餐" in out
    assert "%" in out  # mentions the percentage


def test_protein_shortfall_lens():
    """Protein < 90g → mention gap with specific number (when no late-heavy)."""
    from app.reports.coach_lens import pick_coach_lens
    meals = [
        {"meal_type": "breakfast", "total_calories": 400, "protein": 25},
        {"meal_type": "lunch",     "total_calories": 500, "protein": 25},
        {"meal_type": "dinner",    "total_calories": 400, "protein": 10},
    ]
    out = pick_coach_lens(meals, [], None, [])
    assert "蛋白質" in out
    assert "60" in out  # today's protein


def test_rest_streak_3_days_lens():
    """3+ consecutive rest days → gentle nudge."""
    from app.reports.coach_lens import pick_coach_lens
    today_workouts = [{"workout_type": "休息"}]
    recent = [
        {"date": "2026-04-24", "workout_summary": "休息"},
        {"date": "2026-04-25", "workout_summary": "休息"},
    ]
    out = pick_coach_lens([], today_workouts, None, recent)
    assert "休息" in out or "活動" in out
    assert "3" in out


def test_deficit_streak_3_days_lens():
    """Hitting target deficit 3 days in a row → reinforce consistency."""
    from app.reports.coach_lens import pick_coach_lens
    # BASE_TDEE - DAILY_DEFICIT = 1183; allow ±100 → 1083-1283 counts
    recent = [
        {"date": "2026-04-23", "total_calories_in": 1200},
        {"date": "2026-04-24", "total_calories_in": 1250},
        {"date": "2026-04-25", "total_calories_in": 1180},
    ]
    # Today must NOT trigger higher-priority lenses (low protein / late-heavy)
    out = pick_coach_lens(
        today_meals=[
            {"meal_type": "breakfast", "total_calories": 300, "protein": 30},
            {"meal_type": "lunch",     "total_calories": 400, "protein": 35},
            {"meal_type": "dinner",    "total_calories": 400, "protein": 35},
        ],
        today_workouts=[],
        today_metrics=None,
        recent_summaries=recent,
    )
    # streak now 3 (today not counted because it's not in recent_summaries)
    # so just past 3 days qualify
    assert "連續" in out or "3" in out
