"""Generate weekly summary reports."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from app.db import queries as db

logger = logging.getLogger(__name__)


def _total_volume(workouts: list[dict]) -> float:
    """Sum weight_kg × reps × sets across all exercises in the given workouts.
    Reps/sets default to 1 when missing so menus without full structure still count."""
    total = 0.0
    for w in workouts:
        for ex in (w.get("exercises") or []):
            weight = ex.get("weight_kg") or 0
            reps = ex.get("reps") or 1
            sets = ex.get("sets") or 1
            total += float(weight) * float(reps) * float(sets)
    return total


def _trend_marker(this_v: float, last_v: float) -> str:
    if last_v <= 0:
        return ""
    diff_pct = (this_v - last_v) / last_v * 100
    if diff_pct >= 5:
        return f" ↑{diff_pct:.0f}%"
    if diff_pct <= -5:
        return f" ↓{abs(diff_pct):.0f}%"
    return " →"


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

    # Per-muscle-group comparison vs prior week.
    # User typically hits each part once per week — compare this week's session
    # against last week's same part.
    prev_start = start_date - timedelta(days=7)
    prev_end = end_date - timedelta(days=7)
    part_lines = []
    for group in ("胸肩", "背", "臀腿"):
        try:
            this_week = db.get_workouts_by_muscle_group_range(group, start_date, end_date)
            last_week = db.get_workouts_by_muscle_group_range(group, prev_start, prev_end)
        except Exception:
            logger.exception("Failed to fetch muscle group %s", group)
            continue
        if not this_week and not last_week:
            continue
        this_vol = _total_volume(this_week)
        last_vol = _total_volume(last_week)
        marker = _trend_marker(this_vol, last_vol)
        if this_week and last_week:
            part_lines.append(
                f"• {group}：{this_vol:.0f} vs 上週 {last_vol:.0f}{marker}"
            )
        elif this_week:
            part_lines.append(f"• {group}：{this_vol:.0f}（上週沒練）")
        else:
            part_lines.append(f"• {group}：本週沒練（上週 {last_vol:.0f}）")
    if part_lines:
        lines.append("\n🏋️ 各部位訓練量（總重量 kg × 次數）")
        lines.extend(part_lines)

    # Body composition change vs previous week
    metrics = db.get_body_metrics_range(start_date, end_date)
    if len(metrics) >= 2:
        first = metrics[0]
        last = metrics[-1]
        lines.append("\n⚖️ 身體組成變化")

        fw, lw = first.get("weight"), last.get("weight")
        if fw and lw:
            diff = lw - fw
            arrow = "↑" if diff > 0 else "↓" if diff < 0 else "→"
            lines.append(f"• 體重：{fw} → {lw} kg（{arrow}{abs(diff):.1f}）")

        fbf, lbf = first.get("body_fat_pct"), last.get("body_fat_pct")
        if fbf is not None and lbf is not None:
            pct_diff = lbf - fbf
            arrow = "↑" if pct_diff > 0 else "↓" if pct_diff < 0 else "→"
            tail = ""
            if fw and lw:
                mass_diff = (lw * lbf - fw * fbf) / 100
                sign = "+" if mass_diff > 0 else ""
                tail = f"｜脂肪 {sign}{mass_diff:.1f} kg"
            lines.append(f"• 體脂：{fbf}% → {lbf}%（{arrow}{abs(pct_diff):.1f}pp{tail}）")

        fmp, lmp = first.get("muscle_pct"), last.get("muscle_pct")
        if fmp is not None and lmp is not None:
            pct_diff = lmp - fmp
            arrow = "↑" if pct_diff > 0 else "↓" if pct_diff < 0 else "→"
            tail = ""
            if fw and lw:
                mass_diff = (lw * lmp - fw * fmp) / 100
                sign = "+" if mass_diff > 0 else ""
                tail = f"｜肌肉 {sign}{mass_diff:.1f} kg"
            lines.append(f"• 肌肉：{fmp}% → {lmp}%（{arrow}{abs(pct_diff):.1f}pp{tail}）")
    elif len(metrics) == 1:
        m = metrics[0]
        w = m.get("weight")
        bf = m.get("body_fat_pct")
        mp = m.get("muscle_pct")
        lines.append("\n⚖️ 本週一次測量")
        if w: lines.append(f"• 體重：{w} kg")
        if bf is not None:
            tail = f"（脂肪 {w * bf / 100:.1f} kg）" if w else ""
            lines.append(f"• 體脂：{bf}%{tail}")
        if mp is not None:
            tail = f"（肌肉 {w * mp / 100:.1f} kg）" if w else ""
            lines.append(f"• 肌肉：{mp}%{tail}")

    return "\n".join(lines)
