# Command Mode Redesign — 小健教練
**Date:** 2026-04-19
**Status:** Awaiting user approval

---

## Problem Statement

The current chatbot has a high correction rate: 49 out of 119 user messages (41%) were corrections or clarifications. Root cause analysis from real chat history identified five recurring failure modes:

1. **Meal type misclassification (13 cases)** — photos and nutrition labels default to "other" because there is no meal type context at save time. AI guesses from time of day, which is often wrong.
2. **Silent saves** — the bot saves data without confirmation, so errors are only discovered after the fact, requiring ID-based correction commands.
3. **Context lost mid-conversation (8 cases)** — workout type declared in the morning is forgotten by the time the user reports actual exercise or asks calorie questions later.
4. **Duplicate entries (2+ cases)** — user resends because no confirmation was given, causing the same meal to be logged 2–3 times.
5. **Correction UX too hard** — fixing a wrong entry requires knowing the ID, typing a structured command, and trusting the bot executed it correctly. This creates a debug loop.

**Core insight:** The bot currently has to guess intent, meal type, whether to log, and the quantity — all at once, silently. Command mode separates intent declaration from data extraction, eliminating most guesses.

---

## Design Goals

- User declares intent explicitly before logging — no silent saves ever
- All data confirmed before saving via a confirm card
- Corrections happen in draft state before saving, not after
- Q&A mode never logs anything automatically
- Commands are few enough to memorize; a `/?` guide is always one tap away
- Apple Watch data improves in quality by removing unreliable fields
- Exercise notes feed directly into next-session suggestions

---

## Command System

### Full Command List

| Command | Usage | Description |
|---|---|---|
| `/吃` | `/吃` | Log a meal — triggers meal type quick-reply buttons |
| `/動 [描述]` | `/動 游泳 45分鐘` | Log any exercise, any type |
| `/身體` | `/身體` + PICOOC screenshot | Log body composition data |
| `/休息 [原因]` | `/休息 健檢` | Declare rest day |
| `/今日` | `/今日` | View today's full log with IDs for editing |
| `/下次 [部位]` | `/下次 上半身` | Get next workout suggestion based on last session notes |
| `/週報` | `/週報` | 7-day rolling summary (also sent automatically Sunday evening) |
| `/?` | `/?` | Display command guide in chat |

### `/?` Guide Message (as sent in LINE)

```
📋 小健指令表
──────────────
/吃        記錄飲食（照片/文字/標籤）
/動        記錄運動（任何種類）
           例：/動 游泳 45分鐘
/身體      上傳 PICOOC 截圖
/休息      記錄休息日  例：/休息 健檢
/今日      查看今日紀錄 + 可刪除/修改
/下次      下次訓練建議  例：/下次 上半身
/週報      近7天總結（週日晚上自動發送）
/?         顯示這張指令表
──────────────
Apple Watch 數據每天自動同步，無需手動傳
```

---

## Meal Logging Flow (`/吃`)

### Step 1 — Declare meal type via Quick Reply

After `/吃`, bot immediately replies with LINE Quick Reply buttons:
```
Bot: 這餐是？
     [早餐] [午餐] [晚餐] [點心]
```

### Step 2 — Send food content

User sends any of:
- A photo
- A photo + explanatory text in the same or next message
- Plain text description
- A nutrition label photo

### Step 3 — Confirm card (draft state)

Bot parses the input and shows the confirm card. Nothing is saved yet.

```
Bot: ━━━━━━━━━━━━━━━
     🍽 午餐草稿
     • 蒸蛋 80kcal｜蛋白質 8g
     • 飯糰 x2 500kcal｜蛋白質 16g
     合計：580kcal｜蛋白質 24g
     ━━━━━━━━━━━━━━━
     [✅ 儲存] [❌ 取消] [✏️ 修改]
```

### Step 4 — Iterative correction (if needed)

User can reply with corrections in plain text. Bot updates the draft and shows a new confirm card. This can repeat any number of times. Data is never written until ✅ is tapped.

