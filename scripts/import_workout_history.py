"""
Import historical workout data from LINE note export.

Usage:
    python scripts/import_workout_history.py

Reads the LINE workout log and inserts parsed workouts into Supabase.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from typing import Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from app.db.client import supabase


def parse_workout_file(filepath: str) -> list[dict]:
    """Parse the LINE workout log into structured workout records."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.split("\n")
    workouts = []
    current_date = None
    current_exercises = []
    current_notes = []
    current_day_label = None
    year = 2026  # default

    def _flush():
        nonlocal current_exercises, current_notes, current_day_label
        if current_date and current_exercises:
            workout_type = _classify_workout(current_exercises, current_day_label)
            workouts.append({
                "created_at": current_date.isoformat(),
                "workout_type": workout_type,
                "exercises": current_exercises,
                "duration_min": None,
                "estimated_calories": None,
                "notes": "\n".join(current_notes) if current_notes else None,
            })
        current_exercises = []
        current_notes = []
        current_day_label = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Skip system messages
        if "已新增新的記事本" in line or "已收回訊息" in line:
            continue

        # Year header: "2026.03.16 星期一"
        year_match = re.match(r"(\d{4})\.\d{2}\.\d{2}", line)
        if year_match:
            year = int(year_match.group(1))
            continue

        # Date line: "18:17 Sophy 1/20" or "19:00 Sophy 3/16 18:20"
        date_match = re.match(r"\d{1,2}:\d{2}\s+Sophy\s+(\d{1,2})/(\d{1,2})(?:\s+(\d{1,2}:\d{2}))?", line)
        if date_match:
            _flush()
            month = int(date_match.group(1))
            day = int(date_match.group(2))
            time_str = date_match.group(3) or "18:00"
            hour, minute = map(int, time_str.split(":"))
            current_date = datetime(year, month, day, hour, minute)
            continue

        # "恢復日" note
        if "恢復日" in line and current_date is None:
            # Sometimes appears before exercises, just note it
            current_notes.append(line)
            continue

        # Day label: "Day 1（升級版🔥）" or "Day 2：上半身（背＋肩）"
        day_match = re.match(r"Day\s*[：:]?\s*(.*)", line, re.IGNORECASE)
        if day_match:
            current_day_label = day_match.group(0).strip()
            continue

        # Exercise line patterns:
        exercise = _parse_exercise_line(line)
        if exercise:
            current_exercises.append(exercise)
            continue

        # Note lines (user observations like "手沒力", "左手很吃力")
        if current_date and len(line) > 2 and not line.startswith("恢復"):
            if any(kw in line for kw in ["力", "痠", "累", "吃力", "感覺", "無法", "退步", "進步", "不知道", "先熟悉", "中間", "雖然", "下次"]):
                current_notes.append(line)
                continue

        # Potential exercise name line (for two-line format)
        # e.g. "Goblet Squat", "啞鈴硬舉（雙手）", "單手啞鈴划船（靠bench）"
        cleaned_check = re.sub(r"^[①②③④⑤⑥⑦⑧]\s*", "", line).strip()
        if current_date and len(cleaned_check) > 1 and not re.match(r"^[0-9]", cleaned_check):
            cleaned = re.sub(r"^[①②③④⑤⑥⑦⑧]\s*", "", line).strip()
            if cleaned and "×" not in cleaned and "x" not in cleaned.lower() and "*" not in cleaned:
                # This looks like an exercise name, save as pending
                current_exercises.append({"name": cleaned, "reps": None, "sets": None, "weight_kg": None})
                continue

    _flush()
    return workouts


