"""AI coach for Q&A and workout parsing using Gemini."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, timedelta

from google import genai
from google.genai import types

from app.config import GEMINI_API_KEY
from app.ai.prompts import (
    COACH_SYSTEM_PROMPT,
    COACH_QUERY_TEMPLATE,
    WORKOUT_PARSE_PROMPT,
    CONTEXT_EXTRACTION_PROMPT,
    FOOD_MENTION_PROMPT,
    WORKOUT_MENTION_PROMPT,
)
from app.db import queries as db

logger = logging.getLogger(__name__)

client = genai.Client(api_key=GEMINI_API_KEY)
MODEL = "gemini-2.5-flash"


# --------------- Context Builders ---------------

def _build_profile_context() -> str:
    """Format user profile as context string. Cached in DB layer."""
    profile = db.get_user_profile()
    if not profile:
        return "（尚未設定基本資料）"

    parts = []
    gender_map = {"female": "女性", "male": "男性"}
    if profile.get("gender"):
        parts.append(f"性別：{gender_map.get(profile['gender'], profile['gender'])}")
    if profile.get("birth_year"):
        age = date.today().year - profile["birth_year"]
        parts.append(f"年齡：{age} 歲（{profile['birth_year']}年生）")
    if profile.get("height_cm"):
        parts.append(f"身高：{profile['height_cm']}cm")
    if profile.get("work_style"):
        parts.append(f"工作：{profile['work_style']}")
    if profile.get("dietary_restrictions"):
        parts.append(f"飲食限制：{'、'.join(profile['dietary_restrictions'])}")
    if profile.get("medical_notes"):
        parts.append(f"傷病：{profile['medical_notes']}")

    habits = profile.get("exercise_habits", {})
    if habits:
        schedule = habits.get("schedule", [])
        for s in schedule:
            parts.append(f"運動：{s['activity']} {s.get('frequency', '')} ({s.get('duration', '')})")
        planned = habits.get("planned", [])
        for p in planned:
            parts.append(f"計畫：{p['activity']} {p.get('start', '')} {p.get('note', '')}")
        equip = habits.get("equipment")
        if equip:
            parts.append(f"器材：{equip}")

    return "\n".join(parts)


def _build_active_context() -> str:
    """Format active short-term context notes."""
    notes = db.get_active_context()
    if not notes:
        return "（無）"

    category_map = {
        "injury": "⚠️ 傷痛",
        "travel": "✈️ 旅行",
        "schedule": "📅 行程",
        "mood": "💭 狀態",
        "preference": "🍽 偏好",
        "other": "📌 備註",
    }

    lines = []
    for n in notes:
        cat = category_map.get(n["category"], n["category"])
        expiry = f"（到 {n['expires_at']}）" if n.get("expires_at") else ""
        lines.append(f"• {cat} {n['content']}{expiry}")

    return "\n".join(lines)


def _build_recent_workouts() -> str:
    """Summarize recent workouts for AI context."""
    workouts = db.get_recent_workouts(days=30)
    if not workouts:
        return "（最近 30 天無訓練紀錄）"

    lines = []
    for w in workouts[-10:]:  # last 10 workouts max
        date_str = w["created_at"][:10]
        wtype = w.get("workout_type", "")
        exercises = w.get("exercises", [])

        # Summarize key exercises with weights
        ex_parts = []
        for ex in exercises[:5]:  # max 5 per workout
            name = ex.get("name") or "?"
            weight = ex.get("weight_kg")
            reps = ex.get("reps")
            sets = ex.get("sets")
            parts = [name]
            if weight:
                parts.append(f"{weight}kg")
            if reps and sets:
                parts.append(f"{reps}x{sets}")
            ex_parts.append(" ".join(parts))

        ex_summary = "、".join(ex_parts)
        notes = w.get("notes", "")
        note_str = f" [{notes[:50]}]" if notes else ""
        lines.append(f"{date_str} {wtype}：{ex_summary}{note_str}")

    return "\n".join(lines)


def _build_user_context() -> str:
    """Gather recent user data (today's meals, workouts, metrics, goal)."""
    today = date.today()
    parts = []

    # Today's meals
    meals = db.get_meals_for_date(today)
    if meals:
        total_cal = sum(m.get("total_calories", 0) for m in meals)
        total_pro = sum(m.get("protein", 0) for m in meals)
        total_carb = sum(m.get("carbs", 0) for m in meals)
        total_fat = sum(m.get("fat", 0) for m in meals)
        parts.append(
            f"今日飲食：{len(meals)} 餐，"
            f"共 {total_cal:.0f} kcal（蛋白 {total_pro:.0f}g / "
            f"碳水 {total_carb:.0f}g / 脂肪 {total_fat:.0f}g）"
        )

    # Today's workouts
    workouts = db.get_workouts_for_date(today)
    if workouts:
        workout_names = [w.get("workout_type", "未分類") for w in workouts]
        parts.append(f"今日訓練：{', '.join(workout_names)}")

    # Recent body metrics (last 7 days)
    week_ago = today - timedelta(days=7)
    metrics = db.get_body_metrics_range(week_ago, today)
    if metrics:
        latest = metrics[-1]
        weight = latest.get("weight")
        bf = latest.get("body_fat_pct")
        steps = latest.get("steps")
        if weight:
            parts.append(f"最新體重：{weight} kg")
        if bf:
            parts.append(f"最新體脂：{bf}%")
        if steps:
            parts.append(f"今日步數：{steps}")
        if len(metrics) > 1 and metrics[0].get("weight") and latest.get("weight"):
            diff = latest["weight"] - metrics[0]["weight"]
            if abs(diff) > 0.1:
                direction = "↑" if diff > 0 else "↓"
                parts.append(f"7天體重趨勢：{direction} {abs(diff):.1f} kg")

    # Current goal
    goal = db.get_active_goal()
    if goal:
        goal_map = {"cut": "減脂", "bulk": "增肌", "maintain": "維持"}
        parts.append(f"目標：{goal_map.get(goal['goal_type'], goal['goal_type'])}")
        if goal.get("daily_calorie_target"):
            parts.append(f"每日熱量目標：{goal['daily_calorie_target']} kcal")
        if goal.get("daily_protein_target"):
            parts.append(f"每日蛋白質目標：{goal['daily_protein_target']}g")
        if goal.get("target_body_fat"):
            parts.append(f"目標體脂：{goal['target_body_fat']}%")

    return "\n".join(parts) if parts else "（今日尚無數據）"


def _build_chat_history() -> str:
    """Get recent chat history formatted for the prompt."""
    history = db.get_recent_chat(limit=20)
    if not history:
        return "（第一次對話）"

    lines = []
    for msg in history:
        role = "我" if msg["role"] == "user" else "小健"
        lines.append(f"{role}：{msg['message'][:200]}")

    return "\n".join(lines)


# --------------- Context Extraction ---------------

async def _extract_and_save_context(message: str):
    """Background task: extract notable context from user message and save."""
    try:
        prompt = CONTEXT_EXTRACTION_PROMPT.format(message=message)
        response = await client.aio.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=256,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )

        raw = (response.text or "").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
        raw = raw.strip()

        data = json.loads(raw)
        notes = data.get("notes", [])

        for note in notes:
            db.insert_user_context(
                category=note["category"],
                content=note["content"],
                expires_in_days=note.get("expires_in_days"),
                source_message=message[:200],
            )
            logger.info("Saved context note: [%s] %s", note["category"], note["content"])

    except Exception:
        logger.debug("Context extraction skipped or failed", exc_info=True)


