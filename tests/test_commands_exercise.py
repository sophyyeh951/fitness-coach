import pytest
from unittest.mock import patch
from linebot.v3.messaging import TextMessage


@pytest.mark.asyncio
async def test_start_exercise_flow_cardio_builds_instant_confirm():
    """Cardio exercises show a confirm card immediately."""
    with patch("app.line.commands.exercise.set_session"):
        from app.line.commands.exercise import start_exercise_flow
        result = await start_exercise_flow("游泳 45分鐘", "U123")

    assert isinstance(result, TextMessage)
    assert "游泳" in result.text
    assert "45" in result.text
    assert result.quick_reply is not None


@pytest.mark.asyncio
async def test_start_exercise_flow_weights_asks_for_list():
    """Weight training asks for exercise list."""
    with patch("app.line.commands.exercise.set_session"):
        from app.line.commands.exercise import start_exercise_flow
        result = await start_exercise_flow("上半身重訓", "U123")

    assert isinstance(result, str)
    assert "菜單" in result or "貼" in result


@pytest.mark.asyncio
async def test_start_exercise_flow_empty_shows_type_quick_reply():
    """/動 alone shows a quick reply with workout types."""
    with patch("app.line.commands.exercise.set_session"):
        from app.line.commands.exercise import start_exercise_flow
        result = await start_exercise_flow("", "U123")

    assert isinstance(result, TextMessage)
    assert result.quick_reply is not None
    labels = [item.action.label for item in result.quick_reply.items]
    assert "羽球" in labels
    assert "重訓" in labels
    assert "游泳" in labels


@pytest.mark.asyncio
async def test_handle_exercise_type_selection_cardio_prompts_for_input():
    with patch("app.line.commands.exercise.set_session") as mock_set:
        from app.line.commands.exercise import handle_exercise_type_selection
        result = await handle_exercise_type_selection("__ex_badminton__", "U123")

    args, kwargs = mock_set.call_args
    assert kwargs["mode"] == "awaiting_exercise_input"
    assert kwargs["draft"]["workout_type"] == "羽球"
    assert isinstance(result, str)
    assert "羽球" in result


@pytest.mark.asyncio
async def test_handle_exercise_type_selection_strength_branches_to_list():
    with patch("app.line.commands.exercise.set_session") as mock_set:
        from app.line.commands.exercise import handle_exercise_type_selection
        result = await handle_exercise_type_selection("__ex_strength__", "U123")

    args, kwargs = mock_set.call_args
    assert kwargs["mode"] == "awaiting_exercise_list"
    assert "菜單" in result or "貼" in result


@pytest.mark.asyncio
async def test_handle_exercise_text_input_extracts_kcal():
    draft = {"workout_type": "羽球", "exercises": []}
    with patch("app.line.commands.exercise.set_session") as mock_set:
        from app.line.commands.exercise import handle_exercise_text_input
        result = await handle_exercise_text_input("2小時 650kcal", draft, "U123")

    args, kwargs = mock_set.call_args
    assert kwargs["mode"] == "awaiting_exercise_confirm"
    assert kwargs["draft"]["estimated_calories"] == 650
    assert kwargs["draft"]["duration_min"] == 120
    assert isinstance(result, TextMessage)


@pytest.mark.asyncio
async def test_handle_exercise_confirm_saves_workout():
    draft = {
        "workout_type": "上半身重訓",
        "exercises": [{"name": "硬舉", "weight_kg": 36, "reps": 10, "sets": 4}],
        "duration_min": None,
    }
    with patch("app.line.commands.exercise.db") as mock_db, \
         patch("app.line.commands.exercise.clear_session") as mock_clear, \
         patch("app.line.commands.exercise.set_session"):
        mock_db.insert_workout.return_value = {"id": 10}
        from app.line.commands.exercise import handle_exercise_confirm
        result = await handle_exercise_confirm(draft, "U123")

    mock_db.insert_workout.assert_called_once()
    assert mock_clear.called
