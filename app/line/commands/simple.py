"""Simple single-turn commands: /休息, /?"""

from __future__ import annotations
import logging
from app.db import queries as db

logger = logging.getLogger(__name__)

HELP_TEXT = """\
📋 小健指令表
──────────────
/吃        記錄飲食（照片/文字/標籤）
/動        記錄運動（照片/文字）
           例：/動 游泳 45分鐘
           或直接輸入 /動 選類型 + 傳 Apple Watch 截圖
/身體      上傳 PICOOC 截圖
/休息      記錄休息日  例：/休息 健檢
/今日      查看今日紀錄 + 可刪除/修改
/下次      下次訓練建議  例：/下次 上半身
/計畫      查看或修改週計畫
/週報      近7天總結（週日20:00自動發送）
/?         顯示這張指令表
──────────────
Apple Watch 數據每天自動同步，無需手動傳"""


async def handle_rest(reason: str, user_id: str) -> str:
    """Log a rest day immediately (no confirm needed — low stakes)."""
    from app.line.commands.meal import _today_intake_summary

    notes = f"休息日{f'：{reason}' if reason else ''}"
    try:
        db.insert_workout(
            workout_type="休息",
            exercises=[],
            duration_min=None,
            estimated_calories=0,
            notes=notes,
        )
        head = f"✅ 已記錄今天是休息日。{f'（{reason}）' if reason else ''}\n好好恢復！"
        return f"{head}\n\n{_today_intake_summary()}"
    except Exception:
        logger.exception("Failed to save rest day")
        return "休息日記錄失敗 🙏"


async def handle_help() -> str:
    return HELP_TEXT
