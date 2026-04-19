"""
Message handlers — dispatches LINE messages to the appropriate logic.

Text messages (session-first routing):
  1. Active session → route to multi-turn flow handler
  2. Starts with "/" → slash command dispatch
  3. Otherwise → Q&A only (NEVER logs food/workout)

Image messages:
  - Food photo → nutritional analysis
  - Body data screenshot (PICOOC, Apple Watch) → record body metrics
  - Nutrition label → record nutritional info
"""

from __future__ import annotations

import logging
from datetime import date

from linebot.v3.messaging import AsyncMessagingApiBlob
from linebot.v3.messaging import TextMessage as LineTextMessage

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
from app.ai.coach import ask_coach, parse_workout, ask_coach_qa_only
from app.db import queries as db
from app.line.session import get_session, clear_session, set_session
from app.line.confirm import (
    CONFIRM_SENTINEL, CANCEL_SENTINEL, EDIT_SENTINEL,
    MEAL_SENTINELS, NOTES_SKIP_SENTINEL,
)

logger = logging.getLogger(__name__)


async def handle_text_message(text: str, user_id: str = "default") -> str | LineTextMessage:
    """Handle incoming text messages from LINE.

    Returns either a plain str (for Q&A replies) or a LineTextMessage
    (for confirm cards / quick-reply prompts). webhook.py handles both.
    """
    text = text.strip()

    # 1. Session continuation — check active multi-turn flow first
    session = get_session(user_id)
    if session:
        return await _handle_session(text, session, user_id)

    # 2. Slash command dispatch
    if text.startswith("/"):
        return await _handle_command(text, user_id)

    # 3. Q&A only — NEVER logs anything
    return await ask_coach_qa_only(text)


async def _handle_session(text: str, session: dict, user_id: str) -> str | LineTextMessage:
    """Route a message to the correct session handler based on current mode."""
    from app.line.commands.meal import (
        handle_meal_type_selection,
        handle_food_input,
        handle_meal_confirm,
        handle_meal_correction,
    )
    from app.line.commands.exercise import (
        handle_exercise_list_input,
        handle_exercise_confirm,
        handle_notes_input,
    )
    from app.line.commands.body import handle_body_confirm

    mode = session["mode"]
    draft = session.get("draft", {})

    # Meal flow
    if mode == "awaiting_meal_type":
        return await handle_meal_type_selection(text, user_id)
    if mode == "awaiting_food":
        return await handle_food_input(text, draft, user_id)
    if mode == "awaiting_meal_confirm":
        if text == CONFIRM_SENTINEL:
            return await handle_meal_confirm(draft, user_id)
        if text == CANCEL_SENTINEL:
            clear_session(user_id)
            return "已取消，沒有儲存任何資料。"
        if text == EDIT_SENTINEL:
            return "好，告訴我要改什麼？"
        # Any other text = correction
        return await handle_meal_correction(text, draft, user_id)

    # Exercise flow
    if mode == "awaiting_exercise_list":
        return await handle_exercise_list_input(text, draft, user_id)
    if mode == "awaiting_exercise_confirm":
        if text == CONFIRM_SENTINEL:
            return await handle_exercise_confirm(draft, user_id)
        if text == CANCEL_SENTINEL:
            clear_session(user_id)
            return "已取消，沒有儲存任何資料。"
        if text == EDIT_SENTINEL:
            return "好，告訴我要改什麼？"
        return await handle_exercise_list_input(text, draft, user_id)

    # Notes prompt
    if mode == "awaiting_notes":
        if text == NOTES_SKIP_SENTINEL:
            clear_session(user_id)
            return "好，這次不記備註。"
        return await handle_notes_input(text, draft, user_id)

    # Body data flow
    if mode == "awaiting_body_confirm":
        if text == CONFIRM_SENTINEL:
            return await handle_body_confirm(draft, user_id)
        if text == CANCEL_SENTINEL:
            clear_session(user_id)
            return "已取消，沒有儲存任何資料。"
        return "請點選下方按鈕確認或取消。"

    # Unknown mode — clear and fall through
    clear_session(user_id)
    return await ask_coach_qa_only(text)


async def _handle_command(text: str, user_id: str) -> str | LineTextMessage:
    """Dispatch slash commands to their handlers."""
    from app.line.commands.meal import start_meal_flow
    from app.line.commands.exercise import start_exercise_flow
    from app.line.commands.body import start_body_flow
    from app.line.commands.simple import handle_rest, handle_help
    from app.line.commands.today import handle_today
    from app.line.commands.next_session import handle_next_session
    from app.line.commands.report import handle_weekly_report
    from app.line.commands.schedule import handle_schedule

    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    args = parts[1].strip() if len(parts) > 1 else ""

    dispatch = {
        "/吃": lambda: start_meal_flow(user_id),
        "/動": lambda: start_exercise_flow(args, user_id),
        "/身體": lambda: start_body_flow(user_id),
        "/休息": lambda: handle_rest(args, user_id),
        "/今日": lambda: handle_today(),
        "/下次": lambda: handle_next_session(args),
        "/週報": lambda: handle_weekly_report(),
        "/計畫": lambda: handle_schedule(args, user_id),
        "/?": lambda: handle_help(),
        "/刪": lambda: _handle_delete(args),
        "/改": lambda: _handle_update(args),
    }

    handler = dispatch.get(cmd)
    if handler:
        return await handler()

    return f"未知指令：{cmd}\n輸入 /? 查看所有指令"


