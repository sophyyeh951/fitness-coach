"""
/週報 — 7-day rolling summary of exercise, diet, and body metrics.

Also triggered automatically every Sunday at 20:00 Taiwan time.
"""

from __future__ import annotations
from datetime import timedelta
from app.config import today_tw
from app.reports import weekly_lens


def _rows_with(metrics: list[dict], key: str) -> list[dict]:
    """Rows where `key` is present and non-null, chronological. Scanned per
    metric so a final-day Apple-Health-only row (weight without body comp)
    doesn't mask body_fat recorded earlier in the week."""
    return [m for m in metrics if m.get(key) is not None]


def _fmt_change(first: float, last: float, unit: str) -> str:
    diff = last - first
    arrow = "↑" if diff > 0 else "↓" if diff < 0 else "→"
    return f"{first:.1f}→{last:.1f}{unit}（{arrow}{abs(diff):.1f}）"


def _body_line(label: str, rows: list[dict], key: str, mass_first: bool) -> str | None:
    """Format one body metric line. Shows delta if 2+ readings, single value if 1,
    None if 0. When `mass_first`, lead with derived mass (kg) and tuck the % into
    the parens — body composition's signal for recomp lives in absolute mass."""
    if not rows:
        return None
    if len(rows) == 1:
        r = rows[0]
        v = r[key]
        w = r.get("weight")
        if mass_first and w:
            return f"{label} {w * v / 100:.1f}kg（{v:.1f}%）"
        unit = "%" if mass_first else "kg"
        return f"{label} {v:.1f}{unit}"
    first, last = rows[0], rows[-1]
    fv, lv = first[key], last[key]
    fw, lw = first.get("weight"), last.get("weight")
    if mass_first and fw and lw:
        diff = lw * lv / 100 - fw * fv / 100
        arrow = "↑" if diff > 0 else "↓" if diff < 0 else "→"
        return (
            f"{label} {fw * fv / 100:.1f}→{lw * lv / 100:.1f}kg"
            f"（{arrow}{abs(diff):.1f}｜{fv:.1f}%→{lv:.1f}%）"
        )
    unit = "%" if mass_first else "kg"
    return f"{label} {_fmt_change(fv, lv, unit)}"


def _body_mass_delta(metrics: list[dict], pct_key: str) -> float | None:
    """Mass delta (kg) for fat or muscle across the week. Needs 2+ rows
    with both pct and weight; returns None otherwise."""
    rows = [m for m in metrics if m.get(pct_key) is not None and m.get("weight")]
    if len(rows) < 2:
        return None
    return rows[-1]["weight"] * rows[-1][pct_key] / 100 - rows[0]["weight"] * rows[0][pct_key] / 100


def _build_wow_lines(this_week: dict, last_week: dict) -> list[str]:
    """User cares about week-over-week for strength + body, not diet (per Q2).
    Returns lines for the 📈 vs 上週 block — one per metric, only when both
    weeks have comparable data."""
    lines: list[str] = []

    # Strength frequency
    if this_week["planned_strength"] > 0 or last_week["actual_strength"] > 0:
        lines.append(
            f"重訓 {this_week['actual_strength']}次（上週 {last_week['actual_strength']}次）"
        )

    # Body deltas — show even when last week's reading is missing, to make the
    # asymmetry visible.
    def _wd(metrics):
        weights = [m["weight"] for m in metrics if m.get("weight") is not None]
        return None if len(weights) < 2 else weights[-1] - weights[0]

    tw_wd = _wd(this_week["metrics"])
    lw_wd = _wd(last_week["metrics"])
    if tw_wd is not None or lw_wd is not None:
        cur = f"{tw_wd:+.1f}kg" if tw_wd is not None else "—"
        prev = f"{lw_wd:+.1f}kg" if lw_wd is not None else "—"
        lines.append(f"體重變化 {cur}（上週 {prev}）")

    tw_fat = _body_mass_delta(this_week["metrics"], "body_fat_pct")
    lw_fat = _body_mass_delta(last_week["metrics"], "body_fat_pct")
    if tw_fat is not None or lw_fat is not None:
        cur = f"{tw_fat:+.1f}kg" if tw_fat is not None else "—"
        prev = f"{lw_fat:+.1f}kg" if lw_fat is not None else "—"
        lines.append(f"脂肪重變化 {cur}（上週 {prev}）")

    tw_mus = _body_mass_delta(this_week["metrics"], "muscle_pct")
    lw_mus = _body_mass_delta(last_week["metrics"], "muscle_pct")
    if tw_mus is not None or lw_mus is not None:
        cur = f"{tw_mus:+.1f}kg" if tw_mus is not None else "—"
        prev = f"{lw_mus:+.1f}kg" if lw_mus is not None else "—"
        lines.append(f"肌肉重變化 {cur}（上週 {prev}）")

    return lines


async def handle_weekly_report() -> str:
    today = today_tw()
    start = today - timedelta(days=6)

    this_week = weekly_lens.collect_week(start, today)
    last_week = weekly_lens.collect_week(start - timedelta(days=7), today - timedelta(days=7))

    # Workout summary
    breakdown = this_week["workout_breakdown"]
    workout_str = "　".join(f"{t}x{c}" for t, c in breakdown.items()) if breakdown else "無"

    # Diet summary — average over the full 7 days (matches existing behavior)
    avg_kcal_7d = sum(m.get("total_calories", 0) or 0 for m in this_week["meals"]) / 7
    avg_protein_7d = sum(m.get("protein", 0) or 0 for m in this_week["meals"]) / 7

    metrics = this_week["metrics"]
    body_lines = [
        line for line in (
            _body_line("體重", _rows_with(metrics, "weight"), "weight", mass_first=False),
            _body_line("脂肪", _rows_with(metrics, "body_fat_pct"), "body_fat_pct", mass_first=True),
            _body_line("肌肉", _rows_with(metrics, "muscle_pct"), "muscle_pct", mass_first=True),
        ) if line
    ]

    lines = [
        f"📊 近7天總結 {start.strftime('%m/%d')}–{today.strftime('%m/%d')}\n",
        f"💪 運動：{this_week['non_rest_count']}次（{workout_str}）",
        f"🍽 飲食：平均 {avg_kcal_7d:.0f}kcal/天｜蛋白質平均 {avg_protein_7d:.0f}g",
    ]
    if body_lines:
        lines.append("⚖️ 身體：")
        lines.extend(f"  • {b}" for b in body_lines)

    # WoW comparison — facts only, AI block does interpretation
    wow_lines = _build_wow_lines(this_week, last_week)
    if wow_lines:
        lines.append("\n📈 vs 上週：")
        lines.extend(f"  • {w}" for w in wow_lines)

    # AI insight block — Q4 = A: omit on failure so user notices Gemini is down
    insight = await weekly_lens.generate_weekly_insight(
        weekly_lens.pick_workout_lens(this_week, last_week),
        weekly_lens.pick_diet_lens(this_week, last_week),
        weekly_lens.pick_body_lens(this_week, last_week),
    )
    if insight:
        lines.append(f"\n🧠 教練說：\n{insight}")

    return "\n".join(lines)
