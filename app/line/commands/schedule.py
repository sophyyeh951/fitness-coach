"""
/計畫 — view or update weekly exercise schedule.
"""

from __future__ import annotations
from app.db.schedule import get_schedule, set_schedule, WEEKDAY_CN, WEEKDAY_KEYS


async def handle_schedule(args: str, user_id: str) -> str:
    if not args:
        return _format_schedule()
    return await _update_schedule_from_text(args)


def _format_schedule() -> str:
    schedule = get_schedule()
    if not schedule:
        return "尚未設定週計畫。\n說明：/計畫 週四改成游泳"

    default = schedule.get("default", {})
    lines = ["📅 你的週計畫\n"]
    for key in WEEKDAY_KEYS:
        lines.append(f"  {WEEKDAY_CN[key]}　{default.get(key, '未設定')}")

    overrides = schedule.get("overrides", [])
    if overrides:
        lines.append("\n調整期間：")
        for o in overrides:
            changes = {k: v for k, v in o.items() if k not in ("from", "to")}
            for day_key, activity in changes.items():
                lines.append(f"  {o['from']}–{o['to']}：{WEEKDAY_CN.get(day_key, day_key)} → {activity}")

    lines.append("\n修改範例：/計畫 五月之後週四改成游泳")
    return "\n".join(lines)


async def _update_schedule_from_text(text: str) -> str:
    """Use AI to parse a natural language schedule change and apply it."""
    import asyncio
    import json
    import logging
    from google import genai
    from google.genai import types
    from app.config import GEMINI_API_KEY

    logger = logging.getLogger(__name__)
    client = genai.Client(api_key=GEMINI_API_KEY)
    current = get_schedule()

    prompt = f"""\
目前週計畫：
{json.dumps(current, ensure_ascii=False)}

用戶要修改：「{text}」

請輸出修改後的完整週計畫 JSON（同樣格式，不要 markdown）。
weekday key 用英文小寫（monday/tuesday/wednesday/thursday/friday/saturday/sunday）。
"""
    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.1),
        )
        raw = response.text.strip().strip("```json").strip("```").strip()
        new_schedule = json.loads(raw)
        set_schedule(new_schedule)
        return "✅ 週計畫已更新！\n" + _format_schedule()
    except Exception:
        logger.exception("Failed to update schedule")
        return "更新失敗，請再試一次。\n或用 /計畫 查看目前計畫。"
