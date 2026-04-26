# tests/test_commands_meal.py
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from linebot.v3.messaging import TextMessage

from app.line.confirm import MEAL_SENTINELS


@pytest.mark.asyncio
async def test_start_meal_flow_returns_meal_type_prompt():
    with patch("app.line.session.supabase"):
        from app.line.commands.meal import start_meal_flow
        result = await start_meal_flow("U123")

    assert isinstance(result, TextMessage)
    assert "這餐是" in result.text
    assert result.quick_reply is not None
    labels = [item.action.label for item in result.quick_reply.items]
    assert "早餐" in labels
    assert "午餐" in labels
    assert "晚餐" in labels
    assert "點心" in labels


@pytest.mark.asyncio
async def test_handle_meal_type_selection_sets_session():
    with patch("app.line.commands.meal.set_session") as mock_set, \
         patch("app.line.commands.meal.get_session", return_value={"mode": "awaiting_meal_type", "draft": {}}):
        from app.line.commands.meal import handle_meal_type_selection
        result = await handle_meal_type_selection("__meal_lunch__", "U123")

    mock_set.assert_called_once_with("U123", mode="awaiting_food", draft={"meal_type": "lunch", "meal_type_display": "午餐"})
    assert isinstance(result, str)
    assert "午餐" in result


@pytest.mark.asyncio
async def test_handle_meal_confirm_saves_and_clears_session():
    draft = {
        "meal_type": "lunch",
        "meal_type_display": "午餐",
        "foods": [{"name": "蒸蛋", "calories": 80, "protein": 8, "carbs": 1, "fat": 5, "portion": "1份"}],
        "total_calories": 80,
        "total_protein": 8,
        "total_carbs": 1,
        "total_fat": 5,
    }
    with patch("app.line.commands.meal.db") as mock_db, \
         patch("app.line.commands.meal.clear_session") as mock_clear:
        mock_db.insert_meal.return_value = {"id": 42}
        mock_db.get_meals_for_date.return_value = []
        mock_db.get_workouts_for_date.return_value = []
        mock_db.get_body_metrics_range.return_value = []
        from app.line.commands.meal import handle_meal_confirm
        result = await handle_meal_confirm(draft, "U123")

    mock_db.insert_meal.assert_called_once()
    mock_clear.assert_called_once_with("U123")
    assert "已儲存" in result or "午餐" in result
