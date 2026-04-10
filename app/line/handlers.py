"""
Message handlers — dispatches LINE messages to the appropriate logic.

Text messages:
  - Starts with "記錄" or "訓練" → workout recording
  - Starts with "/" → command (e.g. /目標, /今日, /週報)
  - Otherwise → Q&A with AI coach

Image messages:
  - Food photo → nutritional analysis
  - Body data screenshot (PICOOC, Apple Watch) → record body metrics
  - Nutrition label → record nutritional info
"""

from __future__ import annotations

import logging
from datetime import date

from linebot.v3.messaging import AsyncMessagingApiBlob

from app.ai.image_analyzer import (
    classify_image,
    analyze_food_photo,
    analyze_body_data,
    analyze_nutrition_label,
    format_food_analysis,
    format_body_data,
    format_nutrition_label,
)
from app.ai.coach import ask_coach, parse_workout
from app.db import queries as db

logger = logging.getLogger(__name__)

# Keywords that trigger workout recording
WORKOUT_PREFIXES = ("記錄", "訓練", "練")


async def handle_text_message(text: str) -> str:
    """Handle incoming text messages from LINE."""
    text = text.strip()

    # Command handling
    if text.startswith("/"):
        return await _handle_command(text)

    # Workout recording
    if any(text.startswith(p) for p in WORKOUT_PREFIXES):
        return await _handle_workout(text)

    # Default: Q&A with AI coach
    return await ask_coach(text)


async def handle_image_message(
    message_id: str,
    blob_api: AsyncMessagingApiBlob,
) -> str:
    """Handle incoming image messages — classify and route."""
    # Download image from LINE
    response = await blob_api.get_message_content(message_id)
    image_bytes = response

    # Step 1: Classify the image
    img_type = await classify_image(image_bytes)
    logger.info("Image classified as: %s", img_type)

    # Step 2: Route to appropriate handler
    if img_type == "food":
        return await _handle_food_image(image_bytes)
    elif img_type == "body_data":
        return await _handle_body_data_image(image_bytes)
    elif img_type == "nutrition_label":
        return await _handle_nutrition_label_image(image_bytes)
    else:
        # Unknown — try food analysis as default
        return await _handle_food_image(image_bytes)


async def _handle_food_image(image_bytes: bytes) -> str:
    """Analyze food photo and save to meals."""
    result = await analyze_food_photo(image_bytes)

    try:
        db.insert_meal(
            photo_url=None,
            food_items=result.get("foods", []),
            total_calories=result.get("total_calories", 0),
            protein=result.get("total_protein", 0),
            carbs=result.get("total_carbs", 0),
            fat=result.get("total_fat", 0),
            ai_response=format_food_analysis(result),
        )
    except Exception:
        logger.exception("Failed to save meal to database")

    return format_food_analysis(result)


async def _handle_body_data_image(image_bytes: bytes) -> str:
    """Extract body metrics from screenshot and save."""
    result = await analyze_body_data(image_bytes)

    if "error" in result:
        return format_body_data(result)

    # Build metrics dict for database
    today = date.today()
    measurement_date = result.get("measurement_date") or today.isoformat()

    metrics = {"date": measurement_date}
    if result.get("weight") is not None:
        metrics["weight"] = result["weight"]
    if result.get("body_fat_pct") is not None:
        metrics["body_fat_pct"] = result["body_fat_pct"]
    if result.get("muscle_pct") is not None:
        metrics["muscle_mass"] = result["muscle_pct"]  # store as muscle_mass field
    if result.get("bmi") is not None:
        metrics["bmi"] = result["bmi"]
    if result.get("steps") is not None:
        metrics["steps"] = result["steps"]
    if result.get("active_calories") is not None:
        metrics["active_calories"] = result["active_calories"]
    if result.get("resting_heart_rate") is not None:
        metrics["resting_heart_rate"] = result["resting_heart_rate"]

    try:
        db.upsert_body_metrics(metrics)
        logger.info("Saved body metrics from image: %s", metrics)
    except Exception:
        logger.exception("Failed to save body metrics")

    return format_body_data(result)


async def _handle_nutrition_label_image(image_bytes: bytes) -> str:
    """Extract nutrition info from label and save as meal."""
    result = await analyze_nutrition_label(image_bytes)

    if "error" in result:
        return format_nutrition_label(result)

    # Save as a meal record
    product_name = result.get("product_name") or "營養標示食品"
    try:
        db.insert_meal(
            photo_url=None,
            food_items=[{
                "name": product_name,
                "portion": result.get("serving_size", "一份"),
                "calories": result.get("calories", 0),
                "protein": result.get("protein", 0),
                "carbs": result.get("carbs", 0),
                "fat": result.get("fat", 0),
            }],
            total_calories=result.get("calories", 0),
            protein=result.get("protein", 0),
            carbs=result.get("carbs", 0),
            fat=result.get("fat", 0),
            ai_response=format_nutrition_label(result),
        )
    except Exception:
        logger.exception("Failed to save nutrition label meal")

    return format_nutrition_label(result)