async def _extract_and_save_food(message: str):
    """Background task: detect food mentions and save to meals table."""
    try:
        from datetime import datetime as dt
        current_hour = dt.now().hour
        prompt = FOOD_MENTION_PROMPT.format(message=message, current_hour=current_hour)
        response = await client.aio.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=512,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )

        raw = (response.text or "").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
        raw = raw.strip()

        data = json.loads(raw)
        foods = data.get("foods", [])
        meal_type = data.get("meal_type", "other")

        if foods:
            total_cal = sum(f.get("calories", 0) for f in foods)
            total_pro = sum(f.get("protein", 0) for f in foods)
            total_carb = sum(f.get("carbs", 0) for f in foods)
            total_fat = sum(f.get("fat", 0) for f in foods)
            names = ", ".join(f.get("name", "?") for f in foods)

            meal_label = {"breakfast": "早餐", "lunch": "午餐", "dinner": "晚餐", "snack": "點心"}.get(meal_type, "")

            db.insert_meal(
                photo_url=None,
                food_items=foods,
                total_calories=total_cal,
                protein=total_pro,
                carbs=total_carb,
                fat=total_fat,
                ai_response=f"💬 {meal_label}：{names}",
                source="text",
                meal_type=meal_type or "other",
            )
            logger.info("Saved text food [%s]: %s (%d kcal)", meal_type, names, total_cal)

    except Exception:
        logger.debug("Food extraction skipped or failed", exc_info=True)