def _parse_exercise_line(line: str) -> dict | None:
    """Try to parse a single exercise line into structured data."""
    # Remove leading markers
    line = re.sub(r"^[①②③④⑤⑥⑦⑧]\s*", "", line)
    line = re.sub(r"^[👉→]\s*", "", line)
    line = re.sub(r"^•\s*", "", line)

    # Pattern 1: "硬舉 36kg*8*3" or "深蹲 6kg*10+8kg*10*2+10kg*10*2"
    m1 = re.match(r"(.+?)\s+([\d.]+)kg\*(\d+)\*(\d+)", line)
    if m1:
        return {
            "name": m1.group(1).strip(),
            "weight_kg": float(m1.group(2)),
            "reps": int(m1.group(3)),
            "sets": int(m1.group(4)),
        }

    # Pattern 1b: compound sets "硬舉 20kg*12*3+28kg*6*1"
    m1b = re.match(r"(.+?)\s+([\d.]+kg\*\d+\*\d+(?:\+[\d.]+kg\*\d+\*\d+)*)", line)
    if m1b:
        name = m1b.group(1).strip()
        sets_str = m1b.group(2)
        # Parse first set as main
        first = re.match(r"([\d.]+)kg\*(\d+)\*(\d+)", sets_str)
        if first:
            total_sets = sum(int(s) for s in re.findall(r"\*(\d+)(?:\+|$)", sets_str))
            return {
                "name": name,
                "weight_kg": float(first.group(1)),
                "reps": int(first.group(2)),
                "sets": total_sets or int(first.group(3)),
                "notes": sets_str,
            }

    # Pattern 2: "10 × 4 × 36kg" or "12 × 4 × 14kg"
    m2 = re.match(r"(\d+)\s*[×x]\s*(\d+)\s*[×x]\s*([\d.]+)kg", line)
    if m2:
        return {
            "name": None,  # name comes from previous line
            "reps": int(m2.group(1)),
            "sets": int(m2.group(2)),
            "weight_kg": float(m2.group(3)),
        }

    # Pattern 3: "→ 10下 × 4組 x 36kg" or "→ 12下 × 3組 x (6kg+6kg)"
    m3 = re.match(r"(\d+)下?\s*[×x]\s*(\d+)組?\s*[×x]\s*(?:\(?([\d.]+)kg)?", line)
    if m3:
        weight = float(m3.group(3)) if m3.group(3) else None
        return {
            "name": None,
            "reps": int(m3.group(1)),
            "sets": int(m3.group(2)),
            "weight_kg": weight,
        }

    # Pattern 4: "每腳10 × 3 × 每手 4kg" or "每腳 8–10 × 3 x 每手 4kg"
    m4 = re.match(r"每腳\s*(\d+)[\-–]?(\d*)\s*[×x]\s*(\d+)\s*[×x]?\s*(?:每手\s*)?([\d.]+)?kg?", line)
    if m4:
        return {
            "name": None,
            "reps": int(m4.group(1)),
            "sets": int(m4.group(3)),
            "weight_kg": float(m4.group(4)) if m4.group(4) else None,
            "notes": "每腳",
        }

    # Pattern 5: bodyweight "核心 12*3" or "高姿伏地挺身 5*3"
    m5 = re.match(r"(.+?)\s+(\d+)\*(\d+)$", line)
    if m5 and "kg" not in line:
        return {
            "name": m5.group(1).strip(),
            "reps": int(m5.group(2)),
            "sets": int(m5.group(3)),
            "weight_kg": None,
        }

    # Pattern 6: timed "平板撐 → 50秒 × 3組" or "棒式 30秒"
    m6 = re.match(r"(.+?)\s*[→]?\s*(\d+)秒\s*[×x]?\s*(\d+)?組?", line)
    if m6:
        return {
            "name": m6.group(1).strip(),
            "duration_min": None,
            "reps": None,
            "sets": int(m6.group(3)) if m6.group(3) else 1,
            "weight_kg": None,
            "notes": f"{m6.group(2)}秒",
        }

    # Pattern 7: Named exercise without reps (just a label like "Goblet Squat")
    # Skip these — they're followed by a data line

    return None


def _classify_workout(exercises: list[dict], day_label: str | None) -> str:
    """Classify workout type based on exercises and day label."""
    if day_label:
        label = day_label.lower()
        if any(k in label for k in ["臀腿", "腿", "squat"]):
            return "臀腿"
        if any(k in label for k in ["上半身", "背", "肩", "胸", "核心"]):
            return "上半身"

    names = " ".join(e.get("name", "") or "" for e in exercises).lower()
    if any(k in names for k in ["深蹲", "硬舉", "臀推", "分腿蹲", "squat", "rdl", "goblet"]):
        return "臀腿"
    if any(k in names for k in ["肩推", "胸推", "飛鳥", "划船", "臥推", "二頭"]):
        return "上半身"
    return "全身"


def merge_exercises_with_names(workouts: list[dict]) -> list[dict]:
    """Post-process: merge exercise data lines with their name lines."""
    for workout in workouts:
        exercises = workout["exercises"]
        merged = []
        pending_name = None

        for ex in exercises:
            if ex.get("name") and ex.get("reps") is not None:
                # Complete exercise line
                merged.append(ex)
                pending_name = None
            elif ex.get("name") and ex.get("reps") is None:
                # Name-only line, wait for data
                pending_name = ex["name"]
            elif ex.get("name") is None and pending_name:
                # Data line, merge with pending name
                ex["name"] = pending_name
                merged.append(ex)
                pending_name = None
            else:
                merged.append(ex)
                pending_name = None

        workout["exercises"] = merged
    return workouts


def main():
    filepath = "/Users/sophysmacmini/Downloads/[LINE]重訓紀錄.txt"

    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        sys.exit(1)

    print("Parsing workout history...")
    workouts = parse_workout_file(filepath)
    workouts = merge_exercises_with_names(workouts)

    print(f"Found {len(workouts)} workouts")

    for i, w in enumerate(workouts):
        date_str = w["created_at"][:10]
        ex_count = len(w["exercises"])
        print(f"  {i+1}. {date_str} — {w['workout_type']} ({ex_count} exercises)")
        for ex in w["exercises"]:
            name = ex.get("name", "?")
            weight = ex.get("weight_kg")
            reps = ex.get("reps")
            sets = ex.get("sets")
            parts = [f"    {name}"]
            if weight:
                parts.append(f"{weight}kg")
            if reps and sets:
                parts.append(f"{reps}x{sets}")
            print(" ".join(parts))

    confirm = input(f"\nInsert {len(workouts)} workouts into Supabase? (y/n): ")
    if confirm.lower() != "y":
        print("Aborted.")
        return

    print("Inserting into Supabase...")
    for w in workouts:
        # Ensure exercises is JSON-serializable
        supabase.table("workouts").insert({
            "created_at": w["created_at"],
            "workout_type": w["workout_type"],
            "exercises": w["exercises"],
            "duration_min": w.get("duration_min"),
            "estimated_calories": w.get("estimated_calories"),
            "notes": w.get("notes"),
        }).execute()

    print(f"Done! Inserted {len(workouts)} workouts.")


if __name__ == "__main__":
    main()
