import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch


def _make_session_row(mode="awaiting_meal_type", draft=None, minutes_from_now=30):
    expires = datetime.now(timezone.utc) + timedelta(minutes=minutes_from_now)
    return {
        "user_id": "U123",
        "mode": mode,
        "draft": draft or {},
        "expires_at": expires.isoformat(),
    }


def test_get_session_returns_none_when_not_found():
    with patch("app.line.session.supabase") as mock_sb:
        mock_sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
        from app.line.session import get_session
        result = get_session("U123")
    assert result is None


def test_get_session_returns_none_when_expired():
    row = _make_session_row(minutes_from_now=-1)  # expired 1 minute ago
    with patch("app.line.session.supabase") as mock_sb:
        mock_sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [row]
        from app.line.session import get_session
        result = get_session("U123")
    assert result is None


def test_get_session_returns_session_when_valid():
    row = _make_session_row(mode="awaiting_food", draft={"meal_type": "lunch"})
    with patch("app.line.session.supabase") as mock_sb:
        mock_sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [row]
        from app.line.session import get_session
        result = get_session("U123")
    assert result is not None
    assert result["mode"] == "awaiting_food"
    assert result["draft"]["meal_type"] == "lunch"


def test_set_session_upserts_with_expiry():
    with patch("app.line.session.supabase") as mock_sb:
        mock_sb.table.return_value.upsert.return_value.execute.return_value.data = [{}]
        from app.line.session import set_session
        set_session("U123", mode="awaiting_food", draft={"meal_type": "lunch"})

    call_args = mock_sb.table.return_value.upsert.call_args[0][0]
    assert call_args["user_id"] == "U123"
    assert call_args["mode"] == "awaiting_food"
    assert call_args["draft"]["meal_type"] == "lunch"
    assert "expires_at" in call_args


def test_clear_session_deletes_row():
    with patch("app.line.session.supabase") as mock_sb:
        mock_sb.table.return_value.delete.return_value.eq.return_value.execute.return_value.data = [{}]
        from app.line.session import clear_session
        clear_session("U123")

    mock_sb.table.return_value.delete.return_value.eq.assert_called_once_with("user_id", "U123")