async def _extract_and_save_workout(message: str):
    """Background task: detect workout mentions and save to workouts table."""
    try:
        prompt = WORKOUT_MENTION_PROMPT.format(message=message)
        response = await client.aio.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=512,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )

        raw = (response.text or "").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
        raw = raw.strip()

        data = json.loads(raw)
        workout = data.get("workout")

        if workout:
            db.insert_workout(
                workout_type=workout.get("workout_type", "未分類"),
                exercises=workout.get("exercises", []),
                duration_min=workout.get("duration_min"),
                estimated_calories=workout.get("estimated_calories"),
                notes=workout.get("notes"),
            )
            logger.info("Saved text workout: %s (%d exercises)",
                       workout.get("workout_type"), len(workout.get("exercises", [])))

    except Exception:
        logger.debug("Workout extraction skipped or failed", exc_info=True)


# --------------- Main Coach Functions ---------------

async def ask_coach(question: str) -> str:
    """Ask the AI coach a question with full multi-layer context."""
    # Save user message
    try:
        db.save_chat_message("user", question)
    except Exception:
        logger.exception("Failed to save user message")

    # Build all context layers
    user_profile = _build_profile_context()
    active_context = _build_active_context()
    recent_workouts = _build_recent_workouts()
    user_data = _build_user_context()
    chat_history = _build_chat_history()

    prompt = COACH_QUERY_TEMPLATE.format(
        system_context=COACH_SYSTEM_PROMPT,
        user_profile=user_profile,
        active_context=active_context,
        recent_workouts=recent_workouts,
        user_data=user_data,
        chat_history=chat_history,
        question=question,
    )

    response = await client.aio.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.7,
            max_output_tokens=1000,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )

    text = response.text
    reply = text.strip() if text else "抱歉，我現在沒有回應，請再問一次 🙏"

    # Save assistant reply
    try:
        db.save_chat_message("assistant", reply)
    except Exception:
        logger.exception("Failed to save assistant message")

    # Fire-and-forget background tasks
    asyncio.create_task(_extract_and_save_context(question))
    asyncio.create_task(_extract_and_save_food(question))
    asyncio.create_task(_extract_and_save_workout(question))

    return reply


async def parse_workout(text: str) -> dict:
    """Parse free-text workout description into structured data."""
    prompt = WORKOUT_PARSE_PROMPT.format(text=text)

    response = await client.aio.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.2,
            max_output_tokens=512,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )

    raw_text = (response.text or "").strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1]
    if raw_text.endswith("```"):
        raw_text = raw_text.rsplit("```", 1)[0]
    raw_text = raw_text.strip()

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        logger.error("Failed to parse workout JSON: %s", raw_text)
        return {
            "workout_type": "未分類",
            "exercises": [],
            "duration_min": None,
            "estimated_calories": None,
        }
