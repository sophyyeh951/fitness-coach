"""Weekly summary insights — picks angles for 教練說 block.

Mirrors `coach_lens.py` for daily but produces three independent lenses
(workout / diet / body), each surfacing one directive that the AI converts
into a one-line comment. Returns "" for any lens without a salient angle —
caller skips that line so we never pad with empty rhetoric.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import date, timedelta

from app.db import queries as db
from app.db import schedule as sch

logger = logging.getLogger(__name__)

PROTEIN_MIN = 90
BASE_TDEE = 1483
DAILY_DEFICIT = 300
WEIGHT_NOISE = 0.3   # kg, ±this is treated as scale fluctuation
BF_NOISE = 0.5       # %, ±this is treated as measurement noise


def _day_burn(active_cal: float, day_workouts: list[dict]) -> float:
    """Per-day total burn = TDEE + activity. Mirrors today.py:
    prefer Apple-Watch active_calories; fall back to summed workout estimates."""
    if active_cal and active_cal > 0:
        return BASE_TDEE + active_cal
    workout_est = sum(
        (w.get("estimated_calories") or 0)
        for w in day_workouts
        if "休息" not in (w.get("workout_type") or "")
    )
    return BASE_TDEE + workout_est


def _max_weight_per_exercise(workouts: list[dict]) -> dict[str, float]:
    """Map exercise name → max weight_kg seen across given workouts.
    Used for week-over-week strength progression comparison."""
    out: dict[str, float] = {}
    for w in workouts:
        for ex in w.get("exercises") or []:
            name = (ex.get("name") or "").strip()
            wt = ex.get("weight_kg")
            if not name or not wt:
                continue
            if wt > out.get(name, 0):
                out[name] = wt
    return out


def collect_week(start: date, end: date) -> dict:
    """Aggregate one inclusive 7-day window into the stats lenses need.

    Pulls meals/workouts day-by-day so per-day stats (protein-met streak,
    avg-only-on-logged-days, accurate per-day burn) stay correct when some
    days have no log.
    """
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]

    meals: list[dict] = []
    workouts: list[dict] = []
    by_day_kcal: dict[date, float] = {d: 0.0 for d in days}
    by_day_protein: dict[date, float] = {d: 0.0 for d in days}
    by_day_workouts: dict[date, list[dict]] = {d: [] for d in days}
    days_with_meals: set[date] = set()

    for d in days:
        d_meals = db.get_meals_for_date(d)
        d_workouts = db.get_workouts_for_date(d)
        meals.extend(d_meals)
        workouts.extend(d_workouts)
        by_day_workouts[d] = d_workouts
        for m in d_meals:
            kcal = m.get("total_calories") or 0
            protein = m.get("protein") or 0
            by_day_kcal[d] += kcal
            by_day_protein[d] += protein
            if kcal > 0:
                days_with_meals.add(d)

    metrics = db.get_body_metrics_range(start, end)

    # Per-day burn → per-day deficit. Use active_calories from body_metrics
    # when available, otherwise fall back to workout estimated_calories.
    active_by_day = {
        date.fromisoformat(m["date"]): (m.get("active_calories") or 0)
        for m in metrics
    }
    daily_burns: dict[date, float] = {}
    daily_deficits: dict[date, float] = {}
    for d in days:
        burn = _day_burn(active_by_day.get(d, 0), by_day_workouts[d])
        daily_burns[d] = burn
        if d in days_with_meals:
            daily_deficits[d] = burn - by_day_kcal[d]

    # Strength-day plan — count weekdays scheduled for 重訓 in this window.
    planned_strength = sum(1 for d in days if sch.get_today_exercise(d) == "重訓")
    actual_strength = sum(1 for w in workouts if w.get("workout_type") == "重訓")

    non_rest = [w for w in workouts if "休息" not in (w.get("workout_type") or "")]
    workout_breakdown = Counter(w.get("workout_type", "") for w in non_rest)

    if days_with_meals:
        avg_kcal = sum(by_day_kcal[d] for d in days_with_meals) / len(days_with_meals)
        avg_deficit = sum(daily_deficits.values()) / len(daily_deficits)
        days_protein_met = sum(
            1 for d in days_with_meals if by_day_protein[d] >= PROTEIN_MIN
        )
    else:
        avg_kcal = 0.0
        avg_deficit = 0.0
        days_protein_met = 0

    strength_workouts = [w for w in workouts if w.get("workout_type") == "重訓"]
    max_weight_per_exercise = _max_weight_per_exercise(strength_workouts)

    return {
        "meals": meals,
        "workouts": workouts,
        "metrics": metrics,
        "planned_strength": planned_strength,
        "actual_strength": actual_strength,
        "non_rest_count": len(non_rest),
        "workout_breakdown": workout_breakdown,
        "days_with_meals": len(days_with_meals),
        "avg_kcal": avg_kcal,
        "avg_deficit": avg_deficit,
        "days_protein_met": days_protein_met,
        "max_weight_per_exercise": max_weight_per_exercise,
    }


def _strength_progression_summary(this_week: dict, last_week: dict) -> str:
    """Compare max weight per exercise between weeks.
    Returns a short Chinese string highlighting the most-changed lifts, or "" if
    no overlap exists. Caps at 3 lifts to avoid swamping the directive."""
    this_max = this_week["max_weight_per_exercise"]
    last_max = last_week["max_weight_per_exercise"]
    overlap = set(this_max) & set(last_max)
    if not overlap:
        return ""

    changes = sorted(
        ((name, this_max[name] - last_max[name], last_max[name], this_max[name])
         for name in overlap),
        key=lambda x: -abs(x[1]),
    )[:3]
    if not changes:
        return ""

    parts = []
    for name, delta, prev, now in changes:
        if delta == 0:
            parts.append(f"{name} 持平 {now:g}kg")
        else:
            sign = "↑" if delta > 0 else "↓"
            parts.append(f"{name} {prev:g}→{now:g}kg（{sign}{abs(delta):g}）")
    return "；".join(parts)


def pick_workout_lens(this_week: dict, last_week: dict) -> str:
    """Strength-only lens (Q1 = C). Badminton counts toward cardio but doesn't
    drive recomp — strength frequency + weight progression are the signals."""
    done = this_week["actual_strength"]
    planned = this_week["planned_strength"]
    last_done = last_week["actual_strength"]

    if planned == 0:
        return ""

    diff_label = ""
    if last_done > 0 or this_week["non_rest_count"] > 0:
        delta = done - last_done
        sign = "+" if delta > 0 else ""
        diff_label = f"，上週 {last_done} 次（{sign}{delta}）"

    progression = _strength_progression_summary(this_week, last_week)
    progression_label = f" 重量進步：{progression}。" if progression else ""

    if done >= planned:
        return (
            f"本週重訓 {done}/{planned} 次達標{diff_label}。{progression_label}"
            "→ 給一句肯定。如果有重量進步資料，請點名一個進步最多或退步的動作；"
            "若無進步資料，給一個進階方向（重量加碼、部位平衡、或換動作刺激）。"
        )

    miss = planned - done
    return (
        f"本週重訓 {done}/{planned} 次（少 {miss} 次）{diff_label}。{progression_label}"
        "重訓是增肌主引擎，→ 給一句具體下週安排（指定哪天哪個部位）。"
        "如果有重量進步資料，可以順便提到一個值得追的動作，不要罐頭話。"
    )


def pick_diet_lens(this_week: dict, last_week: dict) -> str:
    """Q2 = C — give AI both calorie and protein angles, let it pick.
    Uses per-day actual burn (TDEE + activity) so badminton/training days
    aren't penalized as 'over-target'."""
    days = this_week["days_with_meals"]
    if days == 0:
        return ""

    avg = this_week["avg_kcal"]
    avg_def = this_week["avg_deficit"]
    pro_met = this_week["days_protein_met"]

    delta_label = ""
    if last_week["days_with_meals"]:
        d = avg - last_week["avg_kcal"]
        sign = "+" if d > 0 else ""
        delta_label = f"（上週 {last_week['avg_kcal']:.0f}，{sign}{d:.0f}）"

    protein_perfect = pro_met == days

    return (
        f"本週飲食記錄 {days}/7 天，平均攝取 {avg:.0f}kcal{delta_label}。"
        f"逐日實際赤字平均 {avg_def:+.0f}kcal/天（目標赤字 {DAILY_DEFICIT}）— "
        f"這個赤字是用「TDEE {BASE_TDEE} + 當天活動」算出來的，已考慮羽球/重訓的消耗。"
        f"蛋白質達標 {pro_met}/{days} 天（≥{PROTEIN_MIN}g）。"
        "→ 挑「熱量赤字是否合適 recomp」與「蛋白質達標」其中**改進空間較大**的那一個面向講。"
        f"{'蛋白質本週 100% 達標，請改聚焦熱量面向，不要恭維蛋白質。' if protein_perfect else ''}"
        "禁止輸出『多攝取 XX、YY 等優質蛋白』這種泛泛食材推薦；"
        "若聚焦熱量，要點名「赤字過大會掉肌」或「赤字不足進度慢」這種具體 trade-off。"
    )


