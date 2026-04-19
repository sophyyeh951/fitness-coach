# Command Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the free-text chatbot's silent-save behavior with an explicit command system, confirm-before-save cards, and session-aware multi-turn flows — eliminating the 41% correction rate found in chat history analysis.

**Architecture:** Each command (e.g. `/吃`, `/動`) sets a session mode in Supabase that persists across messages. Subsequent messages are routed by session mode instead of AI intent-guessing. All logging requires a confirm card tap before data is written. Q&A (no command) never logs anything.

**Tech Stack:** FastAPI, Python 3.11+, Supabase (PostgreSQL + REST client), LINE Messaging API v3 (linebot-sdk v3), APScheduler, Google Gemini (existing), pytest + pytest-asyncio

---

## File Structure

### New files
| File | Responsibility |
|---|---|
| `migrations/006_user_sessions.sql` | Session state table schema |
| `app/line/session.py` | Read/write session state to Supabase |
| `app/line/confirm.py` | Build LINE TextMessage with QuickReply buttons |
| `app/line/commands/__init__.py` | Command registry — maps command strings to handler functions |
| `app/line/commands/meal.py` | `/吃` multi-turn flow (meal type → food input → draft → confirm) |
| `app/line/commands/exercise.py` | `/動` flow (cardio instant + weight training list) |
| `app/line/commands/body.py` | `/身體` body composition photo flow |
| `app/line/commands/simple.py` | `/休息`, `/?` — single-turn commands |
| `app/line/commands/today.py` | `/今日` — today's log with IDs |
| `app/line/commands/next_session.py` | `/下次` — next session suggestion based on notes |
| `app/line/commands/report.py` | `/週報` — 7-day rolling summary |
| `app/line/commands/schedule.py` | `/計畫` — view/update weekly exercise schedule |
| `app/db/schedule.py` | Schedule read/write queries |
| `tests/__init__.py` | Test package |
| `tests/conftest.py` | Shared pytest fixtures |
| `tests/test_session.py` | Session state unit tests |
| `tests/test_confirm.py` | Confirm card builder tests |
| `tests/test_commands_meal.py` | `/吃` flow tests |
| `tests/test_commands_exercise.py` | `/動` flow tests |
| `tests/test_commands_simple.py` | Simple commands tests |

### Modified files
| File | Change |
|---|---|
| `app/line/handlers.py` | Add session-first routing; return `Message \| str` |
| `app/line/webhook.py` | Accept `Message \| str` from handler |
| `app/main.py` | Add Sunday `/週報` scheduler job |
| `app/ai/coach.py` | Add `ask_coach_qa_only()` — guaranteed no logging |
| `app/ai/prompts.py` | Add draft correction prompt |
| `app/db/queries.py` | Add `get_workouts_by_type()` for `/下次` |

---

## Phase 1 — Infrastructure

### Task 1: DB migration — user_sessions table

**Files:**
- Create: `migrations/006_user_sessions.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- migrations/006_user_sessions.sql
CREATE TABLE IF NOT EXISTS user_sessions (
    user_id TEXT PRIMARY KEY,
    mode    TEXT NOT NULL,
    draft   JSONB NOT NULL DEFAULT '{}',
    expires_at TIMESTAMPTZ NOT NULL
);

-- Automatically clean up expired sessions (optional index)
CREATE INDEX IF NOT EXISTS idx_user_sessions_expires ON user_sessions(expires_at);
```

- [ ] **Step 2: Run the migration in Supabase**

Go to Supabase dashboard → SQL Editor → paste and run the migration.
Verify: `SELECT * FROM user_sessions;` returns empty table with no error.

- [ ] **Step 3: Commit**

```bash
git add migrations/006_user_sessions.sql
git commit -m "feat: add user_sessions table for multi-turn command state"
```

---

### Task 2: Session state module

**Files:**
- Create: `app/line/session.py`
- Create: `tests/__init__.py`, `tests/conftest.py`, `tests/test_session.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/__init__.py
# (empty)
```

```python
# tests/conftest.py
import pytest
from unittest.mock import MagicMock, patch

@pytest.fixture
def mock_supabase():
    """Mock Supabase client for unit tests."""
    with patch("app.db.client.supabase") as mock:
        yield mock
```

```python
# tests/test_session.py
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, AsyncMock


def _make_session_row(mode="awaiting_meal_type", draft=None, minutes_from_now=30):
    expires = datetime.now(timezone.utc) + timedelta(minutes=minutes_from_now)
    return {
        "user_id": "U123",
        "mode": mode,
        "draft": draft or {},
        "expires_at": expires.isoformat(),
    }


def test_get_session_returns_none_when_not_found():
    with patch("app.line.session.supabase") as mock_sb:
        mock_sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
        from app.line.session import get_session
        result = get_session("U123")
    assert result is None


def test_get_session_returns_none_when_expired():
    row = _make_session_row(minutes_from_now=-1)  # expired 1 minute ago
    with patch("app.line.session.supabase") as mock_sb:
        mock_sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [row]
        from app.line.session import get_session
        result = get_session("U123")
    assert result is None


def test_get_session_returns_session_when_valid():
    row = _make_session_row(mode="awaiting_food", draft={"meal_type": "lunch"})
    with patch("app.line.session.supabase") as mock_sb:
        mock_sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [row]
        from app.line.session import get_session
        result = get_session("U123")
    assert result is not None
    assert result["mode"] == "awaiting_food"
    assert result["draft"]["meal_type"] == "lunch"


def test_set_session_upserts_with_expiry():
    with patch("app.line.session.supabase") as mock_sb:
        mock_sb.table.return_value.upsert.return_value.execute.return_value.data = [{}]
        from app.line.session import set_session
        set_session("U123", mode="awaiting_food", draft={"meal_type": "lunch"})

    call_args = mock_sb.table.return_value.upsert.call_args[0][0]
    assert call_args["user_id"] == "U123"
    assert call_args["mode"] == "awaiting_food"
    assert call_args["draft"]["meal_type"] == "lunch"
    assert "expires_at" in call_args


def test_clear_session_deletes_row():
    with patch("app.line.session.supabase") as mock_sb:
        mock_sb.table.return_value.delete.return_value.eq.return_value.execute.return_value.data = [{}]
        from app.line.session import clear_session
        clear_session("U123")

    mock_sb.table.return_value.delete.return_value.eq.assert_called_once_with("user_id", "U123")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/sophysmacmini/Documents/fitness-coach
python -m pytest tests/test_session.py -v 2>&1 | head -30
```
Expected: `ModuleNotFoundError: No module named 'app.line.session'`

- [ ] **Step 3: Implement session module**

