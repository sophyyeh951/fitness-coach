"""Analyze images: food photos, body data screenshots, nutrition labels."""

from __future__ import annotations

import json
import logging
from io import BytesIO

from google import genai
from google.genai import types
from PIL import Image

from app.config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

client = genai.Client(api_key=GEMINI_API_KEY)
MODEL = "gemini-2.5-flash"
MAX_IMAGE_SIZE = (1024, 1024)


# --------------- Prompts ---------------

IMAGE_CLASSIFY_PROMPT = """\
判斷這張圖片的類型，只回覆一個詞：

- food — 食物照片（拍的是實際食物或餐點）
- body_data — 身體數據截圖（體重計報告、體脂計、Apple Watch 活動數據、健康App截圖）
- nutrition_label — 營養標示（食品包裝上的營養成分表）
- unknown — 以上都不是

只回覆一個詞，不要其他文字。
"""

FOOD_ANALYSIS_PROMPT = """\
你是一位專業的營養師。請分析這張食物照片，辨識所有食物並估算營養素。
目前時間：{current_hour} 點。

請用以下 JSON 格式回覆（不要加 markdown code block）：
{{
  "foods": [
    {{
      "name": "食物名稱",
      "portion": "份量描述（如：一碗、一片、約200g）",
      "calories": 數字,
      "protein": 數字（克）,
      "carbs": 數字（克）,
      "fat": 數字（克）
    }}
  ],
  "total_calories": 總熱量數字,
  "total_protein": 總蛋白質數字,
  "total_carbs": 總碳水數字,
  "total_fat": 總脂肪數字,
  "brief_comment": "一句簡短的營養評語",
  "meal_type": "根據時間或照片上的文字標注判斷：breakfast/lunch/dinner/snack"
}}

meal_type 判斷：
- 如果照片上有手寫文字標注（如「午餐」「晚餐」「早餐」），以標注為準
- 否則根據時間：5-10點 breakfast、11-14點 lunch、17-21點 dinner、其他 snack

注意：
- 盡量根據照片中食物的份量來估算
- 如果照片上有手寫的份量標注（如「2份」「300ml」），要參考
- 回覆純 JSON，不要其他文字
"""

BODY_DATA_PROMPT = """\
請從這張身體數據截圖中讀取所有可辨識的數值。

可能包含的數據（有什麼就讀什麼，沒有的填 null）：
- 體重 (kg)
- 體脂率 (%)
- 肌肉率 (%)
- BMI
- 基礎代謝率 (kcal)
- 內臟脂肪指數
- 骨量 (kg)
- 骨骼肌 (%)
- 水分 (%)
- 步數
- 活動消耗卡路里 (kcal)
- 靜息心率 (bpm)

請用以下 JSON 格式回覆（不要加 markdown code block）：
{
  "weight": 數字或null,
  "body_fat_pct": 數字或null,
  "muscle_pct": 數字或null,
  "bmi": 數字或null,
  "bmr": 數字或null,
  "visceral_fat": 數字或null,
  "bone_mass": 數字或null,
  "skeletal_muscle_pct": 數字或null,
  "water_pct": 數字或null,
  "steps": 數字或null,
  "active_calories": 數字或null,
  "resting_heart_rate": 數字或null,
  "source": "資料來源描述（如：PICOOC體脂計、Apple Watch）",
  "measurement_date": "如果圖中有日期就填 YYYY-MM-DD，沒有就填 null。注意：PICOOC 的日期格式是 日/月/年（如 9/4/2026 表示 2026年4月9日，不是9月4日）"
}

回覆純 JSON，不要其他文字。
"""

NUTRITION_LABEL_PROMPT = """\
請讀取這張營養標示的內容。

請用以下 JSON 格式回覆（不要加 markdown code block）：
{
  "product_name": "產品名稱（如果看得到）或null",
  "serving_size": "每份量描述",
  "calories": 每份熱量數字,
  "protein": 每份蛋白質克數,
  "carbs": 每份碳水克數,
  "fat": 每份脂肪克數,
  "sodium_mg": 每份鈉毫克數或null,
  "sugar": 每份糖克數或null,
  "fiber": 每份膳食纖維克數或null,
  "servings_per_package": 每包裝份數或null,
  "brief_comment": "一句簡短的營養評語（對減脂增肌目標）"
}

回覆純 JSON，不要其他文字。
"""


# --------------- Helpers ---------------

