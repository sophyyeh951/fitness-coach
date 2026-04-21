"""Reusable builders for LINE confirm cards and quick-reply prompts.

All logging commands return a TextMessage with QuickReply buttons
instead of saving directly. The user must tap ✅ to confirm a save.

Special sentinel values (tapped by user as quick reply):
  __confirm__          — user tapped ✅ 儲存
  __cancel__           — user tapped ❌ 取消
  __edit__             — user tapped ✏️ 修改
  __meal_breakfast__   — user selected 早餐
  __meal_lunch__       — user selected 午餐
  __meal_dinner__      — user selected 晚餐
  __meal_snack__       — user selected 點心
  __notes_skip__       — user skips the post-workout notes prompt
"""

from __future__ import annotations

from linebot.v3.messaging import (
    MessageAction,
    QuickReply,
    QuickReplyItem,
    TextMessage,
)

CONFIRM_SENTINEL = "__confirm__"
CANCEL_SENTINEL = "__cancel__"
EDIT_SENTINEL = "__edit__"
NOTES_SKIP_SENTINEL = "__notes_skip__"

MEAL_SENTINELS = {
    "早餐": "__meal_breakfast__",
    "午餐": "__meal_lunch__",
    "晚餐": "__meal_dinner__",
    "點心": "__meal_snack__",
}

MEAL_TYPE_MAP = {v: k for k, v in MEAL_SENTINELS.items()}
MEAL_TYPE_DB = {
    "__meal_breakfast__": "breakfast",
    "__meal_lunch__": "lunch",
    "__meal_dinner__": "dinner",
    "__meal_snack__": "snack",
}

# Exercise type selection — used by /動 quick reply.
EXERCISE_SENTINELS = {
    "羽球": "__ex_badminton__",
    "重訓": "__ex_strength__",
    "游泳": "__ex_swim__",
    "跑步": "__ex_run__",
    "其他": "__ex_other__",
}
EXERCISE_TYPE_MAP = {v: k for k, v in EXERCISE_SENTINELS.items()}

DIVIDER = "━━━━━━━━━━━━━━━"


def build_confirm_card(title: str, lines: list[str], total: str) -> TextMessage:
    """Build a confirm card TextMessage with ✅/❌/✏️ quick reply buttons."""
    body = "\n".join([DIVIDER, title] + lines + [total, DIVIDER])
    return TextMessage(
        text=body,
        quick_reply=QuickReply(items=[
            QuickReplyItem(action=MessageAction(label="✅ 儲存", text=CONFIRM_SENTINEL)),
            QuickReplyItem(action=MessageAction(label="❌ 取消", text=CANCEL_SENTINEL)),
            QuickReplyItem(action=MessageAction(label="✏️ 修改", text=EDIT_SENTINEL)),
        ]),
    )


def build_quick_reply_prompt(
    text: str,
    options: list[tuple[str, str]],  # [(label, sentinel_text), ...]
) -> TextMessage:
    """Build a prompt message with custom quick reply buttons."""
    items = [
        QuickReplyItem(action=MessageAction(label=label, text=sentinel))
        for label, sentinel in options
    ]
    return TextMessage(text=text, quick_reply=QuickReply(items=items))