```python
# app/line/session.py
"""Session state for multi-turn LINE command flows.

Stores the current mode and draft data in Supabase so state
survives server restarts (Render free tier restarts frequently).

Modes:
  awaiting_meal_type     — sent /吃, waiting for user to tap meal type
  awaiting_food          — meal type chosen, waiting for photo or text
  awaiting_meal_confirm  — draft built, waiting for ✅/❌/correction
  awaiting_exercise_list — sent /動 for weight training, waiting for exercise list
  awaiting_exercise_confirm — exercise draft built, waiting for confirm
  awaiting_body_confirm  — body photo parsed, waiting for confirm
  awaiting_notes         — exercise saved, waiting for post-workout note
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from app.db.client import supabase

logger = logging.getLogger(__name__)

SESSION_TTL_MINUTES = 60  # Sessions expire after 60 minutes of inactivity


def get_session(user_id: str) -> dict | None:
    """Return the active session for user_id, or None if not found / expired."""
    result = (
        supabase.table("user_sessions")
        .select("*")
        .eq("user_id", user_id)
        .execute()
    )
    if not result.data:
        return None

    row = result.data[0]
    expires_at = datetime.fromisoformat(row["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at < datetime.now(timezone.utc):
        clear_session(user_id)
        return None

    return row


def set_session(user_id: str, mode: str, draft: dict | None = None) -> None:
    """Create or update the session for user_id."""
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=SESSION_TTL_MINUTES)
    supabase.table("user_sessions").upsert({
        "user_id": user_id,
        "mode": mode,
        "draft": draft or {},
        "expires_at": expires_at.isoformat(),
    }).execute()
    logger.debug("Session set: user=%s mode=%s", user_id, mode)


def clear_session(user_id: str) -> None:
    """Delete the session for user_id."""
    supabase.table("user_sessions").delete().eq("user_id", user_id).execute()
    logger.debug("Session cleared: user=%s", user_id)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_session.py -v
```
Expected: all 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/line/session.py tests/__init__.py tests/conftest.py tests/test_session.py
git commit -m "feat: add session state module for multi-turn command flows"
```

---

### Task 3: Confirm card builder

**Files:**
- Create: `app/line/confirm.py`
- Create: `tests/test_confirm.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_confirm.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_confirm.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'app.line.confirm'`

- [ ] **Step 3: Implement confirm card builder**

```python
# app/line/confirm.py
"""Reusable builders for LINE confirm cards and quick-reply prompts.

All logging commands return a TextMessage with QuickReply buttons
instead of saving directly. The user must tap ✅ to confirm a save.

Special sentinel values (tapped by user as quick reply):
  __confirm__   — user tapped ✅ 儲存
  __cancel__    — user tapped ❌ 取消
  __edit__      — user tapped ✏️ 修改 (bot prompts for correction text)
  __meal_breakfast__ / __meal_lunch__ / __meal_dinner__ / __meal_snack__
  __notes_skip__  — user skips the post-workout notes prompt
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_confirm.py -v
```
Expected: all 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/line/confirm.py tests/test_confirm.py
git commit -m "feat: add confirm card builder with quick reply buttons"
```

---

### Task 4: Update webhook and handler to support Message returns

**Files:**
- Modify: `app/line/handlers.py`
- Modify: `app/line/webhook.py`
- Create: `app/line/commands/__init__.py`

- [ ] **Step 1: Create the commands package**

```python
# app/line/commands/__init__.py
"""Command handlers for explicit /command flows."""
```

- [ ] **Step 2: Update `handlers.py` — session-first routing**

Replace the entire `handle_text_message` function (keep all other functions unchanged):

```python
# In app/line/handlers.py — add these imports at the top:
from linebot.v3.messaging import TextMessage as LineTextMessage

from app.line.session import get_session, clear_session
from app.line.confirm import (
    CONFIRM_SENTINEL, CANCEL_SENTINEL, EDIT_SENTINEL,
    MEAL_SENTINELS, NOTES_SKIP_SENTINEL,
)

# Replace handle_text_message with:
async def handle_text_message(text: str, user_id: str = "default") -> str | LineTextMessage:
    """Handle incoming text messages from LINE.

    Returns either a plain str (for Q&A replies) or a LineTextMessage
    (for confirm cards / quick-reply prompts). webhook.py handles both.
    """
    text = text.strip()

    # 1. Session continuation — check active multi-turn flow first
    session = get_session(user_id)
    if session:
        return await _handle_session(text, session, user_id)

    # 2. Slash command dispatch
    if text.startswith("/") or text == "/?":
        return await _handle_command(text, user_id)

    # 3. Q&A only — NEVER logs anything
    return await ask_coach_qa_only(text)
```

- [ ] **Step 3: Add `_handle_session` dispatcher to `handlers.py`**

Add this function after `handle_text_message`:

```python
async def _handle_session(text: str, session: dict, user_id: str) -> str | LineTextMessage:
    """Route a message to the correct session handler based on current mode."""
    from app.line.commands.meal import (
        handle_meal_type_selection,
        handle_food_input,
        handle_meal_confirm,
        handle_meal_correction,
    )
    from app.line.commands.exercise import (
        handle_exercise_list_input,
        handle_exercise_confirm,
        handle_notes_input,
    )
    from app.line.commands.body import handle_body_confirm

    mode = session["mode"]
    draft = session.get("draft", {})

    # Meal flow
    if mode == "awaiting_meal_type":
        return await handle_meal_type_selection(text, user_id)
    if mode == "awaiting_food":
        return await handle_food_input(text, draft, user_id)
    if mode == "awaiting_meal_confirm":
        if text == CONFIRM_SENTINEL:
            return await handle_meal_confirm(draft, user_id)
        if text == CANCEL_SENTINEL:
            clear_session(user_id)
            return "已取消，沒有儲存任何資料。"
        if text == EDIT_SENTINEL:
            return "好，告訴我要改什麼？"
        # Any other text = correction
        return await handle_meal_correction(text, draft, user_id)

    # Exercise flow
    if mode == "awaiting_exercise_list":
        return await handle_exercise_list_input(text, draft, user_id)
    if mode == "awaiting_exercise_confirm":
        if text == CONFIRM_SENTINEL:
            return await handle_exercise_confirm(draft, user_id)
        if text == CANCEL_SENTINEL:
            clear_session(user_id)
            return "已取消，沒有儲存任何資料。"
        if text == EDIT_SENTINEL:
            return "好，告訴我要改什麼？"
        return await handle_exercise_list_input(text, draft, user_id)

    # Notes prompt
    if mode == "awaiting_notes":
        if text == NOTES_SKIP_SENTINEL:
            clear_session(user_id)
            return "好，這次不記備註。"
        return await handle_notes_input(text, draft, user_id)

    # Body data flow
    if mode == "awaiting_body_confirm":
        if text == CONFIRM_SENTINEL:
            return await handle_body_confirm(draft, user_id)
        if text == CANCEL_SENTINEL:
            clear_session(user_id)
            return "已取消，沒有儲存任何資料。"
        return "請點選下方按鈕確認或取消。"

    # Unknown mode — clear and fall through
    clear_session(user_id)
    return await ask_coach_qa_only(text)
```

- [ ] **Step 4: Update `_handle_command` in `handlers.py`**

Replace the existing `_handle_command` function:

```python
async def _handle_command(text: str, user_id: str) -> str | LineTextMessage:
    """Dispatch slash commands to their handlers."""
    from app.line.commands.meal import start_meal_flow
    from app.line.commands.exercise import start_exercise_flow
    from app.line.commands.body import start_body_flow
    from app.line.commands.simple import handle_rest, handle_help
    from app.line.commands.today import handle_today
    from app.line.commands.next_session import handle_next_session
    from app.line.commands.report import handle_weekly_report
    from app.line.commands.schedule import handle_schedule

    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    args = parts[1].strip() if len(parts) > 1 else ""

    dispatch = {
        "/吃": lambda: start_meal_flow(user_id),
        "/動": lambda: start_exercise_flow(args, user_id),
        "/身體": lambda: start_body_flow(user_id),
        "/休息": lambda: handle_rest(args, user_id),
        "/今日": lambda: handle_today(),
        "/下次": lambda: handle_next_session(args),
        "/週報": lambda: handle_weekly_report(),
        "/計畫": lambda: handle_schedule(args, user_id),
        "/?": lambda: handle_help(),
    }

    handler = dispatch.get(cmd)
    if handler:
        return await handler()

    return f"未知指令：{cmd}\n輸入 /? 查看所有指令"
```

- [ ] **Step 5: Add `ask_coach_qa_only` to `app/ai/coach.py`**

Open `app/ai/coach.py` and add this function after the existing `ask_coach` function:

```python
async def ask_coach_qa_only(question: str) -> str:
    """Q&A only mode — answers questions but NEVER logs food/workout data.

    This is the default handler for all free-text messages (no command prefix).
    The prompt explicitly forbids the model from triggering any logging.
    """
    context = _build_full_context()
    prompt = QA_ONLY_QUERY_TEMPLATE.format(
        system_context=COACH_SYSTEM_PROMPT,
        user_profile=context["profile"],
        active_context=context["active"],
        recent_workouts=context["workouts"],
        user_data=context["today"],
        chat_history=context["history"],
        question=question,
    )
    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.7),
        )
        reply = response.text.strip()
        save_chat_message("user", question)
        save_chat_message("assistant", reply)
        return reply
    except Exception:
        logger.exception("Q&A coach failed")
        return "抱歉，我現在無法回答，請稍後再試。"
```

- [ ] **Step 6: Add `QA_ONLY_QUERY_TEMPLATE` to `app/ai/prompts.py`**

Add at the end of `app/ai/prompts.py`:

```python
QA_ONLY_QUERY_TEMPLATE = """\
{system_context}

重要規則：這是純問答模式。不論用戶說什麼，你都不能記錄飲食、訓練或身體數據。
如果用戶提到食物（如「我吃了一個便當」），只提供營養資訊，並說：「要記錄的話用 /吃」。
如果用戶提到運動，只給建議，不記錄，並說：「要記錄的話用 /動」。
絕對不要輸出任何 [DELETE_MEAL:] [UPDATE_MEAL:] [DELETE_WORKOUT:] 等指令標記。

--- 我的基本資料 ---
{user_profile}

--- 近期情境筆記 ---
{active_context}

--- 最近訓練紀錄 ---
{recent_workouts}

--- 今日數據 ---
{user_data}

--- 最近對話 ---
{chat_history}

--- 我剛說的 ---
{question}

