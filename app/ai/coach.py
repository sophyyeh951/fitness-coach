"""AI coach for Q&A and workout parsing using Gemini."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, timedelta

from google import genai
from google.genai import types

from app.config import GEMINI_API_KEY, today_tw
from app.ai.prompts import (
    COACH_SYSTEM_PROMPT,
    COACH_QUERY_TEMPLATE,
    QA_ONLY_QUERY_TEMPLATE,
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
        age = today_tw().year - profile["birth_year"]
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
    today = today_tw()
    parts = []

    # Today's meals (with details for modification reference)
    meals = db.get_meals_for_date(today)
    if meals:
        total_cal = sum(m.get("total_calories", 0) for m in meals)
        total_pro = sum(m.get("protein", 0) for m in meals)
        total_carb = sum(m.get("carbs", 0) for m in meals)
        total_fat = sum(m.get("fat", 0) for m in meals)
        parts.append(
            f"今日飲食：{len(meals)} 餐，"
            f"共 {total_cal:.0f} kcal（P {total_pro:.0f}g / C {total_carb:.0f}g / F {total_fat:.0f}g）"
        )
        for m in meals:
            foods = m.get("food_items", [])
            names = ", ".join(f.get("name", "?") for f in foods) if foods else "?"
            mt = m.get("meal_type", "other")
            parts.append(f"  #{m['id']}({mt}) {names} {m.get('total_calories', 0):.0f}kcal")

    # Today's workouts
    workouts = db.get_workouts_for_date(today)
    if workouts:
        workout_names = [w.get("workout_type", "未分類") for w in workouts]
        parts.append(f"今日訓練：{', '.join(workout_names)}")

    # Body metrics: recent for current stats, long-range for trends
    week_ago = today - timedelta(days=7)
    recent_metrics = db.get_body_metrics_range(week_ago, today)
    if recent_metrics:
        latest = recent_metrics[-1]
        weight = latest.get("weight")
        bf = latest.get("body_fat_pct")
        if weight:
            parts.append(f"最新體重：{weight} kg")
        if bf:
            parts.append(f"最新體脂：{bf}%")

    # Long-range body composition trend (180 days for cut/bulk tracking)
    long_ago = today - timedelta(days=180)
    all_metrics = db.get_body_metrics_range(long_ago, today)
    if all_metrics and len(all_metrics) > 1:
        # Weight trend
        first_w = next((m.get("weight") for m in all_metrics if m.get("weight")), None)
        last_w = next((m.get("weight") for m in reversed(all_metrics) if m.get("weight")), None)
        if first_w and last_w:
            diff = last_w - first_w
            if abs(diff) > 0.1:
                direction = "↑" if diff > 0 else "↓"
                parts.append(f"體重趨勢：{direction} {abs(diff):.1f} kg（{all_metrics[0]['date']}～今）")

        # Body fat trend
        bf_records = [(m["date"], m["body_fat_pct"]) for m in all_metrics if m.get("body_fat_pct")]
        if len(bf_records) >= 2:
            first_bf = bf_records[0]
            last_bf = bf_records[-1]
            bf_diff = last_bf[1] - first_bf[1]
            direction = "↑" if bf_diff > 0 else "↓"
            parts.append(f"體脂趨勢：{direction} {abs(bf_diff):.1f}%（{first_bf[0]} {first_bf[1]}% → {last_bf[0]} {last_bf[1]}%）")

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

        # Build recent foods list for duplicate detection
        today = today_tw()
        today_meals = db.get_meals_for_date(today)
        recent_foods = ", ".join(
            f.get("name", "?")
            for m in today_meals
            for f in m.get("food_items", [])
        ) if today_meals else "（今天還沒有記錄）"

        prompt = FOOD_MENTION_PROMPT.format(
            message=message,
            current_hour=current_hour,
            recent_foods=recent_foods,
        )
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


# --------------- Data Modification ---------------

def _execute_data_commands(reply: str) -> str:
    """Parse and execute data modification commands embedded in AI reply."""
    import re

    # DELETE_MEAL:ID
    for match in re.finditer(r'\[DELETE_MEAL:(\d+)\]', reply):
        meal_id = int(match.group(1))
        try:
            db.delete_meal(meal_id)
            logger.info("Deleted meal ID %d", meal_id)
        except Exception:
            logger.exception("Failed to delete meal %d", meal_id)
    reply = re.sub(r'\[DELETE_MEAL:\d+\]', '', reply)

    # DELETE_WORKOUT:ID
    for match in re.finditer(r'\[DELETE_WORKOUT:(\d+)\]', reply):
        workout_id = int(match.group(1))
        try:
            db.delete_workout(workout_id)
            logger.info("Deleted workout ID %d", workout_id)
        except Exception:
            logger.exception("Failed to delete workout %d", workout_id)
    reply = re.sub(r'\[DELETE_WORKOUT:\d+\]', '', reply)

    # UPDATE_MEAL:ID:field=value
    for match in re.finditer(r'\[UPDATE_MEAL:(\d+):(\w+)=(\w+)\]', reply):
        meal_id = int(match.group(1))
        field = match.group(2)
        value = match.group(3)
        allowed_fields = {"meal_type", "source"}
        if field in allowed_fields:
            try:
                db.update_meal(meal_id, {field: value})
                logger.info("Updated meal %d: %s=%s", meal_id, field, value)
            except Exception:
                logger.exception("Failed to update meal %d", meal_id)
    reply = re.sub(r'\[UPDATE_MEAL:\d+:\w+=\w+\]', '', reply)

    # REPLACE_MEAL_FOODS:ID with JSON block
    for match in re.finditer(
        r'\[REPLACE_MEAL_FOODS:(\d+)\]\s*(\{.*?\})\s*\[/REPLACE_MEAL_FOODS\]',
        reply, re.DOTALL
    ):
        meal_id = int(match.group(1))
        try:
            data = json.loads(match.group(2))
            db.update_meal(meal_id, {
                "food_items": data.get("foods", []),
                "total_calories": data.get("total_calories", 0),
                "protein": data.get("total_protein", 0),
                "carbs": data.get("total_carbs", 0),
                "fat": data.get("total_fat", 0),
            })
            logger.info("Replaced foods in meal %d", meal_id)
        except Exception:
            logger.exception("Failed to replace foods in meal %d", meal_id)
    reply = re.sub(
        r'\[REPLACE_MEAL_FOODS:\d+\]\s*\{.*?\}\s*\[/REPLACE_MEAL_FOODS\]',
        '', reply, flags=re.DOTALL
    )

    return reply.strip()


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

    # Execute any data modification commands in the reply
    reply = _execute_data_commands(reply)

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


async def ask_coach_qa_only(question: str) -> str:
    """Q&A only mode — answers questions but NEVER logs food/workout data.

    This is the default handler for all free-text messages (no command prefix).
    The prompt explicitly forbids the model from triggering any logging.
    """
    try:
        db.save_chat_message("user", question)
    except Exception:
        logger.exception("Failed to save user message")

    user_profile = _build_profile_context()
    active_context = _build_active_context()
    recent_workouts = _build_recent_workouts()
    user_data = _build_user_context()
    chat_history = _build_chat_history()

    prompt = QA_ONLY_QUERY_TEMPLATE.format(
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
    # Note: NO _execute_data_commands here — Q&A never modifies data

    try:
        db.save_chat_message("assistant", reply)
    except Exception:
        logger.exception("Failed to save assistant message")

    # Only fire context extraction (no food/workout extraction in Q&A mode)
    asyncio.create_task(_extract_and_save_context(question))

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
