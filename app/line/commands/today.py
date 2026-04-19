"""
/今日 — show today's complete log with IDs for manual correction.
"""

from __future__ import annotations
from app.db import queries as db
from app.config import today_tw


async def handle_today() -> str:
    today = today_tw()
    lines = ["📊 今日紀錄\n"]

    # Meals
    meals = db.get_meals_for_date(today)
    meal_type_display = {
        "breakfast": "早餐", "lunch": "午餐",
        "dinner": "晚餐", "snack": "點心", "other": "其他"
    }
    if meals:
        lines.append("🍽 飲食")
        total_kcal = 0
        total_protein = 0
        for m in meals:
            foods = m.get("food_items", [])
            names = "、".join(f["name"] for f in foods[:2]) if foods else "（無詳細）"
            if len(foods) > 2:
                names += f" 等{len(foods)}項"
            dtype = meal_type_display.get(m.get("meal_type", "other"), "其他")
            kcal = m.get("total_calories", 0)
            total_kcal += kcal
            total_protein += m.get("protein", 0)
            lines.append(f"  #{m['id']} {dtype} {names} {kcal:.0f}kcal")
        lines.append(f"  合計：{total_kcal:.0f}kcal｜蛋白質 {total_protein:.0f}g")
        lines.append("  刪除：/刪 [ID]   修改餐別：/改 [ID] 午餐")
    else:
        lines.append("🍽 飲食：尚無紀錄")

    lines.append("")

    # Workouts
    workouts = db.get_workouts_for_date(today)
    if workouts:
        lines.append("💪 運動")
        for w in workouts:
            wtype = w.get("workout_type", "?")
            kcal = w.get("estimated_calories") or 0
            kcal_str = f" {kcal:.0f}kcal" if kcal else ""
            lines.append(f"  #{w['id']} {wtype}{kcal_str}")
    else:
        lines.append("💪 運動：尚無紀錄")

    lines.append("")

    # Body metrics
    metrics = db.get_body_metrics_range(today, today)
    if metrics:
        m = metrics[-1]
        parts = []
        if m.get("weight"): parts.append(f"體重 {m['weight']}kg")
        if m.get("body_fat_pct"): parts.append(f"體脂 {m['body_fat_pct']}%")
        if m.get("active_calories"): parts.append(f"活動消耗 {m['active_calories']:.0f}kcal")
        if m.get("resting_heart_rate"): parts.append(f"靜心率 {m['resting_heart_rate']}bpm")
        lines.append("⚖️ 身體：" + "　".join(parts))
    else:
        lines.append("⚖️ 身體：尚無紀錄")

    return "\n".join(lines)
