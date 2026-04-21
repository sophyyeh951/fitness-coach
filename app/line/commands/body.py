"""
/身體 command — PICOOC body composition photo flow.
"""

from __future__ import annotations
import logging
from linebot.v3.messaging import TextMessage
from app.ai.image_analyzer import analyze_body_data, format_body_data
from app.db import queries as db
from app.config import today_tw
from app.line.confirm import build_confirm_card
from app.line.session import set_session, clear_session

logger = logging.getLogger(__name__)


async def start_body_flow(user_id: str) -> str:
    """Entry point for /身體 — ask user to send the PICOOC screenshot."""
    set_session(user_id, mode="awaiting_body_photo")
    return "⚖️ 請傳送 PICOOC 截圖 👇"


async def handle_body_photo(image_bytes: bytes, user_id: str) -> TextMessage | str:
    """Parse PICOOC screenshot and show confirm card."""
    result = await analyze_body_data(image_bytes)

    if "error" in result:
        clear_session(user_id)
        return format_body_data(result)

    draft = {
        "weight": result.get("weight"),
        "body_fat_pct": result.get("body_fat_pct"),
        "muscle_pct": result.get("muscle_pct"),
        "date": result.get("measurement_date") or today_tw().isoformat(),
    }
    set_session(user_id, mode="awaiting_body_confirm", draft=draft)

    lines = []
    weight = draft["weight"]
    bf = draft["body_fat_pct"]
    mp = draft["muscle_pct"]
    if weight: lines.append(f"• 體重：{weight} kg")
    if bf is not None:
        fat_mass = weight * bf / 100 if weight else None
        tail = f"（脂肪 {fat_mass:.1f} kg）" if fat_mass else ""
        lines.append(f"• 體脂率：{bf}%{tail}")
    if mp is not None:
        muscle_mass = weight * mp / 100 if weight else None
        tail = f"（肌肉 {muscle_mass:.1f} kg）" if muscle_mass else ""
        lines.append(f"• 肌肉率：{mp}%{tail}")

    return build_confirm_card(
        title=f"⚖️ 身體數據草稿（{draft['date']}）",
        lines=lines,
        total="確認儲存嗎？",
    )


async def handle_body_confirm(draft: dict, user_id: str) -> str:
    """Save confirmed body metrics to DB."""
    try:
        metrics = {k: v for k, v in draft.items() if v is not None}
        db.upsert_body_metrics(metrics)
        clear_session(user_id)
        return f"✅ 身體數據已儲存！體重 {draft.get('weight', '?')}kg，體脂 {draft.get('body_fat_pct', '?')}%"
    except Exception:
        logger.exception("Failed to save body metrics")
        return "儲存失敗，請再試一次 🙏"
