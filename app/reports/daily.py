"""Generate and send daily summary reports."""

from __future__ import annotations

import logging
from datetime import date, timedelta

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
            + f"\n合計：{total_cal:.0f} kcal（P {total_pro:.0f}g / C {total_carb:.0f}g / F {total_fat:.0f}g）"
        )
    else:
        meals_summary = "今天沒有記錄飲食"

    # Build workout summary
    if workouts:
        workout_lines = []
        for w in workouts:
            exercises = w.get("exercises", [])
            ex_names = ", ".join(e.get("name", "?") for e in exercises) if exercises else "未記錄動作"
            cal = w.get("estimated_calories")
            cal_str = f"（~{cal:.0f} kcal）" if cal else ""
            workout_lines.append(f"{w.get('workout_type', '未分類')}：{ex_names}{cal_str}")
            if w.get("notes"):
                workout_lines.append(f"  備註：{w['notes'][:80]}")
        workout_summary = "\n".join(workout_lines)
    else:
        workout_summary = "今天沒有記錄訓練"

    # Today's body data (weight, body fat, active calories — no steps)
    today_metrics = db.get_body_metrics_range(target_date, target_date)
    body_parts = []
    if today_metrics:
        latest = today_metrics[-1]
        if latest.get("weight"):
            body_parts.append(f"體重：{latest['weight']} kg")
        if latest.get("body_fat_pct"):
            body_parts.append(f"體脂：{latest['body_fat_pct']}%")
        if latest.get("active_calories"):
            body_parts.append(f"活動消耗：{latest['active_calories']} kcal")

    # Calorie burn estimate
    base_tdee = 1483
    active_cal = today_metrics[-1].get("active_calories", 0) if today_metrics else 0
    total_burn = base_tdee + (active_cal or 0)
    body_parts.append(f"預估總消耗：{total_burn:.0f} kcal")
    body_data = "\n".join(body_parts) if body_parts else "無數據"

    # Long-range body fat trend (180 days)
    all_metrics = db.get_body_metrics_range(target_date - timedelta(days=180), target_date)
    bf_records = [(m["date"], m["body_fat_pct"]) for m in all_metrics if m.get("body_fat_pct")]
    if len(bf_records) >= 2:
        first_bf = bf_records[0]
        last_bf = bf_records[-1]
        bf_diff = last_bf[1] - first_bf[1]
        direction = "↑" if bf_diff > 0 else "↓"
        body_data += f"\n體脂趨勢：{first_bf[0]} {first_bf[1]}% → {last_bf[0]} {last_bf[1]}%（{direction}{abs(bf_diff):.1f}%）"

    # Goal info with actual vs target
    if goal:
        goal_map = {"cut": "減脂", "bulk": "增肌", "maintain": "維持"}
        goal_parts = [f"目標：{goal_map.get(goal['goal_type'], goal['goal_type'])}"]
        if goal.get("target_body_fat") and bf_records:
            current_bf = bf_records[-1][1]
            target_bf = goal["target_body_fat"]
            remaining = current_bf - target_bf
            goal_parts.append(f"目標體脂 {target_bf}%，目前 {current_bf}%，還差 {remaining:.1f}%")
        if goal.get("daily_calorie_target"):
            goal_parts.append(f"每日熱量目標：{goal['daily_calorie_target']} kcal")
        goal_info = "\n".join(goal_parts)
    else:
        goal_info = "尚未設定目標"

    # User profile
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
            "total_calories_in": total_cal if meals else None,
            "total_protein": total_pro if meals else None,
            "total_carbs": total_carb if meals else None,
            "total_fat": total_fat if meals else None,
            "workout_summary": workout_summary if workouts else None,
            "ai_advice": summary_text,
        })
    except Exception:
        logger.exception("Failed to save daily summary")

    return summary_text
