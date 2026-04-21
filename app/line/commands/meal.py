"""
/吃 command — multi-turn meal logging flow.

Flow:
  1. User sends /吃
     → set_session(mode=awaiting_meal_type)
     → bot sends meal type quick reply [早餐][午餐][晚餐][點心]

  2. User taps a meal type button (e.g. __meal_lunch__)
     → set_session(mode=awaiting_food, draft={meal_type: lunch})
     → bot asks for food

  3. User sends text description
     → AI parses food → build draft
     → set_session(mode=awaiting_meal_confirm, draft={...})
     → bot sends confirm card

  4a. User taps ✅  → save to DB, clear session
  4b. User taps ❌  → clear session, nothing saved (handled in handlers.py)
  4c. User sends correction text → AI re-parses → update draft → show new confirm card
"""

from __future__ import annotations

import json
import logging

from linebot.v3.messaging import TextMessage

from app.db import queries as db
from app.line.confirm import (
    MEAL_SENTINELS, MEAL_TYPE_DB, MEAL_TYPE_MAP,
    build_confirm_card, build_quick_reply_prompt,
)
from app.line.session import clear_session, get_session, set_session
from app.ai.food_analyzer import parse_food_text

logger = logging.getLogger(__name__)


async def start_meal_flow(user_id: str) -> TextMessage:
    """Entry point for /吃 — sets session and asks for meal type."""
    set_session(user_id, mode="awaiting_meal_type")
    return build_quick_reply_prompt(
        text="這餐是？",
        options=[(label, sentinel) for label, sentinel in MEAL_SENTINELS.items()],
    )


async def handle_meal_type_selection(text: str, user_id: str) -> str | TextMessage:
    """Handle meal type button tap (e.g. __meal_lunch__)."""
    if text not in MEAL_TYPE_DB:
        return "請點選下方的餐別按鈕 👇"

    db_type = MEAL_TYPE_DB[text]
    display = MEAL_TYPE_MAP[text]
    set_session(user_id, mode="awaiting_food", draft={
        "meal_type": db_type,
        "meal_type_display": display,
    })
    return f"好，{display}。\n傳照片或告訴我吃什麼 👇"


async def handle_food_input(text: str, draft: dict, user_id: str) -> TextMessage:
    """Parse food text and build the confirm card draft."""
    display = draft.get("meal_type_display", "")
    parsed = await parse_food_text(text)
    new_draft = {**draft, **parsed}
    set_session(user_id, mode="awaiting_meal_confirm", draft=new_draft)
    return _build_meal_confirm_card(new_draft, display)


async def handle_meal_correction(correction: str, draft: dict, user_id: str) -> TextMessage:
    """Apply a user correction to the existing draft and rebuild the confirm card."""
    display = draft.get("meal_type_display", "")
    correction_prompt = (
        f"目前的飲食草稿：\n{json.dumps(draft, ensure_ascii=False)}\n\n"
        f"用戶說要修改：「{correction}」\n\n"
        f"請根據修改重新輸出完整的 JSON（同樣格式，不要 markdown）"
    )
    parsed = await parse_food_text(correction_prompt, is_correction=True)
    new_draft = {**draft, **parsed}
    set_session(user_id, mode="awaiting_meal_confirm", draft=new_draft)
    return _build_meal_confirm_card(new_draft, display, updated=True)


async def handle_meal_confirm(draft: dict, user_id: str) -> str:
    """Save confirmed draft to database, then show today's running totals."""
    try:
        db.insert_meal(
            photo_url=None,
            food_items=draft.get("foods", []),
            total_calories=draft.get("total_calories", 0),
            protein=draft.get("total_protein", 0),
            carbs=draft.get("total_carbs", 0),
            fat=draft.get("total_fat", 0),
            ai_response="",
            source="text",
            meal_type=draft.get("meal_type", "other"),
        )
        clear_session(user_id)
        display = draft.get("meal_type_display", "")
        kcal = draft.get("total_calories", 0)

        # Build today's running totals (including the meal just saved)
        summary = _today_intake_summary()
        return f"✅ {display}已儲存！合計 {kcal:.0f}kcal\n\n{summary}"
    except Exception:
        logger.exception("Failed to save meal")
        return "儲存失敗，請再試一次 🙏"