（直接回覆，不要打招呼，不要記錄任何資料）
"""
```

- [ ] **Step 7: Update `webhook.py` to handle `Message | str` returns**

In `app/line/webhook.py`, update the `_process_event` function. Find the section that calls `handle_text_message` and replace it:

```python
# Replace this block in _process_event:
if isinstance(event.message, TextMessageContent):
    logger.info("Processing text: %s", event.message.text[:50])
    reply_text = await handle_text_message(event.message.text)
elif isinstance(event.message, ImageMessageContent):
    ...

# With this:
if isinstance(event.message, TextMessageContent):
    logger.info("Processing text: %s", event.message.text[:50])
    user_id = event.source.user_id if hasattr(event.source, "user_id") else LINE_USER_ID
    result = await handle_text_message(event.message.text, user_id)
elif isinstance(event.message, ImageMessageContent):
    logger.info("Processing image: %s", event.message.id)
    user_id = event.source.user_id if hasattr(event.source, "user_id") else LINE_USER_ID
    blob_api = get_line_blob_api()
    result = await handle_image_message(event.message.id, blob_api, user_id)
else:
    result = "目前支援文字和圖片訊息喔！"
```

Then replace the message-building section:

```python
# Replace this:
messages = _split_message(reply_text, max_len=4500)
# ...
messages=[TextMessage(text=m) for m in messages[:5]],

# With this:
from linebot.v3.messaging import Message as LineMessage
if isinstance(result, LineMessage):
    # Already a Message object (confirm card, quick reply prompt)
    reply_messages = [result]
else:
    # Plain string — split if long, wrap in TextMessage
    parts = _split_message(result, max_len=4500)
    reply_messages = [TextMessage(text=p) for p in parts[:5]]
```

Also update the reply call:
```python
await line_api.reply_message(
    ReplyMessageRequest(
        reply_token=event.reply_token,
        messages=reply_messages,
    )
)
```

And the push fallback:
```python
for msg in reply_messages:
    await line_api.push_message(
        PushMessageRequest(to=LINE_USER_ID, messages=[msg])
    )
```

Also update `handle_image_message` signature in `handlers.py` to accept `user_id`:
```python
async def handle_image_message(
    message_id: str,
    blob_api: AsyncMessagingApiBlob,
    user_id: str = "default",
) -> str | LineTextMessage:
```

- [ ] **Step 8: Commit**

```bash
git add app/line/handlers.py app/line/webhook.py app/line/commands/__init__.py \
        app/ai/coach.py app/ai/prompts.py
git commit -m "feat: session-first routing, Q&A-only mode, Message return type"
```

---

## Phase 2 — Logging Commands

### Task 5: `/吃` — Meal logging flow

**Files:**
- Create: `app/line/commands/meal.py`
- Create: `tests/test_commands_meal.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_commands_meal.py
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from linebot.v3.messaging import TextMessage

from app.line.confirm import MEAL_SENTINELS


@pytest.mark.asyncio
async def test_start_meal_flow_returns_meal_type_prompt():
    with patch("app.line.session.supabase"):
        from app.line.commands.meal import start_meal_flow
        result = await start_meal_flow("U123")

    assert isinstance(result, TextMessage)
    assert "這餐是" in result.text
    assert result.quick_reply is not None
    labels = [item.action.label for item in result.quick_reply.items]
    assert "早餐" in labels
    assert "午餐" in labels
    assert "晚餐" in labels
    assert "點心" in labels


@pytest.mark.asyncio
async def test_handle_meal_type_selection_sets_session():
    with patch("app.line.commands.meal.set_session") as mock_set, \
         patch("app.line.commands.meal.get_session", return_value={"mode": "awaiting_meal_type", "draft": {}}):
        from app.line.commands.meal import handle_meal_type_selection
        result = await handle_meal_type_selection("__meal_lunch__", "U123")

    mock_set.assert_called_once_with("U123", mode="awaiting_food", draft={"meal_type": "lunch", "meal_type_display": "午餐"})
    assert isinstance(result, str)
    assert "午餐" in result


@pytest.mark.asyncio
async def test_handle_meal_confirm_saves_and_clears_session():
    draft = {
        "meal_type": "lunch",
        "meal_type_display": "午餐",
        "foods": [{"name": "蒸蛋", "calories": 80, "protein": 8, "carbs": 1, "fat": 5, "portion": "1份"}],
        "total_calories": 80,
        "total_protein": 8,
        "total_carbs": 1,
        "total_fat": 5,
    }
    with patch("app.line.commands.meal.db") as mock_db, \
         patch("app.line.commands.meal.clear_session") as mock_clear:
        mock_db.insert_meal.return_value = {"id": 42}
        from app.line.commands.meal import handle_meal_confirm
        result = await handle_meal_confirm(draft, "U123")

    mock_db.insert_meal.assert_called_once()
    mock_clear.assert_called_once_with("U123")
    assert "已儲存" in result or "午餐" in result
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_commands_meal.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'app.line.commands.meal'`

- [ ] **Step 3: Install pytest-asyncio if not present**

```bash
pip install pytest-asyncio
echo "[pytest]
asyncio_mode = auto" > pytest.ini
```

- [ ] **Step 4: Implement meal command**

```python
# app/line/commands/meal.py
"""
/吃 command — multi-turn meal logging flow.

Flow:
  1. User sends /吃
     → set_session(mode=awaiting_meal_type)
     → bot sends meal type quick reply [早餐][午餐][晚餐][點心]

  2. User taps a meal type button (e.g. __meal_lunch__)
     → set_session(mode=awaiting_food, draft={meal_type: lunch})
     → bot asks for food

  3. User sends text description
     → AI parses food → build draft
     → set_session(mode=awaiting_meal_confirm, draft={...})
     → bot sends confirm card

  4a. User taps ✅  → save to DB, clear session
  4b. User taps ❌  → clear session, nothing saved
  4c. User sends correction text → AI re-parses → update draft → show new confirm card
"""

from __future__ import annotations

import asyncio
import json
import logging

from linebot.v3.messaging import TextMessage

from app.db import queries as db
from app.line.confirm import (
    MEAL_SENTINELS, MEAL_TYPE_DB, MEAL_TYPE_MAP,
    build_confirm_card, build_quick_reply_prompt,
)
from app.line.session import clear_session, get_session, set_session
from app.ai.food_analyzer import parse_food_text

logger = logging.getLogger(__name__)


async def start_meal_flow(user_id: str) -> TextMessage:
    """Entry point for /吃 — sets session and asks for meal type."""
    set_session(user_id, mode="awaiting_meal_type")
    return build_quick_reply_prompt(
        text="這餐是？",
        options=[(label, sentinel) for label, sentinel in MEAL_SENTINELS.items()],
    )


async def handle_meal_type_selection(text: str, user_id: str) -> str | TextMessage:
    """Handle meal type button tap (e.g. __meal_lunch__)."""
    if text not in MEAL_TYPE_DB:
        # Not a valid sentinel — treat as unknown
        return "請點選下方的餐別按鈕 👇"

    db_type = MEAL_TYPE_DB[text]
    display = MEAL_TYPE_MAP[text]
    set_session(user_id, mode="awaiting_food", draft={
        "meal_type": db_type,
        "meal_type_display": display,
    })
    return f"好，{display}。\n傳照片或告訴我吃什麼 👇"


async def handle_food_input(text: str, draft: dict, user_id: str) -> TextMessage:
    """Parse food text and build the confirm card draft."""
    meal_type = draft.get("meal_type", "other")
    display = draft.get("meal_type_display", "")

    parsed = await parse_food_text(text)
    new_draft = {**draft, **parsed}

    set_session(user_id, mode="awaiting_meal_confirm", draft=new_draft)
    return _build_meal_confirm_card(new_draft, display)


async def handle_meal_correction(correction: str, draft: dict, user_id: str) -> TextMessage:
    """Apply a user correction to the existing draft and rebuild the confirm card."""
    display = draft.get("meal_type_display", "")
    correction_prompt = (
        f"目前的飲食草稿：\n{json.dumps(draft, ensure_ascii=False)}\n\n"
        f"用戶說要修改：「{correction}」\n\n"
        f"請根據修改重新輸出完整的 JSON（同樣格式，不要 markdown）"
    )
    parsed = await parse_food_text(correction_prompt, is_correction=True)
    new_draft = {**draft, **parsed}
    set_session(user_id, mode="awaiting_meal_confirm", draft=new_draft)
    return _build_meal_confirm_card(new_draft, display, updated=True)


async def handle_meal_confirm(draft: dict, user_id: str) -> str:
    """Save confirmed draft to database."""
    try:
        db.insert_meal(
            photo_url=None,
            food_items=draft.get("foods", []),
            total_calories=draft.get("total_calories", 0),
            protein=draft.get("total_protein", 0),
            carbs=draft.get("total_carbs", 0),
            fat=draft.get("total_fat", 0),
            ai_response="",
            source="text",
            meal_type=draft.get("meal_type", "other"),
        )
        clear_session(user_id)
        display = draft.get("meal_type_display", "")
        kcal = draft.get("total_calories", 0)
        return f"✅ {display}已儲存！合計 {kcal:.0f}kcal"
    except Exception:
        logger.exception("Failed to save meal")
        return "儲存失敗，請再試一次 🙏"


def _build_meal_confirm_card(draft: dict, display: str, updated: bool = False) -> TextMessage:
    foods = draft.get("foods", [])
    lines = [
        f"• {f['name']} {f.get('portion', '')} {f.get('calories', 0):.0f}kcal"
        for f in foods
    ]
    total_kcal = draft.get("total_calories", 0)
    total_protein = draft.get("total_protein", 0)
    total_carbs = draft.get("total_carbs", 0)
    total_fat = draft.get("total_fat", 0)
    title = f"🍽 {display}草稿{'（已更新）' if updated else ''}"
    total_str = f"合計：{total_kcal:.0f}kcal｜蛋白質 {total_protein:.0f}g｜碳水 {total_carbs:.0f}g｜脂肪 {total_fat:.0f}g"
    return build_confirm_card(title=title, lines=lines, total=total_str)
```

- [ ] **Step 5: Add `parse_food_text` to `app/ai/food_analyzer.py`**

Open `app/ai/food_analyzer.py` and add at the end:

```python
async def parse_food_text(text: str, is_correction: bool = False) -> dict:
    """Parse a free-text food description into structured nutrition data.

    Returns dict with keys: foods, total_calories, total_protein, total_carbs, total_fat
    """
    import asyncio, json, logging
    from google import genai
    from google.genai import types
    from app.config import GEMINI_API_KEY

    logger = logging.getLogger(__name__)
    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = f"""\
