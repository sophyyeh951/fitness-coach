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

from app.config import today_tw
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
            source="photo",
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
    today = today_tw()
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
    if result.get("resting_heart_rate") is not None:
        metrics["resting_heart_rate"] = result["resting_heart_rate"]

    # Active calories: accumulate instead of overwrite
    new_active = result.get("active_calories")
    if new_active is not None and new_active > 0:
        existing = db.get_body_metrics_range(today, today)
        if existing and existing[-1].get("active_calories"):
            metrics["active_calories"] = existing[-1]["active_calories"] + new_active
        else:
            metrics["active_calories"] = new_active

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
            source="nutrition_label",
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
    """Generate today summary with meal categories, workouts, and calorie balance."""
    today = today_tw()
    meals = db.get_meals_for_date(today)
    workouts = db.get_workouts_for_date(today)
    metrics = db.get_body_metrics_range(today, today)

    lines = [f"📋 {today.strftime('%Y/%m/%d')} 今日摘要\n"]

    # --- Meals by category with P/C/F per meal ---
    if meals:
        total_cal = sum(m.get("total_calories", 0) for m in meals)
        total_pro = sum(m.get("protein", 0) for m in meals)
        total_carb = sum(m.get("carbs", 0) for m in meals)
        total_fat = sum(m.get("fat", 0) for m in meals)

        meal_type_label = {
            "breakfast": "🌅 早餐",
            "lunch": "☀️ 午餐",
            "dinner": "🌙 晚餐",
            "snack": "🍪 點心",
            "other": "🍽 其他",
        }

        # Group by meal_type
        grouped = {}
        for m in meals:
            mt = m.get("meal_type", "other") or "other"
            grouped.setdefault(mt, []).append(m)

        for mt_key in ["breakfast", "lunch", "dinner", "snack", "other"]:
            if mt_key not in grouped:
                continue
            label = meal_type_label.get(mt_key, "🍽")
            mt_meals = grouped[mt_key]
            mt_cal = sum(m.get("total_calories", 0) for m in mt_meals)
            mt_pro = sum(m.get("protein", 0) for m in mt_meals)
            mt_carb = sum(m.get("carbs", 0) for m in mt_meals)
            mt_fat = sum(m.get("fat", 0) for m in mt_meals)
            # Food names
            all_foods = []
            for m in mt_meals:
                foods = m.get("food_items", [])
                all_foods.extend(f.get("name", "?") for f in foods)
            food_str = ", ".join(all_foods) if all_foods else "?"
            lines.append(f"{label} {mt_cal:.0f}kcal")
            lines.append(f"  {food_str}")
            lines.append(f"  P {mt_pro:.0f}g / C {mt_carb:.0f}g / F {mt_fat:.0f}g")

        lines.append(f"\n📊 攝取合計：{total_cal:.0f} kcal")
        lines.append(f"  P {total_pro:.0f}g / C {total_carb:.0f}g / F {total_fat:.0f}g")
    else:
        total_cal = 0
        total_pro = 0
        lines.append("🍽 今天還沒記錄飲食")

    # --- Workouts: list all exercises ---
    if workouts:
        for w in workouts:
            wtype = w.get("workout_type", "未分類")
            exercises = w.get("exercises", [])
            cal = w.get("estimated_calories")
            cal_str = f" ~{cal:.0f}kcal" if cal else ""
            lines.append(f"\n💪 {wtype}{cal_str}")
            for ex in exercises:
                lines.append(f"  • {ex.get('name', '?')}")
            notes = w.get("notes")
            if notes:
                lines.append(f"  💭 {notes[:80]}")
    else:
        lines.append("\n💪 今天還沒記錄訓練")

    # --- Total calorie burn (2-stage: estimate → actual) ---
    base_tdee = 1483  # sedentary TDEE (BMR 1236 × 1.2)

    # Check if we have actual Apple Watch data
    has_actual = False
    active_cal = 0
    if metrics:
        m = metrics[-1]
        active_cal = m.get("active_calories") or 0
        if active_cal > 0:
            has_actual = True

    if has_actual:
        # Stage 2: actual data from Apple Watch
        total_burn = base_tdee + active_cal
        lines.append(f"\n🔥 總消耗：{total_burn:.0f} kcal（實際）")
        lines.append(f"  基底 {base_tdee} + 活動 {active_cal:.0f}")
    else:
        # Stage 1: estimate based on workout type or today's plan
        exercise_estimate = 0
        exercise_label = "休息日"

        # First check completed workouts
        if workouts:
            workout_types = [w.get("workout_type", "").lower() for w in workouts]
            all_types = " ".join(workout_types)
            if any(k in all_types for k in ["羽球", "有氧", "跑步", "游泳"]):
                exercise_estimate = 550
                exercise_label = "羽球/有氧日"
            else:
                exercise_estimate = 300
                exercise_label = "重訓日"
        else:
            # No workout recorded yet — check context notes and recent chat for plans
            context_notes = db.get_active_context()
            recent_chat = db.get_recent_chat(limit=10)
            plan_text = " ".join(
                [n.get("content", "") for n in context_notes]
                + [c.get("message", "") for c in recent_chat if c.get("role") == "user"]
            ).lower()

            if any(k in plan_text for k in ["羽球", "有氧", "跑步", "游泳", "打球"]):
                exercise_estimate = 550
                exercise_label = "羽球/有氧日（預估）"
            elif any(k in plan_text for k in ["重訓", "練上半身", "練臀腿", "練腿", "上半身日", "臀腿日"]):
                exercise_estimate = 300
                exercise_label = "重訓日（預估）"

        total_burn = base_tdee + exercise_estimate
        lines.append(f"\n🔥 預估總消耗：{total_burn:.0f} kcal")
        lines.append(f"  基底 {base_tdee} + {exercise_label} ~{exercise_estimate}")

    # --- Calorie balance ---
    if total_cal > 0:
        balance = total_cal - total_burn
        if balance < 0:
            lines.append(f"  → 赤字 {abs(balance):.0f} kcal ✅")
        else:
            lines.append(f"  → 盈餘 {balance:.0f} kcal")

    # --- Goal warnings: only when clearly off track ---
    goal = db.get_active_goal()
    if goal and total_cal > 0:
        cal_target = goal.get("daily_calorie_target")
        warnings = []

        if cal_target:
            diff = total_cal - cal_target
            if diff > cal_target * 0.1:
                warnings.append(f"⚠️ 超過熱量目標 {diff:.0f} kcal")

        # Protein: range is 1.6-2.2x body weight (86-118g)
        # Only warn if below lower bound (86g)
        protein_lower = 86
        if total_pro < protein_lower:
            warnings.append(f"🥩 蛋白質偏低（{total_pro:.0f}g），建議至少 {protein_lower}g")

        if warnings:
            lines.append("\n" + "\n".join(warnings))

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
