from linebot.v3.messaging import TextMessage, QuickReply, QuickReplyItem

from app.line.confirm import build_confirm_card, build_quick_reply_prompt


def test_build_confirm_card_returns_text_message():
    msg = build_confirm_card(
        title="🍽 午餐草稿",
        lines=["• 蒸蛋 80kcal", "• 飯糰 250kcal"],
        total="合計：330kcal｜蛋白質 18g",
    )
    assert isinstance(msg, TextMessage)
    assert "午餐草稿" in msg.text
    assert "蒸蛋" in msg.text
    assert "330kcal" in msg.text


def test_build_confirm_card_has_three_quick_reply_buttons():
    msg = build_confirm_card(
        title="🍽 午餐草稿",
        lines=["• 蒸蛋 80kcal"],
        total="合計：80kcal",
    )
    assert msg.quick_reply is not None
    assert len(msg.quick_reply.items) == 3
    labels = [item.action.label for item in msg.quick_reply.items]
    assert "✅ 儲存" in labels
    assert "❌ 取消" in labels
    assert "✏️ 修改" in labels


def test_build_quick_reply_prompt_returns_text_message_with_buttons():
    msg = build_quick_reply_prompt(
        text="這餐是？",
        options=[("早餐", "__meal_breakfast__"), ("午餐", "__meal_lunch__"),
                 ("晚餐", "__meal_dinner__"), ("點心", "__meal_snack__")],
    )
    assert isinstance(msg, TextMessage)
    assert "這餐是" in msg.text
    labels = [item.action.label for item in msg.quick_reply.items]
    assert "早餐" in labels
    assert "午餐" in labels


def test_sentinel_constants_are_defined():
    from app.line.confirm import (
        CONFIRM_SENTINEL, CANCEL_SENTINEL, EDIT_SENTINEL,
        NOTES_SKIP_SENTINEL, MEAL_SENTINELS, MEAL_TYPE_MAP, MEAL_TYPE_DB
    )
    assert CONFIRM_SENTINEL == "__confirm__"
    assert CANCEL_SENTINEL == "__cancel__"
    assert EDIT_SENTINEL == "__edit__"
    assert NOTES_SKIP_SENTINEL == "__notes_skip__"
    assert MEAL_SENTINELS["早餐"] == "__meal_breakfast__"
    assert MEAL_TYPE_MAP["__meal_lunch__"] == "午餐"
    assert MEAL_TYPE_DB["__meal_dinner__"] == "dinner"
