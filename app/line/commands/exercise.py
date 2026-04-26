"""
/動 command — exercise logging flow.

Flow (like /吃):
  1. /動                 → quick-reply [羽球][重訓][游泳][跑步][其他]
  2. Tap type            → mode=awaiting_exercise_input, prompt for photo/text
  3. Photo or text       → AI parses duration + kcal → confirm card
                           (重訓 branches to awaiting_exercise_list for menu)

Shortcut still works: /動 羽球 2小時 skips step 1-2.

After saving, bot prompts for notes (one message, skippable).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re

from linebot.v3.messaging import MessageAction, QuickReply, QuickReplyItem, TextMessage

from app.db import queries as db
from app.line.confirm import (
    CONFIRM_SENTINEL, CANCEL_SENTINEL, NOTES_SKIP_SENTINEL,
    EXERCISE_SENTINELS, EXERCISE_TYPE_MAP,
    build_confirm_card, build_quick_reply_prompt,
)
from app.line.session import clear_session, set_session

logger = logging.getLogger(__name__)

# Keywords that indicate weight/resistance training
WEIGHT_TRAINING_KEYWORDS = ("重訓", "上半身", "臀腿", "核心", "全身", "健身", "啞鈴", "硬舉", "深蹲")


def _is_weight_training(description: str) -> bool:
    return any(kw in description for kw in WEIGHT_TRAINING_KEYWORDS)


def _estimate_cardio_calories(description: str) -> int:
    """Rough calorie estimate for cardio based on duration found in description."""
    minutes = 60  # default
    match = re.search(r"(\d+)\s*分鐘", description)
    if match:
        minutes = int(match.group(1))
    match_h = re.search(r"(\d+)\s*小時", description)
    if match_h:
        minutes = int(match_h.group(1)) * 60

    rates = {"游泳": 7, "羽球": 6, "跑步": 8, "騎車": 5}
    for sport, rate in rates.items():
        if sport in description:
            return minutes * rate
    return minutes * 5  # default


async def start_exercise_flow(args: str, user_id: str) -> str | TextMessage:
    """Entry point for /動.

    /動 alone         → show type quick reply
    /動 [description] → go straight into parsing (backward-compat shortcut)
    """
    if not args:
        set_session(user_id, mode="awaiting_exercise_type")
        return build_quick_reply_prompt(
            text="做什麼運動？",
            options=[(label, sentinel) for label, sentinel in EXERCISE_SENTINELS.items()],
        )

    if _is_weight_training(args):
        set_session(user_id, mode="awaiting_exercise_list", draft={"workout_type": args, "exercises": []})
        return f"💪 {args}\n練完後把菜單貼過來，格式隨意：\n例：硬舉 36kg 10x4\n   肩推 4kg 12x3"

    estimated_kcal = _estimate_cardio_calories(args)
    draft = {
        "workout_type": args,
        "exercises": [],
        "duration_min": None,
        "estimated_calories": estimated_kcal,
    }
    set_session(user_id, mode="awaiting_exercise_confirm", draft=draft)
    return build_confirm_card(
        title=f"🏃 {args}草稿",
        lines=[f"預估消耗：~{estimated_kcal}kcal"],
        total="確認儲存嗎？",
    )


async def handle_exercise_type_selection(text: str, user_id: str) -> str | TextMessage:
    """User tapped a type button (__ex_badminton__ etc.)."""
    if text not in EXERCISE_TYPE_MAP:
        return build_quick_reply_prompt(
            text="請點選下方的運動類型按鈕 👇",
            options=[(label, sentinel) for label, sentinel in EXERCISE_SENTINELS.items()],
        )

    workout_type = EXERCISE_TYPE_MAP[text]

    # 重訓 branches into the menu-list flow
    if workout_type == "重訓":
        set_session(
            user_id,
            mode="awaiting_exercise_list",
            draft={"workout_type": workout_type, "exercises": []},
        )
        return (
            "💪 重訓\n"
            "練完後把菜單貼過來，格式隨意：\n"
            "例：硬舉 36kg 10x4\n"
            "   肩推 4kg 12x3"
        )

    # Cardio types wait for photo or free-text
    set_session(
        user_id,
        mode="awaiting_exercise_input",
        draft={"workout_type": workout_type, "exercises": []},
    )
    return (
        f"🏃 {workout_type}\n"
        "傳 Apple Watch 截圖，或告訴我時長／消耗 👇\n"
        "例：2小時 650kcal"
    )


async def handle_exercise_text_input(text: str, draft: dict, user_id: str) -> TextMessage:
    """Parse a free-text input for a cardio-type exercise and build confirm card."""
    workout_type = draft.get("workout_type", "運動")

    # Try to extract explicit kcal first (user-provided overrides estimate)
    kcal_match = re.search(r"(\d+)\s*k?cal", text, re.IGNORECASE)
    if kcal_match:
        estimated_kcal = int(kcal_match.group(1))
    else:
        estimated_kcal = _estimate_cardio_calories(f"{workout_type} {text}")

    # Extract duration
    duration_min = None
    m = re.search(r"(\d+)\s*分鐘", text)
    if m:
        duration_min = int(m.group(1))
    mh = re.search(r"(\d+(?:\.\d+)?)\s*小時", text)
    if mh:
        duration_min = int(float(mh.group(1)) * 60)

    new_draft = {
        **draft,
        "duration_min": duration_min,
        "estimated_calories": estimated_kcal,
        "raw_input": text,
    }
    set_session(user_id, mode="awaiting_exercise_confirm", draft=new_draft)

    lines = []
    if duration_min:
        lines.append(f"時長：{duration_min} 分鐘")
    lines.append(f"消耗：~{estimated_kcal}kcal")

    return build_confirm_card(
        title=f"🏃 {workout_type}草稿",
        lines=lines,
        total="確認儲存嗎？",
    )


async def handle_exercise_photo_input(image_bytes: bytes, draft: dict, user_id: str) -> TextMessage:
    """Parse a workout screenshot and build confirm card."""
    from app.ai.image_analyzer import analyze_workout_photo

    workout_type = draft.get("workout_type", "運動")
    parsed = await analyze_workout_photo(image_bytes, workout_type=workout_type)

    if "error" in parsed:
        return build_confirm_card(
            title=f"🏃 {workout_type}草稿",
            lines=["（無法從圖片辨識數據，請改用文字輸入）"],
            total="取消後重試，或直接確認以 0kcal 記錄？",
        )

    duration_min = parsed.get("duration_min")
    estimated_kcal = parsed.get("estimated_calories") or 0
    notes = parsed.get("notes")

    new_draft = {
        **draft,
        "duration_min": duration_min,
        "estimated_calories": estimated_kcal,
        "photo_notes": notes,
    }
    set_session(user_id, mode="awaiting_exercise_confirm", draft=new_draft)

    lines = []
    if duration_min:
        lines.append(f"時長：{duration_min} 分鐘")
    if estimated_kcal:
        lines.append(f"消耗：{estimated_kcal}kcal")
    if parsed.get("avg_heart_rate"):
        lines.append(f"平均心率：{parsed['avg_heart_rate']}bpm")
    if notes:
        lines.append(f"📝 {notes}")

    return build_confirm_card(
        title=f"🏃 {workout_type}草稿",
        lines=lines if lines else ["（未辨識到數據）"],
        total="確認儲存嗎？",
    )


async def handle_exercise_list_input(text: str, draft: dict, user_id: str) -> TextMessage:
    """Parse exercise list text and build confirm card."""
    parsed_exercises = await _parse_exercise_list(text, draft.get("workout_type", ""))
    new_draft = {**draft, "exercises": parsed_exercises}
    set_session(user_id, mode="awaiting_exercise_confirm", draft=new_draft)

    lines = []
    for e in parsed_exercises:
        name = e.get("name", "?")
        w = e.get("weight_kg")
        weight_str = f" {w}kg" if w else ""
        reps = e.get("reps", "")
        sets = e.get("sets", "")
        lines.append(f"• {name}{weight_str} {reps}下x{sets}組")

    return build_confirm_card(
        title=f"💪 {draft.get('workout_type', '重訓')}草稿",
        lines=lines if lines else ["（解析失敗，請重新貼上）"],
        total="Apple Watch 卡路里今晚自動同步",
    )


async def handle_exercise_confirm(draft: dict, user_id: str) -> str | TextMessage:
    """Save confirmed exercise to DB and prompt for notes."""
    try:
        db.insert_workout(
            workout_type=draft.get("workout_type", ""),
            exercises=draft.get("exercises", []),
            duration_min=draft.get("duration_min"),
            estimated_calories=draft.get("estimated_calories"),
            notes=draft.get("photo_notes"),
        )
        clear_session(user_id)
        # Prompt for notes — skippable
        set_session(user_id, mode="awaiting_notes", draft=draft)
        return TextMessage(
            text="✅ 已儲存！\n這次感覺怎樣？有什麼想記下來的？\n（直接跳過也可以）",
            quick_reply=QuickReply(items=[
                QuickReplyItem(action=MessageAction(label="跳過", text=NOTES_SKIP_SENTINEL)),
            ]),
        )
    except Exception:
        logger.exception("Failed to save workout")
        return "儲存失敗，請再試一次 🙏"


async def handle_notes_input(notes_text: str, draft: dict, user_id: str) -> str:
    """Save post-workout notes to the most recently inserted workout."""
    from app.line.commands.meal import _today_intake_summary
    try:
        from app.config import today_tw
        workouts_today = db.get_workouts_for_date(today_tw())
        if workouts_today:
            latest_id = workouts_today[-1]["id"]
            existing_notes = workouts_today[-1].get("notes") or ""
            combined = f"{existing_notes}\n{notes_text}".strip() if existing_notes else notes_text
            db.update_workout(latest_id, {"notes": combined})
        clear_session(user_id)
        return f"📝 備註已記下。下次練這個部位前用 /下次 就會提醒你！\n\n{_today_intake_summary()}"
    except Exception:
        logger.exception("Failed to save workout notes")
        clear_session(user_id)
        return "備註儲存失敗，但運動紀錄已儲存 ✅"


async def handle_notes_skip(user_id: str) -> str:
    """User chose to skip notes — clear session and show today's summary."""
    from app.line.commands.meal import _today_intake_summary
    clear_session(user_id)
    return f"好，這次不記備註。\n\n{_today_intake_summary()}"


async def _parse_exercise_list(text: str, workout_type: str) -> list[dict]:
    """Use AI to parse a free-text exercise list into structured data."""
    from google import genai
    from google.genai import types
    from app.config import GEMINI_API_KEY

    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = f"""\
解析以下重訓紀錄，轉成 JSON 陣列（不要 markdown）：

{text}

格式（每個動作）：
[{{"name": "動作名稱", "weight_kg": 數字或null, "reps": 數字或null, "sets": 數字或null, "notes": "備註或null"}}]

直接輸出 JSON 陣列。
"""
    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.1),
        )
        raw = response.text.strip().strip("```json").strip("```").strip()
        return json.loads(raw)
    except Exception:
        logger.exception("Failed to parse exercise list")
        return []