async def _handle_workout(text: str) -> str:
    """Parse and record a workout."""
    parsed = await parse_workout(text)

    try:
        db.insert_workout(
            workout_type=parsed.get("workout_type", "未分類"),
            exercises=parsed.get("exercises", []),
            duration_min=parsed.get("duration_min"),
            estimated_calories=parsed.get("estimated_calories"),
            notes=text,
        )
    except Exception:
        logger.exception("Failed to save workout to database")
        return "訓練記錄儲存失敗，請稍後再試 🙏"

    # Format response
    lines = ["✅ 訓練已記錄！\n"]
    for ex in parsed.get("exercises", []):
        parts = [f"• {ex.get('name', '?')}"]
        if ex.get("sets") and ex.get("reps"):
            parts.append(f"{ex['sets']}x{ex['reps']}")
        if ex.get("weight_kg"):
            parts.append(f"@ {ex['weight_kg']}kg")
        if ex.get("duration_min"):
            parts.append(f"{ex['duration_min']}分鐘")
        lines.append(" ".join(parts))

    cal = parsed.get("estimated_calories")
    if cal:
        lines.append(f"\n🔥 預估消耗：{cal} kcal")

    return "\n".join(lines)


async def _handle_command(text: str) -> str:
    """Handle slash commands."""
    cmd = text.split()[0].lower()

    if cmd in ("/今日", "/today"):
        return await _today_summary()
    elif cmd in ("/目標", "/goal"):
        return _show_goal()

    return (
        "可用指令：\n"
        "/今日 — 查看今日飲食和訓練摘要\n"
        "/目標 — 查看目前的健身目標\n"
        "\n直接打字問問題，或傳食物照片/營養標示/體脂計截圖！"
    )


async def _today_summary() -> str:
    """Generate a quick today summary."""
    today = date.today()
    meals = db.get_meals_for_date(today)
    workouts = db.get_workouts_for_date(today)

    lines = [f"📋 {today.strftime('%Y/%m/%d')} 今日摘要\n"]

    if meals:
        total_cal = sum(m.get("total_calories", 0) for m in meals)
        total_pro = sum(m.get("protein", 0) for m in meals)
        total_carb = sum(m.get("carbs", 0) for m in meals)
        total_fat = sum(m.get("fat", 0) for m in meals)
        lines.append(f"🍽 飲食（{len(meals)} 餐）")
        lines.append(f"  熱量：{total_cal:.0f} kcal")
        lines.append(f"  蛋白質：{total_pro:.0f}g ｜碳水：{total_carb:.0f}g ｜脂肪：{total_fat:.0f}g")
    else:
        lines.append("🍽 今天還沒記錄飲食")

    if workouts:
        lines.append(f"\n💪 訓練（{len(workouts)} 次）")
        for w in workouts:
            lines.append(f"  • {w.get('workout_type', '未分類')}")
    else:
        lines.append("\n💪 今天還沒記錄訓練")

    # Show goal progress if available
    goal = db.get_active_goal()
    if goal and goal.get("daily_calorie_target") and meals:
        target = goal["daily_calorie_target"]
        remaining = target - total_cal
        if remaining > 0:
            lines.append(f"\n🎯 距離目標還可以吃 {remaining:.0f} kcal")
        else:
            lines.append(f"\n⚠️ 已超過目標 {abs(remaining):.0f} kcal")

    return "\n".join(lines)


def _show_goal() -> str:
    """Show current active goal."""
    goal = db.get_active_goal()
    if not goal:
        return "目前沒有設定目標。\n\n請告訴我你的目標，例如：「我想減脂，目標體重 70kg」"

    goal_map = {"cut": "🔥 減脂", "bulk": "💪 增肌", "maintain": "⚖️ 維持"}
    lines = [f"🎯 目前目標：{goal_map.get(goal['goal_type'], goal['goal_type'])}"]

    if goal.get("target_weight"):
        lines.append(f"目標體重：{goal['target_weight']} kg")
    if goal.get("target_body_fat"):
        lines.append(f"目標體脂：{goal['target_body_fat']}%")
    if goal.get("daily_calorie_target"):
        lines.append(f"每日熱量：{goal['daily_calorie_target']} kcal")
    if goal.get("daily_protein_target"):
        lines.append(f"每日蛋白質：{goal['daily_protein_target']}g")

    return "\n".join(lines)
