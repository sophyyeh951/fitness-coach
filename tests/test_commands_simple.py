import pytest
from unittest.mock import patch


@pytest.mark.asyncio
async def test_handle_rest_saves_rest_day():
    with patch("app.line.commands.simple.db") as mock_db:
        mock_db.insert_workout.return_value = {"id": 99}
        from app.line.commands.simple import handle_rest
        result = await handle_rest("健檢", "U123")

    mock_db.insert_workout.assert_called_once()
    call_kwargs = mock_db.insert_workout.call_args
    assert "休息" in str(call_kwargs)
    assert isinstance(result, str)
    assert "休息" in result


@pytest.mark.asyncio
async def test_handle_rest_appends_today_intake_summary():
    """After /休息 saves, response should include today's running totals
    (建議攝取 / 休息日 burn label) so user sees the new target without /今日."""
    with patch("app.line.commands.simple.db") as mock_simple_db, \
         patch("app.line.commands.meal.db") as mock_meal_db:
        mock_simple_db.insert_workout.return_value = {"id": 99}
        mock_meal_db.get_meals_for_date.return_value = []
        mock_meal_db.get_workouts_for_date.return_value = [
            {"workout_type": "休息", "estimated_calories": 0}
        ]
        mock_meal_db.get_body_metrics_range.return_value = []
        from app.line.commands.simple import handle_rest
        result = await handle_rest("", "U123")

    assert "已記錄今天是休息日" in result
    assert "目標攝取" in result
    assert "1300" in result  # MIN_DAILY_TARGET on rest day


@pytest.mark.asyncio
async def test_handle_help_returns_command_guide():
    from app.line.commands.simple import handle_help
    result = await handle_help()
    assert "/吃" in result
    assert "/動" in result
    assert "/身體" in result
    assert "/今日" in result
    assert "/下次" in result
    assert "/週報" in result