請把以下飲食描述解析成 JSON 格式（不要加 markdown）：

{text}

格式：
{{
  "foods": [
    {{"name": "食物名稱", "portion": "份量", "calories": 數字, "protein": 數字, "carbs": 數字, "fat": 數字}}
  ],
  "total_calories": 數字,
  "total_protein": 數字,
  "total_carbs": 數字,
  "total_fat": 數字
}}
"""
    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.2),
        )
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception:
        logger.exception("Failed to parse food text")
        return {"foods": [], "total_calories": 0, "total_protein": 0, "total_carbs": 0, "total_fat": 0}
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
python -m pytest tests/test_commands_meal.py -v
```
Expected: all 3 tests PASS

- [ ] **Step 7: Also update `handle_image_message` in `handlers.py` to route food photos through `/吃` session**

In `handlers.py`, update `handle_image_message` to check if there's an active `awaiting_food` session:

```python
async def handle_image_message(
    message_id: str,
    blob_api: AsyncMessagingApiBlob,
    user_id: str = "default",
) -> str | LineTextMessage:
    """Handle incoming image messages — classify and route."""
    from app.line.session import get_session
    from app.line.commands.meal import _build_meal_confirm_card
    from app.line.session import set_session

    response = await blob_api.get_message_content(message_id)
    image_bytes = response

    # If user is in /吃 flow, treat image as food photo for that meal type
    session = get_session(user_id)
    if session and session["mode"] == "awaiting_food":
        draft = session.get("draft", {})
        meal_type_display = draft.get("meal_type_display", "")
        img_type = "food"  # force food classification
    else:
        img_type = await classify_image(image_bytes)

    if img_type == "food":
        result = await _handle_food_image(image_bytes)
        # If in /吃 session flow, convert to draft confirm
        if session and session["mode"] == "awaiting_food":
            # parse result string back... simpler: re-analyze and build confirm card
            from app.ai.image_analyzer import analyze_food_photo
            parsed = await analyze_food_photo(image_bytes)
            draft_data = {**draft, **{
                "foods": parsed.get("foods", []),
                "total_calories": parsed.get("total_calories", 0),
                "total_protein": parsed.get("total_protein", 0),
                "total_carbs": parsed.get("total_carbs", 0),
                "total_fat": parsed.get("total_fat", 0),
            }}
            set_session(user_id, mode="awaiting_meal_confirm", draft=draft_data)
            return _build_meal_confirm_card(draft_data, meal_type_display)
        return result
    elif img_type == "body_data":
        from app.line.commands.body import handle_body_photo
        return await handle_body_photo(image_bytes, user_id)
    elif img_type == "nutrition_label":
        if session and session["mode"] == "awaiting_food":
            from app.ai.image_analyzer import analyze_nutrition_label
            from app.line.commands.meal import _build_meal_confirm_card
            parsed = await analyze_nutrition_label(image_bytes)
            draft_data = {**draft, **{
                "foods": [{"name": parsed.get("product_name", "食品"), "portion": parsed.get("serving_size", "1份"),
                           "calories": parsed.get("calories_per_serving", 0),
                           "protein": parsed.get("protein_per_serving", 0),
                           "carbs": parsed.get("carbs_per_serving", 0),
                           "fat": parsed.get("fat_per_serving", 0)}],
                "total_calories": parsed.get("calories_per_serving", 0),
                "total_protein": parsed.get("protein_per_serving", 0),
                "total_carbs": parsed.get("carbs_per_serving", 0),
                "total_fat": parsed.get("fat_per_serving", 0),
            }}
            set_session(user_id, mode="awaiting_meal_confirm", draft=draft_data)
            return _build_meal_confirm_card(draft_data, meal_type_display)
        return await _handle_nutrition_label_image(image_bytes)
    else:
        return await _handle_food_image(image_bytes)
```

- [ ] **Step 8: Commit**

```bash
git add app/line/commands/meal.py app/ai/food_analyzer.py app/line/handlers.py \
        tests/test_commands_meal.py pytest.ini
git commit -m "feat: /吃 command with confirm card and iterative correction"
```

---

### Task 6: `/動` — Exercise logging flow

**Files:**
- Create: `app/line/commands/exercise.py`
- Create: `tests/test_commands_exercise.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_commands_exercise.py
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from linebot.v3.messaging import TextMessage


@pytest.mark.asyncio
async def test_start_exercise_flow_cardio_builds_instant_confirm():
    """Cardio exercises show a confirm card immediately."""
    with patch("app.line.commands.exercise.set_session"):
        from app.line.commands.exercise import start_exercise_flow
        result = await start_exercise_flow("游泳 45分鐘", "U123")

    assert isinstance(result, TextMessage)
    assert "游泳" in result.text
    assert "45" in result.text
    assert result.quick_reply is not None


@pytest.mark.asyncio
async def test_start_exercise_flow_weights_asks_for_list():
    """Weight training asks for exercise list."""
    with patch("app.line.commands.exercise.set_session"):
        from app.line.commands.exercise import start_exercise_flow
        result = await start_exercise_flow("上半身重訓", "U123")

    assert isinstance(result, str)
    assert "菜單" in result or "貼" in result


@pytest.mark.asyncio
async def test_handle_exercise_confirm_saves_workout():
    draft = {
        "workout_type": "上半身重訓",
        "exercises": [{"name": "硬舉", "weight_kg": 36, "reps": 10, "sets": 4}],
        "duration_min": None,
    }
    with patch("app.line.commands.exercise.db") as mock_db, \
         patch("app.line.commands.exercise.clear_session") as mock_clear:
        mock_db.insert_workout.return_value = {"id": 10}
        from app.line.commands.exercise import handle_exercise_confirm
        result = await handle_exercise_confirm(draft, "U123")

    mock_db.insert_workout.assert_called_once()
    assert mock_clear.called
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_commands_exercise.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'app.line.commands.exercise'`

- [ ] **Step 3: Implement exercise command**

```python
# app/line/commands/exercise.py
"""
/動 command — exercise logging flow.

Usage: /動 [description]
  /動 上半身重訓        → weight training: ask for exercise list
  /動 羽球 2小時        → cardio: instant confirm card
  /動 游泳 45分鐘       → cardio: instant confirm card

After saving, bot prompts for notes (one message, skippable).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re

from linebot.v3.messaging import MessageAction, QuickReply, QuickReplyItem, TextMessage

from app.db import queries as db
from app.line.confirm import (
    CONFIRM_SENTINEL, CANCEL_SENTINEL, NOTES_SKIP_SENTINEL,
    build_confirm_card,
)
from app.line.session import clear_session, set_session

logger = logging.getLogger(__name__)

# Keywords that indicate weight/resistance training
WEIGHT_TRAINING_KEYWORDS = ("重訓", "上半身", "臀腿", "核心", "全身", "健身", "啞鈴", "硬舉", "深蹲")


def _is_weight_training(description: str) -> bool:
    return any(kw in description for kw in WEIGHT_TRAINING_KEYWORDS)


