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
    MEAL_SENTINELS, NOTES_SKIP_SENTINEL, EXERCISE_SKIP_MENU_SENTINEL,
)

logger = logging.getLogger(__name__)


async def handle_text_message(text: str, user_id: str = "default") -> str | LineTextMessage:
    """Handle incoming text messages from LINE.

    Returns either a plain str (for Q&A replies) or a LineTextMessage
    (for confirm cards / quick-reply prompts). webhook.py handles both.
    """
    text = text.strip()

    # 1. Slash commands override any active session — always restart flow.
    # Otherwise, typing /動 while a prior /動 session is stuck in
    # awaiting_exercise_type would route to the session handler, not restart.
    if text.startswith("/"):
        clear_session(user_id)
        return await _handle_command(text, user_id)

    # 2. Session continuation — multi-turn flow
    session = get_session(user_id)
    if session:
        return await _handle_session(text, session, user_id)

    # 3. Morning plan confirmation → calorie tip
    plan_reply = _morning_plan_reply(text)
    if plan_reply:
        return plan_reply

    # 4. Q&A only — NEVER logs anything
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
        handle_exercise_text_input,
        handle_exercise_type_selection,
        handle_muscle_group_selection,
        handle_notes_input,
        handle_notes_skip,
        handle_strength_skip_menu,
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
    if mode == "awaiting_exercise_type":
        return await handle_exercise_type_selection(text, user_id)
    if mode == "awaiting_muscle_group":
        if text == CANCEL_SENTINEL:
            clear_session(user_id)
            return "已取消，沒有儲存任何資料。"
        return await handle_muscle_group_selection(text, user_id)
    if mode == "awaiting_exercise_input":
        return await handle_exercise_text_input(text, draft, user_id)
    if mode == "awaiting_exercise_list":
        if text == EXERCISE_SKIP_MENU_SENTINEL:
            return await handle_strength_skip_menu(draft, user_id)
        if text == CANCEL_SENTINEL:
            clear_session(user_id)
            return "已取消，沒有儲存任何資料。"
        return await handle_exercise_list_input(text, draft, user_id)
    if mode == "awaiting_exercise_confirm":
        if text == CONFIRM_SENTINEL:
            return await handle_exercise_confirm(draft, user_id)
        if text == CANCEL_SENTINEL:
            clear_session(user_id)
            return "已取消，沒有儲存任何資料。"
        if text == EDIT_SENTINEL:
            return "好，告訴我要改什麼？"
        # Re-parse correction: cardio goes through text handler, strength through list handler
        from app.line.commands.exercise import _is_weight_training
        if draft.get("exercises") or _is_weight_training(draft.get("workout_type", "")):
            return await handle_exercise_list_input(text, draft, user_id)
        return await handle_exercise_text_input(text, draft, user_id)

    # Notes prompt
    if mode == "awaiting_notes":
        if text == NOTES_SKIP_SENTINEL:
            return await handle_notes_skip(user_id)
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


def _morning_plan_reply(text: str) -> str | None:
    """If text looks like a morning exercise plan confirmation, return a calorie tip.

    The morning check-in quick-reply buttons send text like:
      "今天羽球"  "今天重訓"  "今天游泳"  "今天換運動"
    We intercept these to give the user a personalised calorie target.
    """
    if not text.startswith("今天"):
        return None

    from app.line.commands.today import (
        BASE_TDEE, DAILY_DEFICIT, PROTEIN_MIN, PROTEIN_IDEAL, calc_intake_target,
    )

    t = text
    if any(k in t for k in ["羽球", "打球"]):
        active, label = 550, "羽球"
    elif any(k in t for k in ["游泳"]):
        active, label = 500, "游泳"
    elif any(k in t for k in ["跑步", "有氧"]):
        active, label = 500, "有氧"
    elif any(k in t for k in ["重訓", "訓練", "健身", "上半身", "臀腿", "胸", "背", "肩"]):
        active, label = 300, "重訓"
    elif any(k in t for k in ["休息", "不運動"]):
        active, label = 0, "休息"
    else:
        return None  # not a plan keyword — let Q&A handle it

    total_burn = BASE_TDEE + active
    target_intake = calc_intake_target(total_burn)

    lines = [
        f"👍 {label}日加油！",
        f"預估消耗 {total_burn}kcal（基底{BASE_TDEE} + {label}~{active}）",
        f"→ 建議攝取約 {target_intake:.0f}kcal（赤字 {DAILY_DEFICIT}）",
        f"蛋白質 {PROTEIN_MIN}–{PROTEIN_IDEAL}g 💪",
    ]
    return "\n".join(lines)


async def _handle_delete(args: str) -> str:
    """Delete a meal or workout by ID.

    Usage:
      /刪 37        — 刪飲食 #37
      /刪 動 46     — 刪運動 #46
      /刪 吃 37     — 刪飲食 #37（明確指定）
    """
    parts = args.split()
    if not parts:
        return "格式：/刪 [ID] 或 /刪 動 [ID]\n例：/刪 37  ／  /刪 動 46"

    # Type-prefixed form: /刪 動 46 or /刪 吃 37
    if len(parts) == 2 and parts[1].isdigit():
        kind, id_str = parts
        item_id = int(id_str)
        if kind in ("動", "運動", "workout"):
            ok = db.delete_workout(item_id)
            return f"✅ 運動 #{item_id} 已刪除" if ok else f"找不到運動 #{item_id}"
        if kind in ("吃", "飲食", "meal"):
            ok = db.delete_meal(item_id)
            return f"✅ 飲食 #{item_id} 已刪除" if ok else f"找不到飲食 #{item_id}"
        return "格式：/刪 動 [ID] 或 /刪 吃 [ID]"

    # Bare ID — try meal first, then workout (legacy behaviour)
    if len(parts) == 1 and parts[0].isdigit():
        item_id = int(parts[0])
        if db.delete_meal(item_id):
            return f"✅ 飲食 #{item_id} 已刪除\n（如果你要刪的是運動，用 /刪 動 {item_id}）"
        if db.delete_workout(item_id):
            return f"✅ 運動 #{item_id} 已刪除"
        return f"找不到 #{item_id}，請用 /今日 確認 ID"

    return "格式：/刪 [ID] 或 /刪 動 [ID]\n例：/刪 37  ／  /刪 動 46"


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

    # Check for exercise photo session (awaiting Apple Watch screenshot etc.)
    if session and session["mode"] == "awaiting_exercise_input":
        from app.line.commands.exercise import handle_exercise_photo_input
        return await handle_exercise_photo_input(image_bytes, session.get("draft", {}), user_id)

    # 重訓 menu phase: Apple Watch screenshot supplements the menu
    if session and session["mode"] == "awaiting_exercise_list":
        from app.line.commands.exercise import handle_strength_photo_input
        return await handle_strength_photo_input(image_bytes, session.get("draft", {}), user_id)

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
        metrics["muscle_pct"] = result["muscle_pct"]
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
