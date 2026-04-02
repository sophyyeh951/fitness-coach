"""Generate trend charts as images for LINE."""

from __future__ import annotations

import io
import logging
from datetime import date, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from app.db import queries as db

logger = logging.getLogger(__name__)

# Use a font that supports CJK characters
plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "Heiti TC", "PingFang TC", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False


def generate_weight_trend(days: int = 30) -> bytes | None:
    """Generate a weight/body fat trend chart. Returns PNG bytes or None."""
    end = date.today()
    start = end - timedelta(days=days)
    metrics = db.get_body_metrics_range(start, end)

    if not metrics:
        return None

    dates = []
    weights = []
    body_fats = []

    for m in metrics:
        d = date.fromisoformat(m["date"]) if isinstance(m["date"], str) else m["date"]
        dates.append(d)
        weights.append(m.get("weight"))
        body_fats.append(m.get("body_fat_pct"))

    fig, ax1 = plt.subplots(figsize=(8, 4))

    # Plot weight
    w_dates = [d for d, w in zip(dates, weights) if w is not None]
    w_vals = [w for w in weights if w is not None]
    if w_vals:
        ax1.plot(w_dates, w_vals, "b-o", markersize=4, label="體重 (kg)")
        ax1.set_ylabel("體重 (kg)", color="blue")
        ax1.tick_params(axis="y", labelcolor="blue")

    # Plot body fat on secondary axis
    bf_dates = [d for d, bf in zip(dates, body_fats) if bf is not None]
    bf_vals = [bf for bf in body_fats if bf is not None]
    if bf_vals:
        ax2 = ax1.twinx()
        ax2.plot(bf_dates, bf_vals, "r-s", markersize=4, label="體脂 (%)")
        ax2.set_ylabel("體脂 (%)", color="red")
        ax2.tick_params(axis="y", labelcolor="red")

    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax1.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
    fig.autofmt_xdate()

    ax1.set_title(f"體重 / 體脂趨勢（近 {days} 天）")
    ax1.grid(True, alpha=0.3)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def generate_calorie_trend(days: int = 7) -> bytes | None:
    """Generate a daily calorie intake trend chart. Returns PNG bytes or None."""
    end = date.today()
    start = end - timedelta(days=days)

    dates = []
    calories = []
    proteins = []

    current = start
    while current <= end:
        summary = db.get_daily_summary(current)
        if summary and summary.get("total_calories_in"):
            dates.append(current)
            calories.append(summary["total_calories_in"])
            proteins.append(summary.get("total_protein", 0))
        current += timedelta(days=1)

    if not dates:
        return None

    fig, ax1 = plt.subplots(figsize=(8, 4))

    ax1.bar(dates, calories, color="steelblue", alpha=0.7, label="熱量 (kcal)")
    ax1.set_ylabel("熱量 (kcal)")

    # Add protein line on secondary axis
    if any(p > 0 for p in proteins):
        ax2 = ax1.twinx()
        ax2.plot(dates, proteins, "go-", markersize=5, label="蛋白質 (g)")
        ax2.set_ylabel("蛋白質 (g)", color="green")
        ax2.tick_params(axis="y", labelcolor="green")

    # Show calorie target line if available
    goal = db.get_active_goal()
    if goal and goal.get("daily_calorie_target"):
        ax1.axhline(
            y=goal["daily_calorie_target"],
            color="red",
            linestyle="--",
            alpha=0.7,
            label=f"目標 {goal['daily_calorie_target']} kcal",
        )
        ax1.legend(loc="upper left")

    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    fig.autofmt_xdate()

    ax1.set_title(f"每日攝取趨勢（近 {days} 天）")
    ax1.grid(True, alpha=0.3, axis="y")
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf.read()