def _estimate_cardio_calories(description: str) -> int:
    """Rough calorie estimate for cardio based on duration found in description."""
    match = re.search(r"(\d+)\s*分鐘", description)
    minutes = int(match.group(1)) if match else 60
    match_h = re.search(r"(\d+)\s*小時", description)
    if match_h:
        minutes = int(match_h.group(1)) * 60

    rates = {"游泳": 7, "羽球": 6, "跑步": 8, "騎車": 5}
    for sport, rate in rates.items():
        if sport in description:
            return minutes * rate
    return minutes * 5  # default


async def start_exercise_flow(args: str, user_id: str) -> str | TextMessage:
    """Entry point for /動 [description]."""
    if not args:
        return "請告訴我今天做什麼運動\n例：/動 游泳 45分鐘\n   /動 上半身重訓"

    if _is_weight_training(args):
        set_session(user_id, mode="awaiting_exercise_list", draft={"workout_type": args, "exercises": []})
        return f"💪 {args}\n練完後把菜單貼過來，格式隨意：\n例：硬舉 36kg 10x4\n   肩推 4kg 12x3"
    else:
        # Cardio — build confirm card immediately
        estimated_kcal = _estimate_cardio_calories(args)
        draft = {
            "workout_type": args,
            "exercises": [],
            "duration_min": None,
            "estimated_calories": estimated_kcal,
        }
        set_session(user_id, mode="awaiting_exercise_confirm", draft=draft)
        return build_confirm_card(
            title=f"🏃 {args}草稿",
            lines=[f"預估消耗：~{estimated_kcal}kcal（Apple Watch 今晚自動同步更新）"],
            total="確認儲存嗎？",
        )


async def handle_exercise_list_input(text: str, draft: dict, user_id: str) -> TextMessage:
    """Parse exercise list text and build confirm card."""
    parsed_exercises = await _parse_exercise_list(text, draft.get("workout_type", ""))
    new_draft = {**draft, "exercises": parsed_exercises}
    set_session(user_id, mode="awaiting_exercise_confirm", draft=new_draft)

    lines = []
    for e in parsed_exercises:
        name = e.get("name", "?")
        w = e.get("weight_kg")
        weight_str = f" {w}kg" if w else ""
        reps = e.get("reps", "")
        sets = e.get("sets", "")
        lines.append(f"• {name}{weight_str} {reps}下x{sets}組")

    return build_confirm_card(
        title=f"💪 {draft.get('workout_type', '重訓')}草稿",
        lines=lines if lines else ["（解析失敗，請重新貼上）"],
        total="Apple Watch 卡路里今晚自動同步",
    )


async def handle_exercise_confirm(draft: dict, user_id: str) -> str | TextMessage:
    """Save confirmed exercise to DB and prompt for notes."""
    try:
        db.insert_workout(
            workout_type=draft.get("workout_type", ""),
            exercises=draft.get("exercises", []),
            duration_min=draft.get("duration_min"),
            estimated_calories=draft.get("estimated_calories"),
            notes=None,
        )
        clear_session(user_id)
        # Prompt for notes — skippable
        set_session(user_id, mode="awaiting_notes", draft=draft)
        return TextMessage(
            text="✅ 已儲存！\n這次感覺怎樣？有什麼想記下來的？\n（直接跳過也可以）",
            quick_reply=QuickReply(items=[
                QuickReplyItem(action=MessageAction(label="跳過", text=NOTES_SKIP_SENTINEL)),
            ]),
        )
    except Exception:
        logger.exception("Failed to save workout")
        return "儲存失敗，請再試一次 🙏"


async def handle_notes_input(notes_text: str, draft: dict, user_id: str) -> str:
    """Save post-workout notes to the most recently inserted workout."""
    try:
        from app.config import today_tw
        workouts_today = db.get_workouts_for_date(today_tw())
        if workouts_today:
            latest_id = workouts_today[-1]["id"]
            db.update_workout(latest_id, {"notes": notes_text})
        clear_session(user_id)
        return "📝 備註已記下。下次練這個部位前用 /下次 就會提醒你！"
    except Exception:
        logger.exception("Failed to save workout notes")
        clear_session(user_id)
        return "備註儲存失敗，但運動紀錄已儲存 ✅"


async def _parse_exercise_list(text: str, workout_type: str) -> list[dict]:
    """Use AI to parse a free-text exercise list into structured data."""
    from google import genai
    from google.genai import types
    from app.config import GEMINI_API_KEY

    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = f"""\
解析以下重訓紀錄，轉成 JSON 陣列（不要 markdown）：

{text}

格式（每個動作）：
[{{"name": "動作名稱", "weight_kg": 數字或null, "reps": 數字或null, "sets": 數字或null, "notes": "備註或null"}}]

直接輸出 JSON 陣列。
"""
    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.1),
        )
        raw = response.text.strip().strip("```json").strip("```").strip()
        return json.loads(raw)
    except Exception:
        logger.exception("Failed to parse exercise list")
        return []
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_commands_exercise.py -v
```
Expected: all 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/line/commands/exercise.py tests/test_commands_exercise.py
git commit -m "feat: /動 command with weight training list parsing and notes prompt"
```

---

### Task 7: `/身體`, `/休息`, `/?` — Simple commands

**Files:**
- Create: `app/line/commands/body.py`
- Create: `app/line/commands/simple.py`
- Create: `tests/test_commands_simple.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_commands_simple.py
import pytest
from unittest.mock import patch

@pytest.mark.asyncio
async def test_handle_rest_saves_rest_day():
    with patch("app.line.commands.simple.db") as mock_db:
        mock_db.insert_workout.return_value = {"id": 99}
        from app.line.commands.simple import handle_rest
        result = await handle_rest("健檢", "U123")

    mock_db.insert_workout.assert_called_once()
    call_kwargs = mock_db.insert_workout.call_args
    assert "休息" in str(call_kwargs)
    assert isinstance(result, str)
    assert "休息" in result


@pytest.mark.asyncio
async def test_handle_help_returns_command_guide():
    from app.line.commands.simple import handle_help
    result = await handle_help()
    assert "/吃" in result
    assert "/動" in result
    assert "/身體" in result
    assert "/今日" in result
    assert "/下次" in result
    assert "/週報" in result
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_commands_simple.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement simple commands**

```python
# app/line/commands/simple.py
"""Simple single-turn commands: /休息, /?"""

from __future__ import annotations
import logging
from app.db import queries as db
from app.config import today_tw

logger = logging.getLogger(__name__)

HELP_TEXT = """\
📋 小健指令表
──────────────
/吃        記錄飲食（照片/文字/標籤）
/動        記錄運動（任何種類）
           例：/動 游泳 45分鐘
/身體      上傳 PICOOC 截圖
/休息      記錄休息日  例：/休息 健檢
/今日      查看今日紀錄 + 可刪除/修改
/下次      下次訓練建議  例：/下次 上半身
/計畫      查看或修改週計畫
/週報      近7天總結（週日20:00自動發送）
/?         顯示這張指令表
──────────────
Apple Watch 數據每天自動同步，無需手動傳"""


async def handle_rest(reason: str, user_id: str) -> str:
    """Log a rest day immediately (no confirm needed — low stakes)."""
    notes = f"休息日{f'：{reason}' if reason else ''}"
    try:
        db.insert_workout(
            workout_type="休息",
            exercises=[],
            duration_min=None,
            estimated_calories=0,
            notes=notes,
        )
        return f"✅ 已記錄今天是休息日。{f'（{reason}）' if reason else ''}\n好好恢復！"
    except Exception:
        logger.exception("Failed to save rest day")
        return "休息日記錄失敗 🙏"


async def handle_help() -> str:
    return HELP_TEXT
```

```python
# app/line/commands/body.py
"""
/身體 command — PICOOC body composition photo flow.

User sends /身體 then a PICOOC screenshot.
Session is set to awaiting_body_photo.
When image arrives, it's classified and routed here.
"""

from __future__ import annotations
import logging
from linebot.v3.messaging import TextMessage
from app.ai.image_analyzer import analyze_body_data, format_body_data
from app.db import queries as db
from app.config import today_tw
from app.line.confirm import build_confirm_card
from app.line.session import set_session, clear_session

logger = logging.getLogger(__name__)


async def start_body_flow(user_id: str) -> str:
    """Entry point for /身體 — ask user to send the PICOOC screenshot."""
    set_session(user_id, mode="awaiting_body_photo")
    return "⚖️ 請傳送 PICOOC 截圖 👇"


