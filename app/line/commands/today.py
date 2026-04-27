"""
/今日 — show today's complete log with IDs for manual correction.
"""

from __future__ import annotations
from datetime import date
from app.db import queries as db
from app.config import today_tw

_WEEKDAY_TW = ["一", "二", "三", "四", "五", "六", "日"]


def format_date_label(d: date) -> str:
    """Render '2026 年 4 月 27 日 星期一' for headers — quick visual scan + scrollback search."""
    return f"{d.year} 年 {d.month} 月 {d.day} 日 星期{_WEEKDAY_TW[d.weekday()]}"

BASE_TDEE = 1483          # sedentary TDEE (BMR 1236 × 1.2)
DAILY_DEFICIT = 300       # target daily deficit for recomp
MIN_DAILY_TARGET = 1300   # floor for intake target on rest days

PROTEIN_MIN = 90          # floor for muscle preservation (~1.7g/kg body weight)
PROTEIN_IDEAL = 107       # ideal for recomp (~2g/kg body weight)

# Back-compat for any external importers; new code should use PROTEIN_MIN.
PROTEIN_TARGET = PROTEIN_MIN


def calc_intake_target(total_burn: float) -> float:
    """Daily intake target = TDEE − deficit, floored at MIN_DAILY_TARGET."""
    return max(MIN_DAILY_TARGET, total_burn - DAILY_DEFICIT)


def protein_status_line(total_protein: float) -> str:
    """Render one-line protein status against the 90–107g range."""
    if total_protein < PROTEIN_MIN:
        gap = PROTEIN_MIN - total_protein
        return f"🥩 蛋白質還差 {gap:.0f}g（目標 {PROTEIN_MIN}–{PROTEIN_IDEAL}g）"
    if total_protein < PROTEIN_IDEAL:
        return f"🥩 蛋白質基本達標 ✅（理想 {PROTEIN_IDEAL}g）"
    return "🥩 蛋白質達標 🎯"


_TYPE_ESTIMATES = (
    (("羽球", "打球"), 550, "羽球"),
    (("游泳",),       500, "游泳"),
    (("跑步", "有氧"), 500, "有氧"),
)


def _classify_workout_type(wtype: str) -> tuple[int, str]:
    for keys, est, label in _TYPE_ESTIMATES:
        if any(k in wtype for k in keys):
            return est, label
    return 300, "重訓"


def _burn_from_workouts(workouts: list[dict]) -> tuple[int, str]:
    """Return (estimated_active_kcal, short_label) from today's recorded workouts.

    Sums each non-rest workout's `estimated_calories` (DB-recorded), falling back
    to a type-based estimate when missing. Label is the most recent non-rest
    workout's type. All-rest returns (0, '休息').
    """
    active = [w for w in workouts if "休息" not in (w.get("workout_type") or "")]
    if not active:
        return 0, "休息"

    total = 0
    for w in active:
        kcal = w.get("estimated_calories")
        if not kcal:
            kcal, _ = _classify_workout_type(w.get("workout_type") or "")
        total += kcal

    _, label = _classify_workout_type(active[-1].get("workout_type") or "")
    return int(total), label


def _exercise_estimate(planned: str | None) -> tuple[int, str]:
    """Return (estimated_active_kcal, label) from today's planned exercise."""
    if not planned:
        return 0, "休息"
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
        return 0, "休息"
    return 300, "運動"


async def handle_today() -> str:
    today = today_tw()
    lines = [f"📊 今日紀錄 · {format_date_label(today)}\n"]

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

        lines.append("  " + protein_status_line(total_protein))

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
        weight = m.get("weight")
        bf = m.get("body_fat_pct")
        mp = m.get("muscle_pct")
        parts = []
        if weight: parts.append(f"體重 {weight}kg")
        if bf is not None:
            tail = f"（{weight * bf / 100:.1f}kg）" if weight else ""
            parts.append(f"體脂 {bf}%{tail}")
        if mp is not None:
            tail = f"（{weight * mp / 100:.1f}kg）" if weight else ""
            parts.append(f"肌肉 {mp}%{tail}")
        if m.get("active_calories"):    parts.append(f"活動消耗 {m['active_calories']:.0f}kcal")
        if m.get("resting_heart_rate"): parts.append(f"靜心率 {m['resting_heart_rate']}bpm")
        lines.append("⚖️ 身體：" + "　".join(parts))
    else:
        lines.append("⚖️ 身體：尚無紀錄")

    lines.append("")

    # ── Calorie burn estimate ──────────────────────────
    # Priority 1: actual Apple Watch active calories
    actual_active = (metrics[-1].get("active_calories") or 0) if metrics else 0
    if actual_active > 0:
        total_burn = BASE_TDEE + actual_active
        breakdown = f"基底{BASE_TDEE} + 活動{actual_active:.0f}"
    else:
        # Priority 2: recorded workout (overrides schedule). Priority 3: schedule.
        if workouts:
            exercise_est, exercise_label = _burn_from_workouts(workouts)
        else:
            from app.db.schedule import get_today_exercise
            planned = get_today_exercise(today)
            exercise_est, exercise_label = _exercise_estimate(planned)
        total_burn = BASE_TDEE + exercise_est
        breakdown = f"基底{BASE_TDEE} + {exercise_label}~{exercise_est}"

    target = calc_intake_target(total_burn)

    # Single-line summary with all key numbers; breakdown on a small second line.
    head_parts = [f"🔥 消耗 {total_burn:.0f}", f"🎯 目標攝取 {target:.0f}"]
    if total_kcal > 0:
        remaining = target - total_kcal
        if remaining > 0:
            head_parts.append(f"還可以吃 {remaining:.0f}kcal")
        else:
            head_parts.append(f"已超出 {abs(remaining):.0f}kcal")
    lines.append("｜".join(head_parts))
    lines.append(f"   （{breakdown}，赤字 {DAILY_DEFICIT}）")

    return "\n".join(lines)
