"""
/下次 [部位 / 運動] — suggest next session based on the most recent matching session.

Strength examples (uses muscle_group column for precise match):
  /下次 胸肩    → 最近一筆 胸肩
  /下次 背      → 最近一筆 背
  /下次 臀腿    → 最近一筆 臀腿
  /下次 上半身  → 胸肩 與 背 中最新的一筆
  /下次 下半身  → 等同 臀腿

Cardio examples (falls back to workout_type 模糊匹配):
  /下次 游泳 / 羽球 / 跑步
"""

from __future__ import annotations
import asyncio
import logging
from app.db import queries as db
from app.config import GEMINI_API_KEY

logger = logging.getLogger(__name__)


# Map free-text input → list of muscle_group values to query.
# Must match MUSCLE_GROUP_SENTINELS canonical names in app/line/confirm.py.
MUSCLE_GROUP_ALIASES: dict[str, list[str]] = {
    "胸肩": ["胸肩"],
    "背": ["背"],
    "臀腿": ["臀腿"],
    "其他": ["其他"],
    "上半身": ["胸肩", "背"],
    "下半身": ["臀腿"],
    "腿": ["臀腿"],
    "胸": ["胸肩"],
    "肩": ["胸肩"],
}


def _pick_latest_by_muscle_groups(groups: list[str]) -> dict | None:
    """Return the most recent workout among the given muscle_group values."""
    candidates = []
    for g in groups:
        try:
            row = db.get_last_workout_by_muscle_group(g)
        except Exception:
            logger.exception("get_last_workout_by_muscle_group failed for %s", g)
            row = None
        if row:
            candidates.append(row)
    if not candidates:
        return None
    return max(candidates, key=lambda r: r.get("created_at") or "")


async def handle_next_session(args: str) -> str:
    if not args:
        return (
            "請告訴我要練哪個部位\n"
            "例：/下次 胸肩\n"
            "   /下次 背\n"
            "   /下次 臀腿\n"
            "   /下次 游泳"
        )

    keyword = args.strip()

    # 1) Strength — look up by muscle_group column (precise).
    if keyword in MUSCLE_GROUP_ALIASES:
        last = _pick_latest_by_muscle_groups(MUSCLE_GROUP_ALIASES[keyword])
        if not last:
            return (
                f"還沒有「{keyword}」的訓練紀錄。\n"
                f"先用 /動 → 重訓 → 選部位記一次吧！"
            )
        display_label = keyword
        return await _build_suggestion(last, display_label)

    # 2) Cardio / free-text — fall back to workout_type 模糊匹配.
    recent = db.get_workouts_by_type(keyword, limit=2)
    if not recent:
        return f"找不到「{keyword}」的訓練紀錄。先用 /動 {keyword} 記一次吧！"
    return await _build_suggestion(recent[0], keyword)


async def _build_suggestion(last: dict, display_label: str) -> str:
    last_date = (last.get("created_at") or "")[:10]
    exercises = last.get("exercises") or []
    notes = last.get("notes") or "無備註"

    exercise_summary = "\n".join(
        f"  • {e.get('name', '?')} {e.get('weight_kg', '')}kg "
        f"{e.get('reps', '')}下x{e.get('sets', '')}組"
        for e in exercises if e.get("name")
    ) or "  （無詳細動作紀錄）"

    prompt = f"""\
你是健身教練小健。根據用戶上次「{display_label}」訓練，給這次的具體建議。

上次訓練（{last_date}）：
{exercise_summary}

上次備註：{notes}

請給出：
1. 這次每個動作的具體重量/次數/組數建議（沿用或微調，不要憑空換動作）
2. 需要特別注意的地方（根據備註）
3. 最多一句總結

格式：純文字，用 • 列點，不要 markdown，不超過 15 行。
"""
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.5),
        )
        return f"📋 下次{display_label}建議（根據 {last_date}）\n\n{response.text.strip()}"
    except Exception:
        logger.exception("Failed to generate next session suggestion")
        return f"上次{display_label}（{last_date}）：\n{exercise_summary}\n備註：{notes}"
