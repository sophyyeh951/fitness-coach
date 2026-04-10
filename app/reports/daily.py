"""Generate and send daily summary reports."""

from __future__ import annotations

import logging
from datetime import date

from google import genai
from google.genai import types

from app.config import GEMINI_API_KEY, today_tw
from app.ai.prompts import DAILY_SUMMARY_PROMPT
from app.db import queries as db

logger = logging.getLogger(__name__)

client = genai.Client(api_key=GEMINI_API_KEY)
MODEL = "gemini-2.5-flash"


async def generate_daily_summary(target_date: date | None = None) -> str:
    """Generate a daily summary report for the given date."""
    if target_date is None:
        target_date = today_tw()

    # Gather data
    meals = db.get_meals_for_date(target_date)
    workouts = db.get_workouts_for_date(target_date)
    goal = db.get_active_goal()

    # Build meals summary
    if meals:
        total_cal = sum(m.get("total_calories", 0) for m in meals)
        total_pro = sum(m.get("protein", 0) for m in meals)
        total_carb = sum(m.get("carbs", 0) for m in meals)
        total_fat = sum(m.get("fat", 0) for m in meals)
        meal_details = []
        for i, m in enumerate(meals, 1):
            foods = m.get("food_items", [])
            food_names = ", ".join(f.get("name", "?") for f in foods) if foods else "未辨識"
            meal_details.append(f"第{i}餐：{food_names}（{m.get('total_calories', 0):.0f} kcal）")
        meals_summary = (
            "\n".join(meal_details)
            + f"\n合計：{total_cal:.0f} kcal（蛋白 {total_pro:.0f}g / 碳水 {total_carb:.0f}g / 脂肪 {total_fat:.0f}g）"
        )
    else:
        meals_summary = "今天沒有記錄飲食"

    # Build workout summary
    if workouts:
        workout_lines = []
        for w in workouts:
            exercises = w.get("exercises", [])
            ex_names = ", ".join(e.get("name", "?") for e in exercises) if exercises else "未記錄動作"
            workout_lines.append(f"{w.get('workout_type', '未分類')}：{ex_names}")
        workout_summary = "\n".join(workout_lines)
    else:
        workout_summary = "今天沒有記錄訓練"

    # Body data
    from datetime import timedelta

    metrics = db.get_body_metrics_range(target_date - timedelta(days=1), target_date)
    if metrics:
        latest = metrics[-1]
        body_parts = []
        if latest.get("weight"):
            body_parts.append(f"體重：{latest['weight']} kg")
        if latest.get("body_fat_pct"):
            body_parts.append(f"體脂：{latest['body_fat_pct']}%")
        if latest.get("steps"):
            body_parts.append(f"步數：{latest['steps']}")
        if latest.get("active_calories"):
            body_parts.append(f"活動消耗：{latest['active_calories']} kcal")
        body_data = "\n".join(body_parts) if body_parts else "無數據"
    else:
        body_data = "無數據"

    # Goal info
    if goal:
        goal_map = {"cut": "減脂", "bulk": "增肌", "maintain": "維持"}
        goal_parts = [f"目標：{goal_map.get(goal['goal_type'], goal['goal_type'])}"]
        if goal.get("daily_calorie_target"):
            goal_parts.append(f"每日熱量目標：{goal['daily_calorie_target']} kcal")
        if goal.get("daily_protein_target"):
            goal_parts.append(f"每日蛋白質目標：{goal['daily_protein_target']}g")
        goal_info = "\n".join(goal_parts)
    else:
        goal_info = "尚未設定目標"

    # User profile for personalized summary
    from app.ai.coach import _build_profile_context
    user_profile = _build_profile_context()

    # Generate with AI
    prompt = DAILY_SUMMARY_PROMPT.format(
        user_profile=user_profile,
        meals_summary=meals_summary,
        workout_summary=workout_summary,
        body_data=body_data,
        goal_info=goal_info,
    )

    response = await client.aio.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.5,
            max_output_tokens=512,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )

    summary_text = (response.text or "").strip()

    # Save summary to database
    try:
        db.upsert_daily_summary({
            "date": target_date.isoformat(),
            "total_calories_in": sum(m.get("total_calories", 0) for m in meals) if meals else None,
            "total_protein": sum(m.get("protein", 0) for m in meals) if meals else None,
            "total_carbs": sum(m.get("carbs", 0) for m in meals) if meals else None,
            "total_fat": sum(m.get("fat", 0) for m in meals) if meals else None,
            "steps": metrics[-1].get("steps") if metrics else None,
            "workout_summary": workout_summary if workouts else None,
            "ai_advice": summary_text,
        })
    except Exception:
        logger.exception("Failed to save daily summary")

    return summary_text