async def _handle_delete(args: str) -> str:
    """Delete a meal or workout by ID. Usage: /刪 37"""
    if not args.isdigit():
        return "格式：/刪 [ID]\n例：/刪 37"
    item_id = int(args)
    # Try meal first, then workout
    deleted = db.delete_meal(item_id)
    if not deleted:
        deleted = db.delete_workout(item_id)
    return f"✅ #{item_id} 已刪除" if deleted else f"找不到 #{item_id}，請用 /今日 確認 ID"


async def _handle_update(args: str) -> str:
    """Update a meal attribute. Usage: /改 37 午餐  or  /改 37 180kcal"""
    import re
    parts = args.split(maxsplit=1)
    if len(parts) < 2 or not parts[0].isdigit():
        return "格式：/改 [ID] [修改內容]\n例：/改 37 午餐\n   /改 37 180kcal"

    item_id = int(parts[0])
    change = parts[1].strip()

    meal_type_map = {"早餐": "breakfast", "午餐": "lunch", "晚餐": "dinner", "點心": "snack"}
    if change in meal_type_map:
        db.update_meal(item_id, {"meal_type": meal_type_map[change]})
        return f"✅ #{item_id} 已改為{change}"

    kcal_match = re.search(r"(\d+)\s*kcal", change)
    if kcal_match:
        db.update_meal(item_id, {"total_calories": float(kcal_match.group(1))})
        return f"✅ #{item_id} 熱量已更新為 {kcal_match.group(1)}kcal"

    return "不確定要改什麼。\n支援：餐別（早餐/午餐/晚餐/點心）或熱量（如 180kcal）"


async def handle_image_message(
    message_id: str,
    blob_api: AsyncMessagingApiBlob,
    user_id: str = "default",
) -> str | LineTextMessage:
    """Handle incoming image messages — classify and route.

    If user is in an active /吃 session (awaiting_food), route the image
    directly into the meal flow instead of using the old silent-save path.
    """
    from app.ai.image_analyzer import analyze_food_photo, analyze_nutrition_label

    response = await blob_api.get_message_content(message_id)
    image_bytes = response

    # Check for active session
    session = get_session(user_id)

    # Check for body photo session
    if session and session["mode"] == "awaiting_body_photo":
        from app.line.commands.body import handle_body_photo
        return await handle_body_photo(image_bytes, user_id)

    in_meal_flow = session and session["mode"] == "awaiting_food"

    if in_meal_flow:
        draft = session.get("draft", {})
        meal_type_display = draft.get("meal_type_display", "")
        img_type = await classify_image(image_bytes)

        if img_type == "nutrition_label":
            parsed = await analyze_nutrition_label(image_bytes)
            draft_data = {**draft, **{
                "foods": [{"name": parsed.get("product_name", "食品"),
                           "portion": parsed.get("serving_size", "1份"),
                           "calories": parsed.get("calories_per_serving", 0),
                           "protein": parsed.get("protein_per_serving", 0),
                           "carbs": parsed.get("carbs_per_serving", 0),
                           "fat": parsed.get("fat_per_serving", 0)}],
                "total_calories": parsed.get("calories_per_serving", 0),
                "total_protein": parsed.get("protein_per_serving", 0),
                "total_carbs": parsed.get("carbs_per_serving", 0),
                "total_fat": parsed.get("fat_per_serving", 0),
            }}
        else:
            # food photo or unknown — treat as food
            parsed = await analyze_food_photo(image_bytes)
            draft_data = {**draft, **{
                "foods": parsed.get("foods", []),
                "total_calories": parsed.get("total_calories", 0),
                "total_protein": parsed.get("total_protein", 0),
                "total_carbs": parsed.get("total_carbs", 0),
                "total_fat": parsed.get("total_fat", 0),
            }}

        from app.line.commands.meal import _build_meal_confirm_card
        set_session(user_id, mode="awaiting_meal_confirm", draft=draft_data)
        return _build_meal_confirm_card(draft_data, meal_type_display)

    # Not in meal flow — classify and route as before
    img_type = await classify_image(image_bytes)
    logger.info("Image classified as: %s", img_type)

    if img_type == "food":
        return await _handle_food_image(image_bytes)
    elif img_type == "body_data":
        from app.line.commands.body import handle_body_photo
        return await handle_body_photo(image_bytes, user_id)
    elif img_type == "nutrition_label":
        return await _handle_nutrition_label_image(image_bytes)
    else:
        return await _handle_food_image(image_bytes)


async def _handle_food_image(image_bytes: bytes) -> str:
    """Analyze food photo and save to meals."""
    result = await analyze_food_photo(image_bytes)
    meal_type = result.get("meal_type", "other") or "other"

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
            meal_type=meal_type,
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
            # Food names with IDs for modification
            lines.append(f"{label} {mt_cal:.0f}kcal")
            for m in mt_meals:
                foods = m.get("food_items", [])
                food_names = ", ".join(f.get("name", "?") for f in foods) if foods else "?"
                lines.append(f"  #{m['id']} {food_names}")
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
            lines.append(f"\n💪 #{w['id']} {wtype}{cal_str}")
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

            # Check for rest day FIRST (overrides other plans)
            if any(k in plan_text for k in ["休息日", "休息", "不運動", "沒有能量"]):
                exercise_estimate = 0
                exercise_label = "休息日"
            elif any(k in plan_text for k in ["羽球", "有氧", "跑步", "游泳", "打球"]):
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

    # --- Protein warning: only when below lower bound ---
    warnings = []
    if total_cal > 0:
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
