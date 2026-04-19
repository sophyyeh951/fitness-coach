"""Session state for multi-turn LINE command flows.

Stores the current mode and draft data in Supabase so state
survives server restarts (Render free tier restarts frequently).

Modes:
  awaiting_meal_type     — sent /吃, waiting for user to tap meal type
  awaiting_food          — meal type chosen, waiting for photo or text
  awaiting_meal_confirm  — draft built, waiting for ✅/❌/correction
  awaiting_exercise_list — sent /動 for weight training, waiting for exercise list
  awaiting_exercise_confirm — exercise draft built, waiting for confirm
  awaiting_body_confirm  — body photo parsed, waiting for confirm
  awaiting_notes         — exercise saved, waiting for post-workout note
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from app.db.client import supabase

logger = logging.getLogger(__name__)

SESSION_TTL_MINUTES = 60  # Sessions expire after 60 minutes of inactivity


def get_session(user_id: str) -> dict | None:
    """Return the active session for user_id, or None if not found / expired."""
    result = (
        supabase.table("user_sessions")
        .select("*")
        .eq("user_id", user_id)
        .execute()
    )
    if not result.data:
        return None

    row = result.data[0]
    expires_at = datetime.fromisoformat(row["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at < datetime.now(timezone.utc):
        clear_session(user_id)
        return None

    return row


def set_session(user_id: str, mode: str, draft: dict | None = None) -> None:
    """Create or update the session for user_id."""
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=SESSION_TTL_MINUTES)
    supabase.table("user_sessions").upsert({
        "user_id": user_id,
        "mode": mode,
        "draft": draft or {},
        "expires_at": expires_at.isoformat(),
    }).execute()
    logger.debug("Session set: user=%s mode=%s", user_id, mode)


def clear_session(user_id: str) -> None:
    """Delete the session for user_id."""
    supabase.table("user_sessions").delete().eq("user_id", user_id).execute()
    logger.debug("Session cleared: user=%s", user_id)