def _resize_image(image_bytes: bytes) -> bytes:
    """Resize image to save tokens while keeping enough detail."""
    img = Image.open(BytesIO(image_bytes))
    img.thumbnail(MAX_IMAGE_SIZE, Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _parse_json_response(raw: str) -> dict:
    """Parse JSON from Gemini response, stripping code fences."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    raw = raw.strip()
    return json.loads(raw)


async def _gemini_vision(prompt: str, image_bytes: bytes, max_tokens: int = 1024) -> str:
    """Call Gemini Vision with an image and return raw text."""
    resized = _resize_image(image_bytes)
    response = await client.aio.models.generate_content(
        model=MODEL,
        contents=[
            types.Part.from_text(text=prompt),
            types.Part.from_bytes(data=resized, mime_type="image/jpeg"),
        ],
        config=types.GenerateContentConfig(
            temperature=0.2,
            max_output_tokens=max_tokens,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    return (response.text or "").strip()


# --------------- Public API ---------------

async def classify_image(image_bytes: bytes) -> str:
    """Classify image type: food, body_data, nutrition_label, or unknown."""
    result = await _gemini_vision(IMAGE_CLASSIFY_PROMPT, image_bytes, max_tokens=10)
    result = result.strip().lower()
    if result in ("food", "body_data", "nutrition_label"):
        return result
    return "unknown"


async def analyze_food_photo(image_bytes: bytes) -> dict:
    """Analyze a food photo and return nutritional estimates."""
    from datetime import datetime
    from app.config import TW_TZ
    current_hour = datetime.now(TW_TZ).hour
    prompt = FOOD_ANALYSIS_PROMPT.format(current_hour=current_hour)
    raw = await _gemini_vision(prompt, image_bytes)
    try:
        return _parse_json_response(raw)
    except json.JSONDecodeError:
        logger.error("Failed to parse food JSON: %s", raw[:200])
        return {
            "foods": [],
            "total_calories": 0,
            "total_protein": 0,
            "total_carbs": 0,
            "total_fat": 0,
            "brief_comment": f"辨識結果：{raw[:200]}",
        }


async def analyze_body_data(image_bytes: bytes) -> dict:
    """Extract body metrics from a screenshot (PICOOC, Apple Watch, etc.)."""
    raw = await _gemini_vision(BODY_DATA_PROMPT, image_bytes)
    try:
        return _parse_json_response(raw)
    except json.JSONDecodeError:
        logger.error("Failed to parse body data JSON: %s", raw[:200])
        return {"error": raw[:200]}


async def analyze_nutrition_label(image_bytes: bytes) -> dict:
    """Extract nutritional info from a nutrition label photo."""
    raw = await _gemini_vision(NUTRITION_LABEL_PROMPT, image_bytes)
    try:
        return _parse_json_response(raw)
    except json.JSONDecodeError:
        logger.error("Failed to parse nutrition label JSON: %s", raw[:200])
        return {"error": raw[:200]}


# --------------- Formatters ---------------

def format_food_analysis(result: dict) -> str:
    """Format food analysis as a LINE message."""
    lines = ["🍽 食物辨識結果\n"]

    for food in result.get("foods", []):
        lines.append(
            f"• {food.get('name', '?')}（{food.get('portion', '—')}）"
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


def format_body_data(result: dict) -> str:
    """Format body data as a LINE message."""
    if "error" in result:
        return f"⚠️ 無法辨識數據：{result['error']}"

    lines = ["📏 身體數據已記錄\n"]
    source = result.get("source", "")
    if source:
        lines.append(f"來源：{source}\n")

    field_map = [
        ("weight", "體重", "kg"),
        ("body_fat_pct", "體脂率", "%"),
        ("muscle_pct", "肌肉率", "%"),
        ("bmi", "BMI", ""),
        ("bmr", "基礎代謝", "kcal"),
        ("visceral_fat", "內臟脂肪", ""),
        ("bone_mass", "骨量", "kg"),
        ("skeletal_muscle_pct", "骨骼肌", "%"),
        ("water_pct", "水分", "%"),
        ("steps", "步數", "步"),
        ("active_calories", "活動消耗", "kcal"),
        ("resting_heart_rate", "靜息心率", "bpm"),
    ]

    for key, label, unit in field_map:
        val = result.get(key)
        if val is not None:
            lines.append(f"• {label}：{val}{unit}")

    return "\n".join(lines)


def format_nutrition_label(result: dict) -> str:
    """Format nutrition label as a LINE message."""
    if "error" in result:
        return f"⚠️ 無法辨識營養標示：{result['error']}"

    name = result.get("product_name") or "未知產品"
    serving = result.get("serving_size", "—")
    lines = [f"🏷 營養標示：{name}\n", f"每份量：{serving}\n"]

    cal = result.get("calories")
    if cal is not None:
        lines.append(f"• 熱量：{cal} kcal")
    pro = result.get("protein")
    if pro is not None:
        lines.append(f"• 蛋白質：{pro}g")
    carbs = result.get("carbs")
    if carbs is not None:
        lines.append(f"• 碳水：{carbs}g")
    fat = result.get("fat")
    if fat is not None:
        lines.append(f"• 脂肪：{fat}g")
    sodium = result.get("sodium_mg")
    if sodium is not None:
        lines.append(f"• 鈉：{sodium}mg")
    sugar = result.get("sugar")
    if sugar is not None:
        lines.append(f"• 糖：{sugar}g")
    fiber = result.get("fiber")
    if fiber is not None:
        lines.append(f"• 膳食纖維：{fiber}g")

    pkg = result.get("servings_per_package")
    if pkg and pkg > 1:
        total_cal = (cal or 0) * pkg
        lines.append(f"\n📦 整包 {pkg} 份 = {total_cal} kcal")

    comment = result.get("brief_comment")
    if comment:
        lines.append(f"\n💬 {comment}")

    return "\n".join(lines)
