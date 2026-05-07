"""Analyze food photos using Gemini Vision API."""

from __future__ import annotations

import json
import logging
from io import BytesIO

from google import genai
from google.genai import types
from PIL import Image

from app.config import GEMINI_API_KEY
from app.ai.prompts import FOOD_ANALYSIS_PROMPT

logger = logging.getLogger(__name__)

client = genai.Client(api_key=GEMINI_API_KEY)

MODEL = "gemini-2.5-flash"
MAX_IMAGE_SIZE = (1024, 1024)


def _resize_image(image_bytes: bytes) -> bytes:
    """Resize image to save tokens while keeping enough detail."""
    with Image.open(BytesIO(image_bytes)) as img:
        img.thumbnail(MAX_IMAGE_SIZE, Image.LANCZOS)
        with BytesIO() as buf:
            img.save(buf, format="JPEG", quality=85)
            return buf.getvalue()


def _empty_meal_with_error(reason: str) -> dict:
    """Empty meal payload tagged with an error so meal.py can show a real message."""
    return {
        "foods": [],
        "total_calories": 0,
        "total_protein": 0,
        "total_carbs": 0,
        "total_fat": 0,
        "_parse_error": reason,
    }


def _strip_code_fences(raw: str) -> str:
    """Remove ```json ... ``` wrappers Gemini sometimes adds despite instructions."""
    raw = raw.strip()
    if raw.startswith("```"):
        # split on first newline to drop opening ```json (or ```)
        parts = raw.split("\n", 1)
        raw = parts[1] if len(parts) > 1 else raw[3:]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    return raw.strip()


async def analyze_food_photo(image_bytes: bytes) -> dict:
    """
    Analyze a food photo and return nutritional estimates.

    Returns dict with keys: foods, total_calories, total_protein,
    total_carbs, total_fat, brief_comment. On parse failure, includes
    `_parse_error` so callers can show a real message instead of silent zeros.
    """
    resized = _resize_image(image_bytes)

    raw_text = ""
    try:
        response = await client.aio.models.generate_content(
            model=MODEL,
            contents=[
                types.Part.from_text(text=FOOD_ANALYSIS_PROMPT),
                types.Part.from_bytes(data=resized, mime_type="image/jpeg"),
            ],
            config=types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=1024,
                response_mime_type="application/json",
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        raw_text = (response.text or "").strip()
        if not raw_text:
            logger.warning("analyze_food_photo: empty response from Gemini")
            return _empty_meal_with_error("AI 沒回覆")
        return json.loads(_strip_code_fences(raw_text))
    except json.JSONDecodeError as e:
        logger.warning("analyze_food_photo: JSON decode failed raw=%r err=%s", raw_text[:300], e)
        return _empty_meal_with_error("AI 看圖回的格式有問題")
    except Exception:
        logger.exception("analyze_food_photo: unexpected error")
        return _empty_meal_with_error("AI 暫時不可用")


async def parse_food_text(text: str, is_correction: bool = False) -> dict:
    """Parse a free-text food description into structured nutrition data.

    Returns dict with keys: foods, total_calories, total_protein, total_carbs, total_fat.
    On failure, includes a `_parse_error` key so the caller can surface a real message
    to the user instead of a silent zero meal.
    """
    import asyncio
    import json
    from google.genai import types

    prompt = f"""\
請把以下飲食描述解析成 JSON：

{text}

格式（純 JSON，不要 markdown 不要解釋文字）：
{{
  "foods": [
    {{"name": "食物名稱", "portion": "份量", "calories": 數字, "protein": 數字, "carbs": 數字, "fat": 數字}}
  ],
  "total_calories": 數字,
  "total_protein": 數字,
  "total_carbs": 數字,
  "total_fat": 數字
}}

注意：
- calories/protein/carbs/fat 一定要是整數或小數，不能是字串或 null
- 即使是飲料、調味料也要估熱量（蜂蜜、糖、鮮奶等）
- 中文食物用常識估算（抹茶拿鐵約 80-150kcal、藍莓 50g 約 30kcal）
"""
    raw = ""
    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                response_mime_type="application/json",  # force clean JSON
            ),
        )
        raw = (response.text or "").strip()
        if not raw:
            logger.warning("parse_food_text: empty response from Gemini for text=%r", text)
            return _empty_meal_with_error("AI 沒回覆")
        cleaned = _strip_code_fences(raw)
        parsed = json.loads(cleaned)
        # sanity check: at least one food with non-zero calories
        foods = parsed.get("foods") or []
        total_cal = parsed.get("total_calories") or 0
        if not foods and total_cal == 0:
            logger.warning("parse_food_text: empty parse for text=%r raw=%r", text, raw[:200])
            return _empty_meal_with_error("AI 看不懂這段描述")
        return parsed
    except json.JSONDecodeError as e:
        logger.warning("parse_food_text: JSON decode failed for text=%r raw=%r err=%s", text, raw[:300], e)
        return _empty_meal_with_error("AI 回的格式有問題")
    except Exception:
        logger.exception("parse_food_text: unexpected error for text=%r", text)
        return _empty_meal_with_error("AI 暫時不可用")


def format_food_analysis(result: dict) -> str:
    """Format the analysis result as a readable LINE message."""
    lines = ["🍽 食物辨識結果\n"]

    for food in result.get("foods", []):
        lines.append(
            f"• {food['name']}（{food.get('portion', '—')}）"
            f"\n  {food.get('calories', '?')} kcal"
            f" ｜蛋白 {food.get('protein', '?')}g"
            f" ｜碳水 {food.get('carbs', '?')}g"
            f" ｜脂肪 {food.get('fat', '?')}g"
        )

    lines.append(
        f"\n📊 合計：{result.get('total_calories', 0)} kcal"
        f"\n蛋白質 {result.get('total_protein', 0)}g"
        f" / 碳水 {result.get('total_carbs', 0)}g"
        f" / 脂肪 {result.get('total_fat', 0)}g"
    )

    comment = result.get("brief_comment")
    if comment:
        lines.append(f"\n💬 {comment}")

    return "\n".join(lines)
