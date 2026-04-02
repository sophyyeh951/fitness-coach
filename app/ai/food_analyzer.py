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

MODEL = "gemini-2.0-flash"
MAX_IMAGE_SIZE = (1024, 1024)


def _resize_image(image_bytes: bytes) -> bytes:
    """Resize image to save tokens while keeping enough detail."""
    img = Image.open(BytesIO(image_bytes))
    img.thumbnail(MAX_IMAGE_SIZE, Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


async def analyze_food_photo(image_bytes: bytes) -> dict:
    """
    Analyze a food photo and return nutritional estimates.

    Returns dict with keys: foods, total_calories, total_protein,
    total_carbs, total_fat, brief_comment
    """
    resized = _resize_image(image_bytes)

    response = await client.aio.models.generate_content(
        model=MODEL,
        contents=[
            types.Part.from_text(text=FOOD_ANALYSIS_PROMPT),
            types.Part.from_bytes(data=resized, mime_type="image/jpeg"),
        ],
        config=types.GenerateContentConfig(
            temperature=0.3,
            max_output_tokens=1024,
        ),
    )

    raw_text = response.text.strip()
    # Strip markdown code fences if present
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1]
    if raw_text.endswith("```"):
        raw_text = raw_text.rsplit("```", 1)[0]
    raw_text = raw_text.strip()

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        logger.error("Failed to parse Gemini response as JSON: %s", raw_text)
        return {
            "foods": [],
            "total_calories": 0,
            "total_protein": 0,
            "total_carbs": 0,
            "total_fat": 0,
            "brief_comment": f"辨識結果（非結構化）：{raw_text[:200]}",
        }


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
