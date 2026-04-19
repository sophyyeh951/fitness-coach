"""
/週報 — 7-day rolling summary of exercise, diet, and body metrics.

Also triggered automatically every Sunday at 20:00 Taiwan time.
"""

from __future__ import annotations
from datetime import timedelta
from app.db import queries as db
from app.config import today_tw


async def handle_weekly_report() -> str:
    today = today_tw()
    start = today - timedelta(days=6)

    meals_all = []
    workouts_all = []
    for i in range(7):
        day = start + timedelta(days=i)
        meals_all.extend(db.get_meals_for_date(day))
        workouts_all.extend(db.get_workouts_for_date(day))

    metrics = db.get_body_metrics_range(start, today)

    # Workout summary
    non_rest = [w for w in workouts_all if w.get("workout_type") != "休息"]
    workout_types = [w.get("workout_type", "") for w in non_rest]
    from collections import Counter
    type_counts = Counter(workout_types)
    workout_str = "　".join(f"{t}x{c}" for t, c in type_counts.items()) if type_counts else "無"

    # Diet summary
    if meals_all:
        avg_kcal = sum(m.get("total_calories", 0) for m in meals_all) / 7
        avg_protein = sum(m.get("protein", 0) for m in meals_all) / 7
    else:
        avg_kcal = avg_protein = 0

    # Body change
    body_str = ""
    if len(metrics) >= 2:
        first, last = metrics[0], metrics[-1]
        w_change = (last.get("weight", 0) or 0) - (first.get("weight", 0) or 0)
        bf_change = (last.get("body_fat_pct", 0) or 0) - (first.get("body_fat_pct", 0) or 0)
        w_arrow = "↑" if w_change > 0 else "↓" if w_change < 0 else "→"
        bf_arrow = "↑" if bf_change > 0 else "↓" if bf_change < 0 else "→"
        body_str = (
            f"⚖️ 身體：體重 {first.get('weight','?')}→{last.get('weight','?')}kg（{w_arrow}{abs(w_change):.1f}）"
            f"　體脂 {first.get('body_fat_pct','?')}→{last.get('body_fat_pct','?')}%（{bf_arrow}{abs(bf_change):.1f}）"
        )
    elif metrics:
        m = metrics[-1]
        body_str = f"⚖️ 身體：體重 {m.get('weight','?')}kg　體脂 {m.get('body_fat_pct','?')}%"

    lines = [
        f"📊 近7天總結 {start.strftime('%m/%d')}–{today.strftime('%m/%d')}\n",
        f"💪 運動：{len(non_rest)}次（{workout_str}）",
        f"🍽 飲食：平均 {avg_kcal:.0f}kcal/天｜蛋白質平均 {avg_protein:.0f}g",
    ]
    if body_str:
        lines.append(body_str)

    return "\n".join(lines)
