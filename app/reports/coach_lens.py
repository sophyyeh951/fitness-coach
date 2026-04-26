"""Pick the most salient angle for today's daily-summary 教練說 line.

The AI prompt was producing formulaic 「體脂從 X 降到 Y」 every day because it
had a fixed example and near-identical inputs. This module picks one concrete
angle worth speaking to today (protein gap, dinner imbalance, streak, …) and
hands it to the prompt as a directive. Returns "" when nothing's salient — AI
falls back to a generic observation.
"""
from __future__ import annotations

PROTEIN_MIN = 90
DAILY_DEFICIT = 300
BASE_TDEE = 1483


def pick_coach_lens(
    today_meals: list[dict],
    today_workouts: list[dict],
    today_metrics: dict | None,
    recent_summaries: list[dict],
) -> str:
    """Return a one-line directive for the AI to anchor on, or ""."""
    today_kcal = sum(m.get("total_calories", 0) or 0 for m in today_meals)
    today_protein = sum(m.get("protein", 0) or 0 for m in today_meals)

    # 1. Late-heavy day: dinner > 50% of total intake
    if today_meals and today_kcal > 1000:
        dinner_kcal = sum(
            m.get("total_calories", 0) or 0
            for m in today_meals
            if m.get("meal_type") == "dinner"
        )
        if dinner_kcal / today_kcal > 0.5:
            pct = dinner_kcal / today_kcal * 100
            return (
                f"今日 {pct:.0f}% 熱量集中在晚餐（{dinner_kcal:.0f}/{today_kcal:.0f}kcal）。"
                "→ 請給一句具體建議，怎麼把熱量分散到早午餐（指出一個食物/份量）。"
            )

    # 2. Protein shortfall (only if user actually ate today)
    if today_meals and today_protein < PROTEIN_MIN:
        gap = PROTEIN_MIN - today_protein
        return (
            f"今日蛋白質 {today_protein:.0f}g（差 {gap:.0f}g 才到 {PROTEIN_MIN}g 下限）。"
            "→ 請給一句明日可立即執行的補蛋白建議（指名食物 + 份量，例：早餐多 1 顆蛋 + 1 杯豆漿）。"
        )

    # 3. Rest streak: today is rest + N consecutive past rest days
    today_is_rest = bool(today_workouts) and all(
        "休息" in (w.get("workout_type") or "") for w in today_workouts
    )
    if today_is_rest:
        rest_days = 1
        for s in reversed(recent_summaries):
            ws = s.get("workout_summary") or ""
            if not ws or "休息" in ws:
                rest_days += 1
            else:
                break
        if rest_days >= 3:
            return (
                f"連續 {rest_days} 天沒訓練了。"
                "→ 請給一句溫和提醒：明天嘗試 20 分鐘輕度活動（散步/瑜珈），不必到健身房。"
            )

    # 4. Deficit streak: 3+ recent days hitting the target window (target ±100kcal)
    target = BASE_TDEE - DAILY_DEFICIT
    streak = 0
    for s in reversed(recent_summaries):
        kcal_in = s.get("total_calories_in")
        if kcal_in is None:
            break
        if target - 100 <= kcal_in <= target + 100:
            streak += 1
        else:
            break
    if streak >= 3:
        return (
            f"連續 {streak} 天熱量都落在赤字目標附近（{target}±100kcal）。"
            "→ 請肯定這個一致性，並給一句「再 X 週可看到 Y」這種前瞻性的話。"
        )

    return ""
