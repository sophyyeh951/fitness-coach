"""
Weekly exercise schedule storage.

Stored in user_profile.exercise_habits.weekly_schedule as JSONB.
"""

from __future__ import annotations
import logging
from datetime import date
from app.db.client import supabase

logger = logging.getLogger(__name__)

WEEKDAY_KEYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
WEEKDAY_CN = {"monday": "週一", "tuesday": "週二", "wednesday": "週三",
              "thursday": "週四", "friday": "週五", "saturday": "週六", "sunday": "週日"}


def get_schedule() -> dict:
    """Return the full schedule dict from user_profile."""
    result = supabase.table("user_profile").select("exercise_habits").limit(1).execute()
    if not result.data:
        return {}
    habits = result.data[0].get("exercise_habits") or {}
    return habits.get("weekly_schedule", {})


def get_today_exercise(target_date: date | None = None) -> str | None:
    """Return today's planned exercise type, respecting overrides."""
    if target_date is None:
        from app.config import today_tw
        target_date = today_tw()

    schedule = get_schedule()
    if not schedule:
        return None

    weekday_key = WEEKDAY_KEYS[target_date.weekday()]

    # Check overrides first
    for override in schedule.get("overrides", []):
        from_date = date.fromisoformat(override["from"])
        to_date = date.fromisoformat(override["to"])
        if from_date <= target_date <= to_date and weekday_key in override:
            return override[weekday_key]

    return schedule.get("default", {}).get(weekday_key)


def set_schedule(schedule: dict) -> None:
    """Save the full schedule dict to user_profile."""
    result = supabase.table("user_profile").select("id, exercise_habits").limit(1).execute()
    if not result.data:
        logger.warning("No user_profile found, cannot save schedule")
        return
    row = result.data[0]
    habits = row.get("exercise_habits") or {}
    habits["weekly_schedule"] = schedule
    supabase.table("user_profile").update({"exercise_habits": habits}).eq("id", row["id"]).execute()


def seed_initial_schedule() -> None:
    """Seed the schedule from the user's stated plan (April 2026 setup)."""
    schedule = {
        "default": {
            "monday": "重訓",
            "tuesday": "羽球",
            "wednesday": "重訓",
            "thursday": "重訓",
            "friday": "重訓",
            "saturday": "羽球",
            "sunday": "羽球",
        },
        "overrides": [
            {"from": "2026-05-01", "to": "2026-06-30", "thursday": "游泳"},
        ],
    }
    set_schedule(schedule)
    logger.info("Initial schedule seeded")