```
You: 那個不是蒸蛋，是吻仔魚蒸蛋，而且飯糰只有一個

Bot: ━━━━━━━━━━━━━━━
     🍽 午餐草稿（已更新）
     • 吻仔魚蒸蛋 120kcal｜蛋白質 12g
     • 飯糰 250kcal｜蛋白質 8g
     合計：370kcal｜蛋白質 20g
     ━━━━━━━━━━━━━━━
     [✅ 儲存] [❌ 取消] [✏️ 繼續修改]
```

### Key Rules
- Bot never logs food mentioned in Q&A mode (no command = no logging)
- If user sends a photo without `/吃`, bot asks: "要記錄這餐嗎？用 /吃 開始"
- Nutrition label photos follow the same flow after meal type is selected

---

## Exercise Logging Flow (`/動`)

### Two sub-types handled automatically

**Weight training** — detected when description contains 重訓/上半身/臀腿/核心/全身:
```
You: /動 上半身重訓

Bot: 上半身重訓 💪
     練完後把菜單貼過來，格式隨意：
     例：硬舉 36kg 10x4
         肩推 4kg 12x3
     （或傳語音/照片也可以）
```

After user sends exercise list:
```
Bot: ━━━━━━━━━━━━━━━
     💪 上半身重訓草稿
     • 啞鈴臥推 6kg 12x4
     • 單手划船 8kg 12x4
     • 肩推 4kg 12x3
     消耗：Apple Watch 數據今晚自動同步
     ━━━━━━━━━━━━━━━
     [✅ 儲存] [❌ 取消] [✏️ 修改]
```

Then bot asks for notes (one message after save):
```
Bot: 這次感覺怎樣？有什麼想記下來的？
     （直接跳過也可以）
```

**Cardio / sport** — everything else:
```
You: /動 游泳 45分鐘

Bot: ━━━━━━━━━━━━━━━
     🏊 游泳 45分鐘草稿
     消耗：約 ~270kcal（估算）
     Apple Watch 數據今晚自動同步
     ━━━━━━━━━━━━━━━
     [✅ 儲存] [❌ 取消] [✏️ 加備註]
```

### Unified Exercise Data Model

All exercise sessions store the same fields regardless of type:

| Field | Source | Notes |
|---|---|---|
| `workout_type` | From command description | Free text, no fixed enum |
| `duration_min` | From command or Apple Watch | |
| `active_calories` | Apple Watch auto-sync | Synced via iOS Shortcut |
| `exercises` | Exercise list (weight training only) | sets / reps / weight_kg |
| `notes` | User's free-text after session | Used for /下次 suggestions |
| `feeling` | Extracted from notes | Parsed from note text |

---

## Body Data Flow (`/身體`)

```
You: /身體 + [PICOOC screenshot]

Bot: ━━━━━━━━━━━━━━━
     ⚖️ 身體數據草稿
     • 體重：54.3kg
     • 體脂率：25.2%
     • 肌肉率：70.4%
     • BMI：20.2
     ━━━━━━━━━━━━━━━
     [✅ 儲存] [❌ 取消] [✏️ 修改]
```

---

## Apple Watch Integration — Improvement

### Remove from iOS Shortcut
- `steps` — inaccurate for badminton/gym users, removed entirely

### Keep in iOS Shortcut
- `active_calories` — useful for daily calorie balance
- `resting_heart_rate` — useful for recovery tracking
- `weight` — if synced from PICOOC via Apple Health

### No changes needed on the server endpoint (`/health-data`)
Just update the iOS Shortcut to stop sending `steps`.

---

## Morning Push — Redesigned

Current morning push is a text block. New version:

```
早安 💪 根據你的訓練輪替，今天建議：臀腿日
熱量目標：1,850kcal（運動日）

[✅ 就臀腿] [🔄 換上半身] [😴 今天休息]
```

