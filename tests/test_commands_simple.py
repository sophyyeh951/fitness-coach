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
async def test_handle_help_returns_command_guide():
    from app.line.commands.simple import handle_help
    result = await handle_help()
    assert "/吃" in result
    assert "/動" in result
    assert "/身體" in result
    assert "/今日" in result
    assert "/下次" in result
    assert "/週報" in result
