"""Sophy 的 8 週家庭 PPL 課表（2026-05-04 起）。

設備：可調式啞鈴 2-20kg/支、20kg 壺鈴、bench、翹臀圈、拉力帶。
無槓鈴、無彈力帶、無單槓。

雙重漸進：同重量做到 reps 上限且 RIR ≤ 1，下次加重；達不到就維持。
"""
from __future__ import annotations

PPL_PROGRAM = {
    "胸肩": {
        "label": "Push（胸、肩、三頭）",
        "exercises": [
            {"name": "啞鈴臥推（平板）", "sets": 4, "rep_range": "6-10", "rest": "2-3 分", "note": "主項先做"},
            {"name": "啞鈴肩推（坐姿）", "sets": 3, "rep_range": "8-12", "rest": "2 分", "note": "椅背調直"},
            {"name": "啞鈴上斜臥推（30-45°）", "sets": 3, "rep_range": "10-12", "rest": "90 秒", "note": "上胸"},
            {"name": "啞鈴側平舉", "sets": 3, "rep_range": "12-15", "rest": "60 秒", "note": "中三角"},
            {"name": "啞鈴法式彎舉", "sets": 3, "rep_range": "10-12", "rest": "60 秒", "note": "三頭、仰躺或站姿"},
            {"name": "伏地挺身（力竭）", "sets": 2, "rep_range": "AMRAP", "rest": "60 秒", "note": "收尾"},
        ],
    },
    "背": {
        "label": "Pull（背、二頭、後三角）",
        "exercises": [
            {"name": "啞鈴單手划船", "sets": 4, "rep_range": "8-10/邊", "rest": "2 分", "note": "背厚度，下放放慢 3 秒"},
            {"name": "啞鈴硬舉", "sets": 3, "rep_range": "8-10", "rest": "2-3 分", "note": "後鏈整體"},
            {"name": "啞鈴俯身划船（雙手）", "sets": 3, "rep_range": "10-12", "rest": "90 秒", "note": "中背"},
            {"name": "啞鈴俯身飛鳥", "sets": 3, "rep_range": "12-15", "rest": "60 秒", "note": "後三角，輕重量 2-4kg"},
            {"name": "啞鈴二頭彎舉（站姿）", "sets": 3, "rep_range": "10-12", "rest": "60 秒"},
            {"name": "啞鈴錘式彎舉", "sets": 2, "rep_range": "12-15", "rest": "60 秒", "note": "肱肌+前臂"},
        ],
    },
    "臀腿": {
        "label": "Legs（股四、臀、腿後、小腿）",
        "exercises": [
            {"name": "高腳杯深蹲（壺鈴/啞鈴）", "sets": 4, "rep_range": "8-12", "rest": "2-3 分", "note": "蹲到大腿平行"},
            {"name": "啞鈴 RDL（羅馬尼亞硬舉）", "sets": 4, "rep_range": "8-10", "rest": "2 分", "note": "離心慢，腿後+臀"},
            {"name": "啞鈴保加利亞分腿蹲", "sets": 3, "rep_range": "8-10/邊", "rest": "90 秒", "note": "後腳放椅子上"},
            {"name": "啞鈴臀推（背靠 bench）", "sets": 3, "rep_range": "10-12", "rest": "90 秒", "note": "啞鈴放髖部"},
            {"name": "啞鈴登階（用 bench）", "sets": 3, "rep_range": "10/邊", "rest": "60 秒", "note": "bench 約 40-50cm"},
            {"name": "站姿提踵（單手扶牆，負重）", "sets": 3, "rep_range": "15-20", "rest": "60 秒", "note": "小腿"},
        ],
    },
}


def get_program_for_muscle_group(muscle_group: str) -> dict | None:
    """Return today's program for the given muscle group, or None if no template."""
    return PPL_PROGRAM.get(muscle_group)


def format_program_block(muscle_group: str) -> str | None:
    """Render today's PPL program as a text block. None if muscle_group has no template."""
    prog = get_program_for_muscle_group(muscle_group)
    if not prog:
        return None
    lines = [f"📋 今日課表：{prog['label']}"]
    for i, ex in enumerate(prog["exercises"], 1):
        sets = ex["sets"]
        reps = ex["rep_range"]
        note = ex.get("note")
        line = f"{i}. {ex['name']} {sets}×{reps}"
        if note:
            line += f"（{note}）"
        lines.append(line)
    lines.append("")
    lines.append("💡 雙重漸進：同重量做到區間上限且 RIR ≤ 1 → 下次加重")
    return "\n".join(lines)
