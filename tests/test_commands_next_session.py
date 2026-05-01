import pytest
from unittest.mock import patch


@pytest.mark.asyncio
async def test_next_session_uses_muscle_group_for_canonical_names():
    """`/下次 胸肩` must look up by muscle_group column, NOT workout_type ilike.
    This is the regression: pre-fix it ilike-matched workout_type and pulled
    very old free-text records, ignoring new tagged sessions."""
    with patch("app.line.commands.next_session.db") as mock_db:
        mock_db.get_last_workout_by_muscle_group.return_value = {
            "created_at": "2026-04-28T10:00:00",
            "exercises": [{"name": "臥推", "weight_kg": 20, "reps": 10, "sets": 3}],
            "notes": "右肩有點緊",
        }
        from app.line.commands.next_session import handle_next_session
        # Force fallback path off — the AI call should fail/skipped harmlessly
        with patch("app.line.commands.next_session.GEMINI_API_KEY", None):
            result = await handle_next_session("胸肩")

    mock_db.get_last_workout_by_muscle_group.assert_called_with("胸肩")
    assert mock_db.get_workouts_by_type.called is False
    assert "2026-04-28" in result
    assert "臥推" in result


@pytest.mark.asyncio
async def test_next_session_alias_上半身_picks_latest_of_chest_or_back():
    """`/下次 上半身` should query both 胸肩 and 背 and pick whichever is newer."""
    chest_row = {
        "created_at": "2026-04-20T10:00:00",
        "exercises": [{"name": "臥推", "weight_kg": 20, "reps": 10, "sets": 3}],
        "notes": None,
    }
    back_row = {
        "created_at": "2026-04-29T10:00:00",  # newer
        "exercises": [{"name": "划船", "weight_kg": 25, "reps": 8, "sets": 4}],
        "notes": None,
    }

    def fake_lookup(group):
        return {"胸肩": chest_row, "背": back_row}.get(group)

    with patch("app.line.commands.next_session.db") as mock_db:
        mock_db.get_last_workout_by_muscle_group.side_effect = fake_lookup
        from app.line.commands.next_session import handle_next_session
        with patch("app.line.commands.next_session.GEMINI_API_KEY", None):
            result = await handle_next_session("上半身")

    # Must have queried both
    called_args = [c.args[0] for c in mock_db.get_last_workout_by_muscle_group.call_args_list]
    assert "胸肩" in called_args
    assert "背" in called_args
    # Picked the newer one
    assert "2026-04-29" in result
    assert "划船" in result


@pytest.mark.asyncio
async def test_next_session_no_record_for_muscle_group():
    with patch("app.line.commands.next_session.db") as mock_db:
        mock_db.get_last_workout_by_muscle_group.return_value = None
        from app.line.commands.next_session import handle_next_session
        result = await handle_next_session("臀腿")

    assert "還沒有" in result
    assert "臀腿" in result


@pytest.mark.asyncio
async def test_next_session_cardio_falls_back_to_workout_type():
    """游泳 / 跑步 不在 muscle_group 別名表 → 退回 workout_type ilike 查詢。"""
    with patch("app.line.commands.next_session.db") as mock_db:
        mock_db.get_workouts_by_type.return_value = [
            {
                "created_at": "2026-04-25T10:00:00",
                "exercises": [],
                "notes": "輕鬆游 1500m",
            }
        ]
        from app.line.commands.next_session import handle_next_session
        with patch("app.line.commands.next_session.GEMINI_API_KEY", None):
            result = await handle_next_session("游泳")

    mock_db.get_workouts_by_type.assert_called_once()
    assert mock_db.get_last_workout_by_muscle_group.called is False
    assert "2026-04-25" in result


@pytest.mark.asyncio
async def test_next_session_empty_args_shows_help():
    from app.line.commands.next_session import handle_next_session
    result = await handle_next_session("")
    assert "胸肩" in result
    assert "臀腿" in result