async def handle_body_photo(image_bytes: bytes, user_id: str) -> TextMessage:
    """Parse PICOOC screenshot and show confirm card."""
    result = await analyze_body_data(image_bytes)

    if "error" in result:
        clear_session(user_id)
        return format_body_data(result)

    draft = {
        "weight": result.get("weight"),
        "body_fat_pct": result.get("body_fat_pct"),
        "muscle_pct": result.get("muscle_pct"),
        "bmi": result.get("bmi"),
        "measurement_date": result.get("measurement_date") or today_tw().isoformat(),
    }
    set_session(user_id, mode="awaiting_body_confirm", draft=draft)

    lines = []
    if draft["weight"]: lines.append(f"• 體重：{draft['weight']}kg")
    if draft["body_fat_pct"]: lines.append(f"• 體脂率：{draft['body_fat_pct']}%")
    if draft["muscle_pct"]: lines.append(f"• 肌肉率：{draft['muscle_pct']}%")
    if draft["bmi"]: lines.append(f"• BMI：{draft['bmi']}")

    return build_confirm_card(
        title=f"⚖️ 身體數據草稿（{draft['measurement_date']}）",
        lines=lines,
        total="確認儲存嗎？",
    )


async def handle_body_confirm(draft: dict, user_id: str) -> str:
    """Save confirmed body metrics to DB."""
    try:
        metrics = {k: v for k, v in draft.items() if v is not None}
        if "muscle_pct" in metrics:
            metrics["muscle_mass"] = metrics.pop("muscle_pct")
        db.upsert_body_metrics(metrics)
        clear_session(user_id)
        return f"✅ 身體數據已儲存！體重 {draft.get('weight', '?')}kg，體脂 {draft.get('body_fat_pct', '?')}%"
    except Exception:
        logger.exception("Failed to save body metrics")
        return "儲存失敗，請再試一次 🙏"
```

- [ ] **Step 4: Update `handlers.py` to handle `awaiting_body_photo` session mode in image handler**

In the `handle_image_message` function in `handlers.py`, add a check before the existing `classify_image` call:

```python
# Add this check at the top of handle_image_message, after getting image_bytes:
if session and session["mode"] == "awaiting_body_photo":
    from app.line.commands.body import handle_body_photo
    return await handle_body_photo(image_bytes, user_id)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python -m pytest tests/test_commands_simple.py -v
```
Expected: all 2 tests PASS

- [ ] **Step 6: Commit**

```bash
git add app/line/commands/body.py app/line/commands/simple.py \
        tests/test_commands_simple.py
git commit -m "feat: /身體, /休息, /? commands"
```

---

## Phase 3 — Query & Advisory Commands

### Task 8: `/今日` — Today's log with IDs

**Files:**
- Create: `app/line/commands/today.py`

- [ ] **Step 1: Implement**

```python
# app/line/commands/today.py
"""
/今日 — show today's complete log with IDs for manual correction.

Format:
  🍽 飲食
  #37 午餐 低纖養生粥 384kcal  → /刪 37 | /改 37 午餐→早餐
  ...
  合計：1,200kcal

  💪 運動
  #28 上半身重訓 300kcal

  ⚖️ 身體
  體重 54.3kg  體脂 25.2%
"""

from __future__ import annotations
from app.db import queries as db
from app.config import today_tw


async def handle_today() -> str:
    today = today_tw()
    lines = ["📊 今日紀錄\n"]

    # Meals
    meals = db.get_meals_for_date(today)
    meal_type_display = {
        "breakfast": "早餐", "lunch": "午餐",
        "dinner": "晚餐", "snack": "點心", "other": "其他"
    }
    if meals:
        lines.append("🍽 飲食")
        total_kcal = 0
        total_protein = 0
        for m in meals:
            foods = m.get("food_items", [])
            names = "、".join(f["name"] for f in foods[:2]) if foods else "（無詳細）"
            if len(foods) > 2:
                names += f" 等{len(foods)}項"
            dtype = meal_type_display.get(m.get("meal_type", "other"), "其他")
            kcal = m.get("total_calories", 0)
            total_kcal += kcal
            total_protein += m.get("protein", 0)
            lines.append(f"  #{m['id']} {dtype} {names} {kcal:.0f}kcal")
        lines.append(f"  合計：{total_kcal:.0f}kcal｜蛋白質 {total_protein:.0f}g")
        lines.append("  刪除：/刪 [ID]   修改餐別：/改 [ID] 午餐")
    else:
        lines.append("🍽 飲食：尚無紀錄")

    lines.append("")

    # Workouts
    workouts = db.get_workouts_for_date(today)
    if workouts:
        lines.append("💪 運動")
        for w in workouts:
            wtype = w.get("workout_type", "?")
            kcal = w.get("estimated_calories") or 0
            kcal_str = f" {kcal:.0f}kcal" if kcal else ""
            lines.append(f"  #{w['id']} {wtype}{kcal_str}")
    else:
        lines.append("💪 運動：尚無紀錄")

    lines.append("")

    # Body metrics
    metrics = db.get_body_metrics_range(today, today)
    if metrics:
        m = metrics[-1]
        parts = []
        if m.get("weight"): parts.append(f"體重 {m['weight']}kg")
        if m.get("body_fat_pct"): parts.append(f"體脂 {m['body_fat_pct']}%")
        if m.get("active_calories"): parts.append(f"活動消耗 {m['active_calories']:.0f}kcal")
        if m.get("resting_heart_rate"): parts.append(f"靜心率 {m['resting_heart_rate']}bpm")
        lines.append("⚖️ 身體：" + "　".join(parts))
    else:
        lines.append("⚖️ 身體：尚無紀錄")

    return "\n".join(lines)
```

- [ ] **Step 2: Add `/刪` and `/改` to command router in `handlers.py`**

In `_handle_command`, add to the dispatch dict:

```python
"/刪": lambda: _handle_delete(args),
"/改": lambda: _handle_update(args),
```

Then add these functions to `handlers.py`:

```python
async def _handle_delete(args: str) -> str:
    """Delete a meal or workout by ID. Usage: /刪 37"""
    if not args.isdigit():
        return "格式：/刪 [ID]\n例：/刪 37"
    item_id = int(args)
    # Try meal first, then workout
    deleted = db.delete_meal(item_id)
    if not deleted:
        deleted = db.delete_workout(item_id)
    return f"✅ #{item_id} 已刪除" if deleted else f"找不到 #{item_id}，請用 /今日 確認 ID"


async def _handle_update(args: str) -> str:
    """Update a meal attribute. Usage: /改 37 午餐  or  /改 37 180kcal"""
    parts = args.split(maxsplit=1)
    if len(parts) < 2 or not parts[0].isdigit():
        return "格式：/改 [ID] [修改內容]\n例：/改 37 午餐\n   /改 37 180kcal"

    item_id = int(parts[0])
    change = parts[1].strip()

    meal_type_map = {"早餐": "breakfast", "午餐": "lunch", "晚餐": "dinner", "點心": "snack"}
    if change in meal_type_map:
        db.update_meal(item_id, {"meal_type": meal_type_map[change]})
        return f"✅ #{item_id} 已改為{change}"

    import re
    kcal_match = re.search(r"(\d+)\s*kcal", change)
    if kcal_match:
        db.update_meal(item_id, {"total_calories": float(kcal_match.group(1))})
        return f"✅ #{item_id} 熱量已更新為 {kcal_match.group(1)}kcal"

    return f"不確定要改什麼。\n支援：餐別（早餐/午餐/晚餐/點心）或熱量（如 180kcal）"
```

- [ ] **Step 3: Commit**

```bash
git add app/line/commands/today.py app/line/handlers.py
git commit -m "feat: /今日 with IDs, /刪 and /改 inline correction commands"
```

---

### Task 9: `/下次` — Next session suggestion

**Files:**
- Create: `app/line/commands/next_session.py`
- Modify: `app/db/queries.py` — add `get_workouts_by_type()`

- [ ] **Step 1: Add `get_workouts_by_type` to `app/db/queries.py`**

```python
def get_workouts_by_type(workout_type_keyword: str, limit: int = 3) -> list[dict]:
    """Return the most recent workouts matching a type keyword (case-insensitive partial match)."""
    result = (
        supabase.table("workouts")
        .select("*")
        .ilike("workout_type", f"%{workout_type_keyword}%")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []
```

- [ ] **Step 2: Implement next session command**

```python
# app/line/commands/next_session.py
"""
/下次 [部位] — suggest next session based on last session of that type.

Examples:
  /下次 上半身   → reads last 上半身 session + notes → specific plan
  /下次 臀腿     → reads last 臀腿 session + notes → specific plan
  /下次 游泳     → reads last 游泳 session → duration/intensity suggestion
"""

from __future__ import annotations
import asyncio
import logging
from app.db import queries as db
from app.config import GEMINI_API_KEY

logger = logging.getLogger(__name__)


async def handle_next_session(args: str) -> str:
    if not args:
        return "請告訴我要練哪個部位\n例：/下次 上半身\n   /下次 臀腿\n   /下次 游泳"

    workout_type = args.strip()
    recent = db.get_workouts_by_type(workout_type, limit=2)

    if not recent:
        return f"找不到「{workout_type}」的訓練紀錄。先用 /動 {workout_type} 記一次吧！"

    last = recent[0]
    last_date = last.get("created_at", "")[:10]
    exercises = last.get("exercises", [])
    notes = last.get("notes") or "無備註"

    exercise_summary = "\n".join(
        f"  • {e.get('name', '?')} {e.get('weight_kg', '')}kg "
        f"{e.get('reps', '')}下x{e.get('sets', '')}組"
        for e in exercises if e.get("name")
    ) or "  （無詳細動作紀錄）"

    prompt = f"""\
你是健身教練小健。根據用戶上次「{workout_type}」訓練，給這次的具體建議。

上次訓練（{last_date}）：
{exercise_summary}

上次備註：{notes}

請給出：
1. 這次每個動作的具體重量/次數/組數建議
2. 需要特別注意的地方（根據備註）
3. 最多一句總結

格式：純文字，用 • 列點，不要 markdown，不超過 15 行。
"""
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.5),
        )
        return f"📋 下次{workout_type}建議（根據 {last_date}）\n\n{response.text.strip()}"
    except Exception:
        logger.exception("Failed to generate next session suggestion")
        return f"上次{workout_type}（{last_date}）：\n{exercise_summary}\n備註：{notes}"
