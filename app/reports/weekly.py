"""Generate weekly summary reports."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from app.db import queries as db

logger = logging.getLogger(__name__)


def generate_weekly_text(end_date: date | None = None) -> str:
    """Generate a text-based weekly summary."""
    if end_date is None:
        end_date = date.today()
    start_date = end_date - timedelta(days=6)

    lines = [f"📊 週報 {start_date.strftime('%m/%d')} - {end_date.strftime('%m/%d')}\n"]

    # Aggregate daily summaries
    total_cal = 0
    total_pro = 0
    days_tracked = 0
    current = start_date
    while current <= end_date:
        summary = db.get_daily_summary(current)
        if summary and summary.get("total_calories_in"):
            total_cal += summary["total_calories_in"]
            total_pro += summary.get("total_protein", 0)
            days_tracked += 1
        current += timedelta(days=1)

    if days_tracked > 0:
        lines.append(f"🍽 飲食（記錄 {days_tracked} 天）")
        lines.append(f"  平均每日：{total_cal / days_tracked:.0f} kcal")
        lines.append(f"  平均蛋白質：{total_pro / days_tracked:.0f}g")
    else:
        lines.append("🍽 本週沒有飲食記錄")

    # Workout count
    workout_count = 0
    current = start_date
    while current <= end_date:
        workouts = db.get_workouts_for_date(current)
        workout_count += len(workouts)
        current += timedelta(days=1)

    lines.append(f"\n💪 本週訓練 {workout_count} 次")

    # Body metrics trend
    metrics = db.get_body_metrics_range(start_date, end_date)
    if len(metrics) >= 2:
        first = metrics[0]
        last = metrics[-1]
        if first.get("weight") and last.get("weight"):
            diff = last["weight"] - first["weight"]
            arrow = "↑" if diff > 0 else "↓" if diff < 0 else "→"
            lines.append(
                f"\n⚖️ 體重：{first['weight']}→{last['weight']} kg（{arrow}{abs(diff):.1f}）"
            )
        if first.get("body_fat_pct") and last.get("body_fat_pct"):
            diff = last["body_fat_pct"] - first["body_fat_pct"]
            arrow = "↑" if diff > 0 else "↓" if diff < 0 else "→"
            lines.append(
                f"📉 體脂：{first['body_fat_pct']}→{last['body_fat_pct']}%（{arrow}{abs(diff):.1f}）"
            )
    elif len(metrics) == 1:
        m = metrics[0]
        if m.get("weight"):
            lines.append(f"\n⚖️ 體重：{m['weight']} kg")
        if m.get("body_fat_pct"):
            lines.append(f"📉 體脂：{m['body_fat_pct']}%")

    return "\n".join(lines)
