"""
/動 command — exercise logging flow.

Usage: /動 [description]
  /動 上半身重訓        → weight training: ask for exercise list
  /動 羽球 2小時        → cardio: instant confirm card
  /動 游泳 45分鐘       → cardio: instant confirm card

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
    build_confirm_card,
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
    """Entry point for /動 [description]."""
    if not args:
        return "請告訴我今天做什麼運動\n例：/動 游泳 45分鐘\n   /動 上半身重訓"

    if _is_weight_training(args):
        set_session(user_id, mode="awaiting_exercise_list", draft={"workout_type": args, "exercises": []})
        return f"💪 {args}\n練完後把菜單貼過來，格式隨意：\n例：硬舉 36kg 10x4\n   肩推 4kg 12x3"
    else:
        # Cardio — build confirm card immediately
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
            lines=[f"預估消耗：~{estimated_kcal}kcal（Apple Watch 今晚自動同步更新）"],
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
            notes=None,
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
    try:
        from app.config import today_tw
        workouts_today = db.get_workouts_for_date(today_tw())
        if workouts_today:
            latest_id = workouts_today[-1]["id"]
            db.update_workout(latest_id, {"notes": notes_text})
        clear_session(user_id)
        return "📝 備註已記下。下次練這個部位前用 /下次 就會提醒你！"
    except Exception:
        logger.exception("Failed to save workout notes")
        clear_session(user_id)
        return "備註儲存失敗，但運動紀錄已儲存 ✅"


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