```

- [ ] **Step 3: Commit**

```bash
git add app/line/commands/next_session.py app/db/queries.py
git commit -m "feat: /下次 command reads last session notes for specific suggestions"
```

---

### Task 10: `/週報` — Weekly report (on-demand + auto Sunday)

**Files:**
- Create: `app/line/commands/report.py`
- Modify: `app/main.py` — add Sunday 20:00 scheduler job

- [ ] **Step 1: Implement weekly report command**

```python
# app/line/commands/report.py
"""
/週報 — 7-day rolling summary of exercise, diet, and body metrics.

Also triggered automatically every Sunday at 20:00 Taiwan time.
"""

from __future__ import annotations
from datetime import timedelta
from app.db import queries as db
from app.config import today_tw


async def handle_weekly_report() -> str:
    today = today_tw()
    start = today - timedelta(days=6)

    meals_all = []
    workouts_all = []
    for i in range(7):
        day = start + timedelta(days=i)
        meals_all.extend(db.get_meals_for_date(day))
        workouts_all.extend(db.get_workouts_for_date(day))

    metrics = db.get_body_metrics_range(start, today)

    # Workout summary
    non_rest = [w for w in workouts_all if w.get("workout_type") != "休息"]
    workout_types = [w.get("workout_type", "") for w in non_rest]
    from collections import Counter
    type_counts = Counter(workout_types)
    workout_str = "　".join(f"{t}x{c}" for t, c in type_counts.items()) if type_counts else "無"

    # Diet summary
    if meals_all:
        avg_kcal = sum(m.get("total_calories", 0) for m in meals_all) / 7
        avg_protein = sum(m.get("protein", 0) for m in meals_all) / 7
    else:
        avg_kcal = avg_protein = 0

    # Body change
    body_str = ""
    if len(metrics) >= 2:
        first, last = metrics[0], metrics[-1]
        w_change = (last.get("weight", 0) or 0) - (first.get("weight", 0) or 0)
        bf_change = (last.get("body_fat_pct", 0) or 0) - (first.get("body_fat_pct", 0) or 0)
        w_arrow = "↑" if w_change > 0 else "↓" if w_change < 0 else "→"
        bf_arrow = "↑" if bf_change > 0 else "↓" if bf_change < 0 else "→"
        body_str = (
            f"⚖️ 身體：體重 {first.get('weight','?')}→{last.get('weight','?')}kg（{w_arrow}{abs(w_change):.1f}）"
            f"　體脂 {first.get('body_fat_pct','?')}→{last.get('body_fat_pct','?')}%（{bf_arrow}{abs(bf_change):.1f}）"
        )
    elif metrics:
        m = metrics[-1]
        body_str = f"⚖️ 身體：體重 {m.get('weight','?')}kg　體脂 {m.get('body_fat_pct','?')}%"

    lines = [
        f"📊 近7天總結 {start.strftime('%m/%d')}–{today.strftime('%m/%d')}\n",
        f"💪 運動：{len(non_rest)}次（{workout_str}）",
        f"🍽 飲食：平均 {avg_kcal:.0f}kcal/天｜蛋白質平均 {avg_protein:.0f}g",
    ]
    if body_str:
        lines.append(body_str)

    return "\n".join(lines)
```

- [ ] **Step 2: Add Sunday 20:00 scheduler job to `app/main.py`**

In `app/main.py`, inside the `lifespan` function, add after the existing jobs:

```python
# Add this import at the top of main.py (with existing imports):
async def _weekly_report():
    """Auto-send weekly report every Sunday at 20:00 Taiwan time."""
    try:
        from app.line.push import push_text
        from app.line.commands.report import handle_weekly_report
        import asyncio
        report = await handle_weekly_report()
        push_text(report)
        logger.info("Weekly report sent")
    except Exception:
        logger.exception("Failed to send weekly report")

# In lifespan(), add after the evening summary job:
scheduler.add_job(
    _weekly_report,
    CronTrigger(day_of_week="sun", hour=20, minute=0, timezone=TW_TZ),
)
```

- [ ] **Step 3: Commit**

```bash
git add app/line/commands/report.py app/main.py
git commit -m "feat: /週報 7-day summary, auto-send Sunday 20:00 Taiwan time"
```

---

## Phase 4 — Schedule System & Morning Push

### Task 11: Weekly schedule system + `/計畫`

**Files:**
- Create: `app/db/schedule.py`
- Create: `app/line/commands/schedule.py`

- [ ] **Step 1: Implement schedule DB module**

```python
# app/db/schedule.py
"""
Weekly exercise schedule storage.

Stored in user_profile.exercise_habits.weekly_schedule as JSONB.

Schema:
{
  "default": {
    "monday": "重訓",
    "tuesday": "羽球",
    "wednesday": "重訓",
    "thursday": "重訓",
    "friday": "重訓",
    "saturday": "羽球",
    "sunday": "羽球"
  },
  "overrides": [
    {"from": "2026-05-01", "to": "2026-06-30", "thursday": "游泳"}
  ]
}
"""

from __future__ import annotations
import logging
from datetime import date
from app.db.client import supabase

logger = logging.getLogger(__name__)

WEEKDAY_KEYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
WEEKDAY_CN = {"monday": "週一", "tuesday": "週二", "wednesday": "週三",
              "thursday": "週四", "friday": "週五", "saturday": "週六", "sunday": "週日"}


def get_schedule() -> dict:
    """Return the full schedule dict from user_profile."""
    result = supabase.table("user_profile").select("exercise_habits").limit(1).execute()
    if not result.data:
        return {}
    habits = result.data[0].get("exercise_habits") or {}
    return habits.get("weekly_schedule", {})


def get_today_exercise(target_date: date | None = None) -> str | None:
    """Return today's planned exercise type, respecting overrides."""
    from datetime import date as date_type
    if target_date is None:
        from app.config import today_tw
        target_date = today_tw()

    schedule = get_schedule()
    if not schedule:
        return None

    weekday_key = WEEKDAY_KEYS[target_date.weekday()]

    # Check overrides first
    for override in schedule.get("overrides", []):
        from_date = date_type.fromisoformat(override["from"])
        to_date = date_type.fromisoformat(override["to"])
        if from_date <= target_date <= to_date and weekday_key in override:
            return override[weekday_key]

    return schedule.get("default", {}).get(weekday_key)


def set_schedule(schedule: dict) -> None:
    """Save the full schedule dict to user_profile."""
    result = supabase.table("user_profile").select("id, exercise_habits").limit(1).execute()
    if not result.data:
        logger.warning("No user_profile found, cannot save schedule")
        return
    row = result.data[0]
    habits = row.get("exercise_habits") or {}
    habits["weekly_schedule"] = schedule
    supabase.table("user_profile").update({"exercise_habits": habits}).eq("id", row["id"]).execute()


def seed_initial_schedule() -> None:
    """Seed the schedule from the user's stated plan (April 2026 setup)."""
    schedule = {
        "default": {
            "monday": "重訓",
            "tuesday": "羽球",
            "wednesday": "重訓",
            "thursday": "重訓",
            "friday": "重訓",
            "saturday": "羽球",
            "sunday": "羽球",
        },
        "overrides": [
            {"from": "2026-05-01", "to": "2026-06-30", "thursday": "游泳"},
        ],
    }
    set_schedule(schedule)
    logger.info("Initial schedule seeded")
```

- [ ] **Step 2: Implement `/計畫` command**

```python
# app/line/commands/schedule.py
"""
/計畫 — view or update weekly exercise schedule.
"""

