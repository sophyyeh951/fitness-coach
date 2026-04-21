import pytest
from unittest.mock import patch, AsyncMock
from linebot.v3.messaging import TextMessage


@pytest.mark.asyncio
async def test_slash_command_overrides_stuck_session():
    """A /動 typed while a prior exercise session is still active should
    clear the stale session and restart the flow — not get stuck in the
    type-selection fallback."""
    from app.line import handlers

    stale_session = {"mode": "awaiting_exercise_type", "draft": {}}

    with patch("app.line.handlers.get_session", return_value=stale_session), \
         patch("app.line.handlers.clear_session") as mock_clear, \
         patch("app.line.handlers.set_session"):
        result = await handlers.handle_text_message("/動", "U123")

    mock_clear.assert_called_once_with("U123")
    assert isinstance(result, TextMessage)
    assert result.quick_reply is not None
    labels = [item.action.label for item in result.quick_reply.items]
    assert "羽球" in labels


@pytest.mark.asyncio
async def test_slash_command_overrides_meal_session():
    """Same fix applies to /吃 over a stale meal session."""
    from app.line import handlers

    stale_session = {"mode": "awaiting_food", "draft": {"meal_type": "lunch"}}

    with patch("app.line.handlers.get_session", return_value=stale_session), \
         patch("app.line.handlers.clear_session") as mock_clear, \
         patch("app.line.handlers.set_session"):
        result = await handlers.handle_text_message("/吃", "U123")

    mock_clear.assert_called_once_with("U123")
    assert isinstance(result, TextMessage)


@pytest.mark.asyncio
async def test_non_slash_text_still_routes_to_session():
    """Plain text during a session stays in the flow (doesn't clear)."""
    from app.line import handlers

    session = {"mode": "awaiting_food", "draft": {"meal_type": "lunch", "meal_type_display": "午餐"}}

    with patch("app.line.handlers.get_session", return_value=session), \
         patch("app.line.handlers.clear_session") as mock_clear, \
         patch("app.line.commands.meal.handle_food_input",
               new=AsyncMock(return_value=TextMessage(text="ok"))):
        await handlers.handle_text_message("雞腿便當", "U123")

    mock_clear.assert_not_called()


@pytest.mark.asyncio
async def test_exercise_type_fallback_reshows_quick_reply():
    """If user types non-sentinel text while awaiting_exercise_type,
    fallback message should carry the quick reply again, not be a dead string."""
    with patch("app.line.commands.exercise.set_session"):
        from app.line.commands.exercise import handle_exercise_type_selection
        result = await handle_exercise_type_selection("什麼運動都可以", "U123")

    assert isinstance(result, TextMessage)
    assert result.quick_reply is not None
    labels = [item.action.label for item in result.quick_reply.items]
    assert "羽球" in labels


@pytest.mark.asyncio
async def test_meal_type_fallback_reshows_quick_reply():
    """Same fix on /吃's type fallback."""
    with patch("app.line.commands.meal.set_session"):
        from app.line.commands.meal import handle_meal_type_selection
        result = await handle_meal_type_selection("隨便", "U123")

    assert isinstance(result, TextMessage)
    assert result.quick_reply is not None
    labels = [item.action.label for item in result.quick_reply.items]
    assert "早餐" in labels