Tapping any button:
- Sets today's workout type (used for calorie estimate all day)
- Locks in the calorie target
- No further input needed

If no tap by 10am, bot sends a gentle nudge once.

---

## `/下次` — Next Session Suggestion

User specifies the body part:
```
/下次 上半身
/下次 臀腿
```

Bot reads the last session of that type + the notes, and generates a specific plan:

```
Bot: 上次上半身（4/10）：
     • 划船 8kg 12x4 — 你說左手後來沒力
     • 肩推 4kg 12x3 — 最後一組力竭

     今天建議：
     1. 啞鈴臥推 6kg 12x4（維持，感覺穩了再加）
     2. 單手划船 8kg 10x4（降下數，專注左手穩定）
     3. 肩推 4kg 10x3（略降，確保最後一組不力竭）
     4. 側平舉 2kg 15x3
```

Notes from previous sessions directly drive the suggestion. No memory loss.

---

## `/週報` — Weekly Summary

**Triggered:** Automatically every Sunday 20:00 (Taiwan time), or on demand via `/週報`

**Rolling period:** Last 7 days from today (not calendar week)

**Format:**
```
📊 近7天總結 4/13–4/19

運動：4次（上半身x2 臀腿x1 羽球x1）
飲食：平均 1,620kcal/天｜蛋白質平均 68g
身體：體重 54.3kg → 54.1kg（↓0.2）體脂 25.2% → 24.8%（↓0.4）

本週亮點：划船重量穩定，左手有改善
下週重點：蛋白質還差目標約 20g/天，可考慮在點心加一份豆漿
```

---

## Q&A Mode — Rules

- **No command = no logging.** Bot only answers questions in Q&A mode.
- If user mentions food ("我吃了一個便當") in Q&A, bot replies with nutritional info but does NOT log it. Bot adds: "要記錄的話用 /吃"
- If user mentions workout in Q&A, bot comments but does NOT log. Bot adds: "要記錄的話用 /動"
- All advice (calorie balance, workout suggestions, nutrition gaps) is based on confirmed database records, not chat context

---

## Data Flow Summary

```
User input
    │
    ├── /吃 → meal type tap → food input → draft confirm card → [iterative correction] → ✅ save
    │
    ├── /動 [desc] → weight: exercise list → draft confirm → ✅ save → notes prompt
    │               → cardio: instant draft → ✅ save → notes prompt (optional)
    │
    ├── /身體 → PICOOC photo → draft confirm → ✅ save
    │
    ├── /休息 → immediate save (no confirm needed, low stakes)
    │
    ├── /今日 → show log with IDs → user can /刪 or /改 inline
    │
    ├── /下次 [部位] → read last session + notes → generate specific plan
    │
    ├── /週報 → 7-day summary (also auto-Sunday 20:00)
    │
    ├── /? → send command guide message
    │
    └── free text → Q&A only, never logs
```

---

## What This Fixes (vs. Current)

| Problem | Before | After |
|---|---|---|
| Meal type wrong | AI guesses from time → often wrong | User taps meal type → always correct |
| Silent wrong saves | Saves immediately, find out later | Confirm card → catch before saving |
| Duplicate entries | Resend because unsure it worked | Confirm card = clear feedback, no retry |
| Context lost mid-chat | Workout type forgotten by afternoon | Declared via morning push tap, persisted |
| Correction needs ID | /今日 → find ID → type command → unsure if worked | Draft corrections in-place before save |
| Q&A accidentally logs | Any message might trigger a log | Q&A mode never logs, period |
| Steps data inaccurate | Sent from Apple Watch (unreliable for badminton) | Removed from Shortcut |
| No exercise notes | Notes field often empty | Prompted after every session, feeds /下次 |

---

## Out of Scope (this iteration)

- Web dashboard / Google Sheets integration — deferred, evaluate after 1 week
- Multi-user support
- Meal photo history gallery
- Automatic workout rotation detection (manual `/下次 [部位]` for now)