from __future__ import annotations
from app.db.schedule import get_schedule, set_schedule, WEEKDAY_CN, WEEKDAY_KEYS


async def handle_schedule(args: str, user_id: str) -> str:
    if not args:
        return _format_schedule()

    # Natural language update — delegate to AI parser
    return await _update_schedule_from_text(args)


def _format_schedule() -> str:
    from app.db.schedule import get_schedule
    schedule = get_schedule()
    if not schedule:
        return "尚未設定週計畫。\n說明：/計畫 週四改成游泳"

    default = schedule.get("default", {})
    lines = ["📅 你的週計畫\n"]
    for key in WEEKDAY_KEYS:
        lines.append(f"  {WEEKDAY_CN[key]}　{default.get(key, '未設定')}")

    overrides = schedule.get("overrides", [])
    if overrides:
        lines.append("\n調整期間：")
        for o in overrides:
            changes = {k: v for k, v in o.items() if k not in ("from", "to")}
            for day_key, activity in changes.items():
                lines.append(f"  {o['from']}–{o['to']}：{WEEKDAY_CN.get(day_key, day_key)} → {activity}")

    lines.append("\n修改範例：/計畫 五月之後週四改成游泳")
    return "\n".join(lines)


async def _update_schedule_from_text(text: str) -> str:
    """Use AI to parse a natural language schedule change and apply it."""
    import asyncio, json, logging
    from google import genai
    from google.genai import types
    from app.config import GEMINI_API_KEY
    from app.db.schedule import get_schedule, set_schedule

    logger = logging.getLogger(__name__)
    client = genai.Client(api_key=GEMINI_API_KEY)
    current = get_schedule()

    prompt = f"""\
目前週計畫：
{json.dumps(current, ensure_ascii=False)}

用戶要修改：「{text}」

請輸出修改後的完整週計畫 JSON（同樣格式，不要 markdown）。
weekday key 用英文小寫（monday/tuesday/wednesday/thursday/friday/saturday/sunday）。
"""
    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.1),
        )
        raw = response.text.strip().strip("```json").strip("```").strip()
        new_schedule = json.loads(raw)
        set_schedule(new_schedule)
        return "✅ 週計畫已更新！\n" + _format_schedule()
    except Exception:
        logger.exception("Failed to update schedule")
        return "更新失敗，請再試一次。\n或用 /計畫 查看目前計畫。"
```

- [ ] **Step 3: Seed the initial schedule**

```bash
cd /Users/sophysmacmini/Documents/fitness-coach
python3 -c "
import os; os.chdir('/Users/sophysmacmini/Documents/fitness-coach')
from dotenv import load_dotenv; load_dotenv('.env')
from app.db.schedule import seed_initial_schedule
seed_initial_schedule()
print('Schedule seeded')
"
```
Expected output: `Schedule seeded`

Verify in Supabase: `SELECT exercise_habits FROM user_profile;` — should show `weekly_schedule` key with the plan.

- [ ] **Step 4: Commit**

```bash
git add app/db/schedule.py app/line/commands/schedule.py
git commit -m "feat: weekly schedule system with /計畫 command and seasonal overrides"
```

---

### Task 12: Morning push — schedule-aware with quick-tap buttons

**Files:**
- Modify: `app/main.py` — replace `_morning_checkin` with schedule-aware version
- Modify: `app/line/push.py` — add `push_message()` that accepts Message objects

- [ ] **Step 1: Add `push_message` to `app/line/push.py`**

Add at the end of `app/line/push.py`:

```python
def push_line_message(message, user_id: str | None = None) -> None:
    """Send any LINE Message object (TextMessage, etc.) as a push."""
    from linebot.v3.messaging import ApiClient, MessagingApi
    target = user_id or LINE_USER_ID
    if not target:
        logger.warning("No LINE_USER_ID set, cannot push message")
        return
    with ApiClient(config) as api_client:
        api = MessagingApi(api_client)
        api.push_message(PushMessageRequest(to=target, messages=[message]))
```

- [ ] **Step 2: Replace `_morning_checkin` in `app/main.py`**

Replace the entire `_morning_checkin` function:

```python
async def _morning_checkin():
    """Morning check-in: reads today's schedule and sends a quick-tap message."""
    try:
        from app.line.push import push_line_message
        from app.db.schedule import get_today_exercise, WEEKDAY_CN
        from app.config import today_tw
        from linebot.v3.messaging import TextMessage, QuickReply, QuickReplyItem, MessageAction

        today = today_tw()
        weekday_key = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"][today.weekday()]
        weekday_cn = WEEKDAY_CN[weekday_key]
        planned = get_today_exercise(today)

        if planned:
            body = f"早安 💪 今天{weekday_cn}，計畫：{planned}"
            confirm_text = f"✅ 就{planned}"
        else:
            body = f"早安 💪 今天{weekday_cn}，今天做什麼運動？"
            confirm_text = "✅ 按計畫"

        msg = TextMessage(
            text=body,
            quick_reply=QuickReply(items=[
                QuickReplyItem(action=MessageAction(label=confirm_text, text=f"今天{planned or '按計畫'}")),
                QuickReplyItem(action=MessageAction(label="🔄 換其他", text="今天換運動")),
                QuickReplyItem(action=MessageAction(label="😴 今天休息", text="/休息")),
            ]),
        )
        push_line_message(msg)
        logger.info("Morning check-in sent for %s: %s", weekday_cn, planned)
    except Exception:
        logger.exception("Failed to send morning check-in")
```

- [ ] **Step 3: Commit**

```bash
git add app/main.py app/line/push.py
git commit -m "feat: schedule-aware morning push with quick-tap exercise confirmation"
```

---

## Phase 5 — Deploy & Verify

### Task 13: Deploy and smoke test

- [ ] **Step 1: Run full test suite locally**

```bash
python -m pytest tests/ -v
```
Expected: all tests PASS

- [ ] **Step 2: Test the app starts without errors**

```bash
uvicorn app.main:app --reload --port 8000
```
Expected: server starts, no import errors

- [ ] **Step 3: Push to Render (deploy)**

```bash
git push origin main
```
Wait for Render to deploy (check Render dashboard logs).

- [ ] **Step 4: Smoke test each command via LINE**

Send these messages in sequence and verify:
1. `/?` → should receive command guide
2. `/吃` → should receive meal type buttons
3. Tap [午餐] → should receive "好，午餐。傳照片或告訴我吃什麼"
4. Send "一碗白飯 200g" → should receive confirm card with nutritional estimate
5. Tap [✅ 儲存] → should receive confirmation message
6. `/今日` → should show the logged meal with ID
7. `/動 游泳 30分鐘` → should receive confirm card
8. Tap [✅ 儲存] → save, then receive notes prompt
9. Tap [跳過] → clear
10. `/下次 上半身` → should receive next session suggestion
11. `/週報` → should receive 7-day summary
12. `/計畫` → should show the seeded weekly schedule

- [ ] **Step 5: Final commit**

```bash
git add .
git commit -m "chore: verify all commands working post-deploy"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| `/吃` with meal type quick-reply | Task 5 |
| Photo + text iterative correction before save | Task 5 (handle_meal_correction) |
| `/動` for any exercise type | Task 6 |
| Post-exercise notes prompt | Task 6 (handle_notes_input) |
| `/身體` PICOOC flow | Task 7 |
| `/休息` | Task 7 |
| `/?` command guide | Task 7 |
| `/今日` with IDs | Task 8 |
| `/刪` and `/改` | Task 8 |
| `/下次 [部位]` from notes | Task 9 |
| `/週報` on-demand + auto Sunday 20:00 | Task 10 |
| Weekly schedule with seasonal overrides | Task 11 |
| `/計畫` view/update | Task 11 |
| Morning push reads schedule | Task 12 |
| Q&A never logs | Task 4 (ask_coach_qa_only + QA_ONLY_QUERY_TEMPLATE) |
| Apple Watch steps removed | Done by user (Shortcut) |
| Session state persists across restarts | Task 2 (Supabase-backed) |
| Nutrition label photo in /吃 flow | Task 5 (handle_image_message update) |

**No gaps found.**

**Placeholder scan:** No TBDs, TODOs, or "similar to Task N" — all code shown in full.

**Type consistency:**
- `set_session(user_id, mode=..., draft=...)` — used consistently Tasks 2, 5, 6, 7, 11
- `clear_session(user_id)` — used consistently Tasks 5, 6, 7
- `build_confirm_card(title, lines, total)` — used consistently Tasks 3, 5, 6, 7
- `handle_text_message(text, user_id)` — updated signature used in Tasks 4 and webhook
- `CONFIRM_SENTINEL / CANCEL_SENTINEL / EDIT_SENTINEL` — defined Task 3, used Tasks 4, 5, 6