def _delta(records: list[float]) -> float | None:
    if len(records) < 2:
        return None
    return records[-1] - records[0]


def pick_body_lens(this_week: dict, last_week: dict) -> str:
    metrics = this_week["metrics"]
    weights = [m["weight"] for m in metrics if m.get("weight") is not None]
    bf_rows = [m for m in metrics if m.get("body_fat_pct") is not None]
    mu_rows = [m for m in metrics if m.get("muscle_pct") is not None]

    if not weights and not bf_rows and not mu_rows:
        return ""

    parts: list[str] = []
    notes: list[str] = []

    wd = _delta(weights)
    if wd is not None:
        parts.append(f"體重 {wd:+.1f}kg")
        if abs(wd) <= WEIGHT_NOISE:
            notes.append("體重變化在 ±0.3kg 波動範圍內")
    elif weights:
        notes.append("體重只有 1 次讀數")

    if len(bf_rows) >= 2:
        bd = bf_rows[-1]["body_fat_pct"] - bf_rows[0]["body_fat_pct"]
        first_w = bf_rows[0].get("weight")
        last_w = bf_rows[-1].get("weight")
        if first_w and last_w:
            mass_d = last_w * bf_rows[-1]["body_fat_pct"] / 100 - first_w * bf_rows[0]["body_fat_pct"] / 100
            parts.append(f"脂肪 {mass_d:+.1f}kg（體脂 {bd:+.1f}%）")
        else:
            parts.append(f"體脂 {bd:+.1f}%")
        if abs(bd) <= BF_NOISE:
            notes.append("體脂變化在 ±0.5% 波動範圍內")
    elif bf_rows:
        notes.append("體脂只有 1 次讀數，無法判斷組成方向")

    if len(mu_rows) >= 2:
        md = mu_rows[-1]["muscle_pct"] - mu_rows[0]["muscle_pct"]
        first_w = mu_rows[0].get("weight")
        last_w = mu_rows[-1].get("weight")
        if first_w and last_w:
            mass_d = last_w * mu_rows[-1]["muscle_pct"] / 100 - first_w * mu_rows[0]["muscle_pct"] / 100
            parts.append(f"肌肉 {mass_d:+.1f}kg（{md:+.1f}%）")
        else:
            parts.append(f"肌肉 {md:+.1f}%")

    # Last-week comparison: the direction of weight change WoW gives a momentum signal
    last_weights = [m["weight"] for m in last_week["metrics"] if m.get("weight") is not None]
    last_wd = _delta(last_weights)
    if wd is not None and last_wd is not None:
        if wd * last_wd > 0 and abs(wd) > WEIGHT_NOISE:
            parts.append(f"連兩週體重{'升' if wd > 0 else '降'}")

    summary = "、".join(parts) if parts else "資料不足"
    note_str = ("（" + "；".join(notes) + "）") if notes else ""

    return (
        f"本週 {summary}{note_str}。"
        "→ 判讀方向（recomp 漂亮 / 偏增脂 / 偏掉肌 / 資料不足無法判斷），"
        "給一句具體建議。如有「波動範圍內」提示，請避免強行解讀方向；"
        "如有「只有 1 次讀數」提示，請建議下週多站幾次 PICOOC。"
    )


async def generate_weekly_insight(
    workout_lens: str, diet_lens: str, body_lens: str
) -> str | None:
    """Call Gemini to render lens directives into 教練說 text.

    Returns the formatted block (with leading newline), or None if AI fails
    or all lenses are empty. Per Q4 = A: on failure we omit the section
    entirely so the user notices Gemini is down.
    """
    if not (workout_lens or diet_lens or body_lens):
        return None

    from google.genai import types
    from app.ai.coach import _build_profile_context, client, MODEL
    from app.ai.prompts import WEEKLY_INSIGHT_PROMPT

    prompt = WEEKLY_INSIGHT_PROMPT.format(
        user_profile=_build_profile_context(),
        workout_lens=workout_lens or "（空 — 此行省略）",
        diet_lens=diet_lens or "（空 — 此行省略）",
        body_lens=body_lens or "（空 — 此行省略）",
    )

    try:
        response = await client.aio.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.5,
                max_output_tokens=400,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
    except Exception:
        logger.exception("Weekly insight generation failed")
        return None

    text = (response.text or "").strip()
    if not text:
        return None
    return text
