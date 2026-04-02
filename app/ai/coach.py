"""AI coach for Q&A and workout parsing using Gemini."""

from __future__ import annotations

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
)
from app.db import queries as db

logger = logging.getLogger(__name__)

client = genai.Client(api_key=GEMINI_API_KEY)
MODEL = "gemini-2.5-flash"


def _build_user_context() -> str:
    """Gather recent user data to give the AI context."""
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
            f"今日飲食：已記錄 {len(meals)} 餐，"
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
        if weight:
            parts.append(f"最新體重：{weight} kg")
        if bf:
            parts.append(f"最新體脂：{bf}%")

    # Current goal
    goal = db.get_active_goal()
    if goal:
        goal_map = {"cut": "減脂", "bulk": "增肌", "maintain": "維持"}
        parts.append(
            f"目前目標：{goal_map.get(goal['goal_type'], goal['goal_type'])}"
        )
        if goal.get("daily_calorie_target"):
            parts.append(f"每日熱量目標：{goal['daily_calorie_target']} kcal")
        if goal.get("daily_protein_target"):
            parts.append(f"每日蛋白質目標：{goal['daily_protein_target']}g")

    return "\n".join(parts) if parts else "（尚無歷史數據）"


async def ask_coach(question: str) -> str:
    """Ask the AI coach a question with user context."""
    user_data = _build_user_context()

    prompt = COACH_QUERY_TEMPLATE.format(
        system_context=COACH_SYSTEM_PROMPT,
        user_data=user_data,
        question=question,
    )

    response = await client.aio.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.7,
            max_output_tokens=512,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )

    text = response.text
    return text.strip() if text else "抱歉，我現在沒有回應，請再問一次 🙏"


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

    raw_text = response.text.strip()
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