def _today_intake_summary() -> str:
    """Return a short summary of today's cumulative intake vs. burn estimate."""
    from app.config import today_tw
    from app.db.schedule import get_today_exercise
    from app.line.commands.today import (
        _exercise_estimate, BASE_TDEE, DAILY_DEFICIT,
        calc_intake_target, protein_status_line,
    )

    today = today_tw()
    meals = db.get_meals_for_date(today)
    workouts = db.get_workouts_for_date(today)
    metrics = db.get_body_metrics_range(today, today)

    total_kcal    = sum(m.get("total_calories", 0) or 0 for m in meals)
    total_protein = sum(m.get("protein", 0) or 0 for m in meals)
    total_carbs   = sum(m.get("carbs", 0) or 0 for m in meals)
    total_fat     = sum(m.get("fat", 0) or 0 for m in meals)

    # Burn estimate: Apple Watch > recorded workout > schedule
    actual_active = (metrics[-1].get("active_calories") or 0) if metrics else 0
    if actual_active > 0:
        total_burn = BASE_TDEE + actual_active
        burn_label = f"實際消耗 {total_burn:.0f}kcal"
    else:
        if workouts:
            all_types = " ".join(w.get("workout_type", "") for w in workouts)
            if any(k in all_types for k in ["休息"]):
                ex_est, ex_label = 0, "休息日"
            elif any(k in all_types for k in ["羽球", "打球"]):
                ex_est, ex_label = 550, "羽球"
            elif any(k in all_types for k in ["游泳"]):
                ex_est, ex_label = 500, "游泳"
            elif any(k in all_types for k in ["跑步", "有氧"]):
                ex_est, ex_label = 500, "有氧"
            else:
                ex_est, ex_label = 300, "重訓"
        else:
            planned = get_today_exercise(today)
            ex_est, ex_label = _exercise_estimate(planned)
        total_burn = BASE_TDEE + ex_est
        burn_label = f"預估消耗 {total_burn:.0f}kcal（{ex_label}日）"

    target = calc_intake_target(total_burn)
    remaining = target - total_kcal

    lines = [
        f"📊 今日截至目前",
        f"攝取 {total_kcal:.0f}kcal｜P {total_protein:.0f}g / C {total_carbs:.0f}g / F {total_fat:.0f}g",
        f"🔥 {burn_label}",
        f"🎯 建議攝取 {target:.0f}kcal（赤字 {DAILY_DEFICIT}）",
        f"→ 還可以吃 {remaining:.0f}kcal" if remaining > 0 else f"→ 已超出目標 {abs(remaining):.0f}kcal",
        protein_status_line(total_protein),
    ]

    return "\n".join(lines)


def _build_meal_confirm_card(draft: dict, display: str, updated: bool = False) -> TextMessage:
    """Build the meal confirm card from the draft data."""
    foods = draft.get("foods", [])
    lines = [
        f"• {f['name']} {f.get('portion', '')} {f.get('calories', 0):.0f}kcal"
        for f in foods
    ]
    total_kcal = draft.get("total_calories", 0)
    total_protein = draft.get("total_protein", 0)
    total_carbs = draft.get("total_carbs", 0)
    total_fat = draft.get("total_fat", 0)
    title = f"🍽 {display}草稿{'（已更新）' if updated else ''}"
    total_str = f"合計：{total_kcal:.0f}kcal｜蛋白質 {total_protein:.0f}g｜碳水 {total_carbs:.0f}g｜脂肪 {total_fat:.0f}g"
    return build_confirm_card(title=title, lines=lines, total=total_str)
