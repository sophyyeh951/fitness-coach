from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from app.db.client import supabase


# --- Meals ---

def insert_meal(
    photo_url: str | None,
    food_items: list[dict],
    total_calories: float,
    protein: float,
    carbs: float,
    fat: float,
    ai_response: str,
) -> dict:
    return (
        supabase.table("meals")
        .insert({
            "photo_url": photo_url,
            "food_items": food_items,
            "total_calories": total_calories,
            "protein": protein,
            "carbs": carbs,
            "fat": fat,
            "ai_response": ai_response,
        })
        .execute()
        .data[0]
    )


def get_meals_for_date(target_date: date) -> list[dict]:
    start = datetime.combine(target_date, datetime.min.time()).isoformat()
    end = datetime.combine(target_date, datetime.max.time()).isoformat()
    return (
        supabase.table("meals")
        .select("*")
        .gte("created_at", start)
        .lte("created_at", end)
        .order("created_at")
        .execute()
        .data
    )


# --- Workouts ---

def insert_workout(
    workout_type: str,
    exercises: list[dict],
    duration_min: int | None = None,
    estimated_calories: float | None = None,
    notes: str | None = None,
) -> dict:
    return (
        supabase.table("workouts")
        .insert({
            "workout_type": workout_type,
            "exercises": exercises,
            "duration_min": duration_min,
            "estimated_calories": estimated_calories,
            "notes": notes,
        })
        .execute()
        .data[0]
    )


def get_workouts_for_date(target_date: date) -> list[dict]:
    start = datetime.combine(target_date, datetime.min.time()).isoformat()
    end = datetime.combine(target_date, datetime.max.time()).isoformat()
    return (
        supabase.table("workouts")
        .select("*")
        .gte("created_at", start)
        .lte("created_at", end)
        .order("created_at")
        .execute()
        .data
    )


# --- Body Metrics ---

def upsert_body_metrics(metrics: dict) -> dict:
    return (
        supabase.table("body_metrics")
        .upsert(metrics, on_conflict="date")
        .execute()
        .data[0]
    )


def get_body_metrics_range(start_date: date, end_date: date) -> list[dict]:
    return (
        supabase.table("body_metrics")
        .select("*")
        .gte("date", start_date.isoformat())
        .lte("date", end_date.isoformat())
        .order("date")
        .execute()
        .data
    )


# --- Daily Summary ---

def upsert_daily_summary(summary: dict) -> dict:
    return (
        supabase.table("daily_summary")
        .upsert(summary, on_conflict="date")
        .execute()
        .data[0]
    )


def get_daily_summary(target_date: date) -> dict | None:
    result = (
        supabase.table("daily_summary")
        .select("*")
        .eq("date", target_date.isoformat())
        .execute()
        .data
    )
    return result[0] if result else None


# --- User Goals ---

def get_active_goal() -> dict | None:
    result = (
        supabase.table("user_goals")
        .select("*")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
        .data
    )
    return result[0] if result else None


# --- Chat History ---

def save_chat_message(role: str, message: str) -> dict:
    return (
        supabase.table("chat_history")
        .insert({"role": role, "message": message})
        .execute()
        .data[0]
    )


def get_recent_chat(limit: int = 20) -> list[dict]:
    return (
        supabase.table("chat_history")
        .select("role,message,created_at")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
        .data
    )[::-1]  # reverse to chronological order


def set_goal(
    goal_type: str,
    target_weight: float | None = None,
    target_body_fat: float | None = None,
    daily_calorie_target: float | None = None,
    daily_protein_target: float | None = None,
) -> dict:
    return (
        supabase.table("user_goals")
        .insert({
            "goal_type": goal_type,
            "target_weight": target_weight,
            "target_body_fat": target_body_fat,
            "daily_calorie_target": daily_calorie_target,
            "daily_protein_target": daily_protein_target,
        })
        .execute()
        .data[0]
    )
