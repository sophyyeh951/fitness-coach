"""
/下次 [部位] — suggest next session based on last session of that type.

Examples:
  /下次 上半身   → reads last 上半身 session + notes → specific plan
  /下次 臀腿     → reads last 臀腿 session + notes → specific plan
  /下次 游泳     → reads last 游泳 session → duration/intensity suggestion
"""

from __future__ import annotations
import asyncio
import logging
from app.db import queries as db
from app.config import GEMINI_API_KEY

logger = logging.getLogger(__name__)


async def handle_next_session(args: str) -> str:
    if not args:
        return "請告訴我要練哪個部位\n例：/下次 上半身\n   /下次 臀腿\n   /下次 游泳"

    workout_type = args.strip()
    recent = db.get_workouts_by_type(workout_type, limit=2)

    if not recent:
        return f"找不到「{workout_type}」的訓練紀錄。先用 /動 {workout_type} 記一次吧！"

    last = recent[0]
    last_date = last.get("created_at", "")[:10]
    exercises = last.get("exercises", [])
    notes = last.get("notes") or "無備註"

    exercise_summary = "\n".join(
        f"  • {e.get('name', '?')} {e.get('weight_kg', '')}kg "
        f"{e.get('reps', '')}下x{e.get('sets', '')}組"
        for e in exercises if e.get("name")
    ) or "  （無詳細動作紀錄）"

    prompt = f"""\
你是健身教練小健。根據用戶上次「{workout_type}」訓練，給這次的具體建議。

上次訓練（{last_date}）：
{exercise_summary}

上次備註：{notes}

請給出：
1. 這次每個動作的具體重量/次數/組數建議
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
        return f"📋 下次{workout_type}建議（根據 {last_date}）\n\n{response.text.strip()}"
    except Exception:
        logger.exception("Failed to generate next session suggestion")
        return f"上次{workout_type}（{last_date}）：\n{exercise_summary}\n備註：{notes}"
