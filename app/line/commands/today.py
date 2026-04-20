"""
/今日 — show today's complete log with IDs for manual correction.
"""

from __future__ import annotations
from app.db import queries as db
from app.config import today_tw

PROTEIN_TARGET = 86   # minimum grams
BASE_TDEE = 1483      # sedentary TDEE (BMR 1236 × 1.2)


def _exercise_estimate(planned: str | None) -> tuple[int, str]:
    """Return (estimated_active_kcal, label) from today's planned exercise."""
    if not planned:
        return 0, "休息日"
    p = planned
    if any(k in p for k in ["羽球", "打球"]):
        return 550, "羽球"
    if any(k in p for k in ["游泳"]):
        return 500, "游泳"
    if any(k in p for k in ["跑步", "有氧"]):
        return 500, "有氧"
    if any(k in p for k in ["重訓", "訓練", "健身"]):
        return 300, "重訓"
    if any(k in p for k in ["休息"]):
        return 0, "休息日"
    return 300, "運動"


async def handle_today() -> str:
    today = today_tw()
    lines = ["📊 今日紀錄\n"]

    # ── Meals ──────────────────────────────────────────
    meals = db.get_meals_for_date(today)
    meal_type_display = {
        "breakfast": "早餐", "lunch": "午餐",
        "dinner": "晚餐", "snack": "點心", "other": "其他",
    }
    total_kcal = total_protein = total_carbs = total_fat = 0.0

    if meals:
        lines.append("🍽 飲食")
        for m in meals:
            foods = m.get("food_items", [])
            names = "、".join(f["name"] for f in foods[:2]) if foods else "（無詳細）"
            if len(foods) > 2:
                names += f" 等{len(foods)}項"
            dtype = meal_type_display.get(m.get("meal_type", "other"), "其他")
            kcal = m.get("total_calories", 0) or 0
            pro  = m.get("protein", 0) or 0
            carb = m.get("carbs", 0) or 0
            fat  = m.get("fat", 0) or 0
            total_kcal    += kcal
            total_protein += pro
            total_carbs   += carb
            total_fat     += fat
            lines.append(f"  #{m['id']} {dtype} {names} {kcal:.0f}kcal")
            lines.append(f"       P {pro:.0f}g / C {carb:.0f}g / F {fat:.0f}g")

        lines.append(f"  ─────────────────────")
        lines.append(f"  合計：{total_kcal:.0f}kcal")
        lines.append(f"  P {total_protein:.0f}g / C {total_carbs:.0f}g / F {total_fat:.0f}g")

        # Protein gap
        gap = PROTEIN_TARGET - total_protein
        if gap > 0:
            lines.append(f"  🥩 蛋白質還差 {gap:.0f}g（目標 {PROTEIN_TARGET}g）")
        else:
            lines.append(f"  🥩 蛋白質達標 ✅")

        lines.append("  ─────────────────────")
        lines.append("  刪除：/刪 [ID]   修改餐別：/改 [ID] 午餐")
    else:
        lines.append("🍽 飲食：尚無紀錄")

    lines.append("")

    # ── Workouts ───────────────────────────────────────
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

    # ── Body metrics ───────────────────────────────────
    metrics = db.get_body_metrics_range(today, today)
    if metrics:
        m = metrics[-1]
        parts = []
        if m.get("weight"):           parts.append(f"體重 {m['weight']}kg")
        if m.get("body_fat_pct"):     parts.append(f"體脂 {m['body_fat_pct']}%")
        if m.get("active_calories"):  parts.append(f"活動消耗 {m['active_calories']:.0f}kcal")
        if m.get("resting_heart_rate"): parts.append(f"靜心率 {m['resting_heart_rate']}bpm")
        lines.append("⚖️ 身體：" + "　".join(parts))
    else:
        lines.append("⚖️ 身體：尚無紀錄")

    lines.append("")

    # ── Calorie burn estimate ──────────────────────────
    from app.db.schedule import get_today_exercise
    planned = get_today_exercise(today)

    # Prefer actual Apple Watch active calories if available
    actual_active = (metrics[-1].get("active_calories") or 0) if metrics else 0
    if actual_active > 0:
        total_burn = BASE_TDEE + actual_active
        lines.append(f"🔥 實際消耗：{total_burn:.0f}kcal（基底{BASE_TDEE} + 活動{actual_active:.0f}）")
    else:
        exercise_est, exercise_label = _exercise_estimate(planned)
        total_burn = BASE_TDEE + exercise_est
        if planned:
            lines.append(f"🔥 預估消耗：{total_burn:.0f}kcal（基底{BASE_TDEE} + {exercise_label}~{exercise_est}）")
        else:
            lines.append(f"🔥 預估消耗：{total_burn:.0f}kcal（基底{BASE_TDEE} + 休息日~0）")

    # Calorie balance
    if total_kcal > 0:
        balance = total_kcal - total_burn
        if balance < 0:
            lines.append(f"→ 赤字 {abs(balance):.0f}kcal ✅")
        else:
            lines.append(f"→ 盈餘 {balance:.0f}kcal")

    return "\n".join(lines)
