"""Tests for _burn_from_workouts — Priority-2 burn estimate from logged workouts."""
import pytest


def test_rest_only_returns_zero_and_rest_label():
    from app.line.commands.today import _burn_from_workouts
    est, label = _burn_from_workouts([{"workout_type": "休息", "estimated_calories": 0}])
    assert est == 0
    assert label == "休息"


def test_strength_plus_rest_uses_strength_estimate():
    """Bug 3: 重訓 + 休息 should NOT be zeroed out by the rest entry."""
    from app.line.commands.today import _burn_from_workouts
    workouts = [
        {"workout_type": "重訓", "estimated_calories": None},
        {"workout_type": "休息", "estimated_calories": 0},
    ]
    est, label = _burn_from_workouts(workouts)
    assert est == 300
    assert label == "重訓"


def test_uses_db_estimated_calories_when_present():
    """O2: real recorded kcal (e.g. 3-hr badminton = 1080) wins over hardcoded 550."""
    from app.line.commands.today import _burn_from_workouts
    workouts = [{"workout_type": "羽球", "estimated_calories": 1080}]
    est, label = _burn_from_workouts(workouts)
    assert est == 1080
    assert label == "羽球"


def test_label_uses_last_active_workout_type():
    """If user logs rest then later logs 重訓, label reflects 重訓."""
    from app.line.commands.today import _burn_from_workouts
    workouts = [
        {"workout_type": "休息", "estimated_calories": 0},
        {"workout_type": "重訓", "estimated_calories": None},
    ]
    est, label = _burn_from_workouts(workouts)
    assert est == 300
    assert label == "重訓"


def test_sums_multiple_active_workouts_with_mixed_kcal():
    """Cardio with kcal + strength without → sum of both, label = last active."""
    from app.line.commands.today import _burn_from_workouts
    workouts = [
        {"workout_type": "羽球", "estimated_calories": 1080},
        {"workout_type": "重訓", "estimated_calories": None},
    ]
    est, label = _burn_from_workouts(workouts)
    assert est == 1380  # 1080 + 300 fallback
    assert label == "重訓"
