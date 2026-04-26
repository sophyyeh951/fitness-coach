# 休息日切換相關 bug 紀錄

> 發現於 2026-04-26。處理完可刪除。
> 情境：早上計畫重訓，臨時改 /休息 → 預估消耗/建議攝取數字感覺怪。

驗算結果：休息日的數字本身都是對的（1483 burn / 1300 target，BASE_TDEE=1483、DAILY_DEFICIT=300、MIN_DAILY_TARGET=1300）。但有以下三個問題會讓使用者覺得「對不上」。

---

## Bug 1（UX 缺補刀）：/休息 不像 /吃 會回今日目標摘要

**位置**：`app/line/commands/simple.py:27-41`（`handle_rest`）

**現況**：只回「✅ 已記錄今天是休息日。好好恢復！」

**問題**：早上按「✅ 就重訓」會由 `_morning_plan_reply` 算出「建議攝取約 1483kcal」並推給用戶。之後按「😴 今天休息」走 `/休息`，沒有回新的目標，LINE 聊天紀錄停留在舊的 1483，要再 `/今日` 才看得到 1300。這是「數字感覺怪」的最可能來源。

**建議修法**：`handle_rest` 成功儲存後，append `_today_intake_summary()` 的輸出（從 `app.line.commands.meal` import），跟 `handle_meal_confirm` 一致。

**測試重點**：
- 模擬早上 `_morning_plan_reply("今天重訓")` 後，再呼叫 `handle_rest("")`，回傳訊息應包含「建議攝取 1300kcal」「休息日」字樣。
- /動 的 cardio/strength confirm 是否也要補摘要（一致性）—— 目前 `handle_exercise_confirm` 只回「已儲存！這次感覺怎樣？」，可順便檢視。

---

## Bug 2（文案疊字）：/吃 後顯示「休息日日」

**位置**：`app/line/commands/meal.py:157`

```python
burn_label = f"預估消耗 {total_burn:.0f}kcal（{ex_label}日）"
```

**問題**：`ex_label` 在休息情境已經是 `"休息日"`（meal.py:144、today.py:145），再串「日」變成「休息日日」。其他類型 label 是 `羽球` / `游泳` / `有氧` / `重訓`（單字），所以只有休息踩雷。

**建議修法**：兩擇一
- (a) 把 `ex_label` 統一改成單字：meal.py:144 與 today.py:145 改 `"休息"`，外圍 label 統一加「日」。
- (b) 把 meal.py:157 的格式改成 `f"預估消耗 {total_burn:.0f}kcal（{ex_label}）"`（移除多餘「日」），但要確認其他 label 加不加「日」的閱讀感。

我傾向 (a)：lookup 表回傳 `(估計值, 短 label)`，display 時統一加「日」，最一致。

**測試重點**：snapshot test `_today_intake_summary` 在 `[{workout_type: "休息"}]` workouts 下的輸出，確認沒有「日日」。

---

## Bug 3（邏輯邊角案例）：重訓 + /休息 混記，重訓消耗被歸零

**位置**：
- `app/line/commands/today.py:141-153`
- `app/line/commands/meal.py:140-152`

```python
if workouts:
    all_types = " ".join(w.get("workout_type", "") for w in workouts)
    if any(k in all_types for k in ["休息"]):   # ← 最先攔截
        exercise_est, exercise_label = 0, "休息日"
    elif ...
```

**問題**：只要當天 workouts 中有任一筆是「休息」，就直接 0kcal，**忽略其他真實有做的運動**。例如：

| workouts                                | 預期         | 實際       |
| --------------------------------------- | ------------ | ---------- |
| `[{type: 重訓}, {type: 休息}]`            | ~300 kcal    | 0 kcal     |
| `[{type: 羽球}, {type: 休息}]`            | ~550 kcal    | 0 kcal     |
| `[{type: 練上半身}, {type: 休息}]`        | ~300 kcal    | 0 kcal     |

**使用者目前情境（早上沒真的做、直接 /休息）不會踩到**，但若以後真的有「練一半喊休息」或誤按、還沒清掉的舊紀錄，就會少算消耗 → 建議攝取被低估 → 容易吃不夠。

**建議修法（其中一種）**：
- (a) 改用 max 邏輯：算每筆的估計值，取最大或加總非休息部分；忽略休息筆。
- (b) 改用 workout 欄位的 `estimated_calories`（DB 已經存了），sum 所有非休息工作的 kcal。Cardio 透過 `_estimate_cardio_calories` 已寫入；重訓目前可能是 None（等 Apple Watch 同步）。
- (c) 若 workouts 中同時存在「休息 + 其他類型」，視為使用者切換，**取最後一筆的類型**作為當日定調（時間排序）。

我傾向 (b) + fallback 到 (c) 最乾淨。

**測試重點**：
- `[{type: 重訓}, {type: 休息}]` → 預期非 0
- `[{type: 休息}]` only → 預期 0
- `[{type: 休息}, {type: 重訓}]`（順序顛倒）→ 看實作選哪種語意

---

## 觀察重點（不一定是 bug，但值得留意）

### O1：`_today_summary` 是 dead code

`app/line/handlers.py:438-579` 定義 `_today_summary`，全 repo 沒有 caller。內含**另一份**休息日邏輯漏判（531-539 沒有 `休息` 分支，會 fallback 成「重訓日 300kcal」）。如果未來重新接上會踩雷。

**建議**：直接刪掉這個 function，避免誤用。

### O2：`/動` 的 estimated_calories 在 today/meal 摘要中被忽略

`workouts.estimated_calories` 已經存了（cardio 從 `_estimate_cardio_calories` 算，重訓等 Apple Watch），但 `today.py` Priority 2、`meal.py` Priority 2 都用**寫死的 550/500/300**，沒讀 DB 欄位。

例：用戶 `/動 羽球 3小時 → 1080kcal`（>550），摘要還是顯示 550。

修 Bug 3 時可以一起處理（採方案 b）。

### O3：Apple Watch 同步時機

Priority 1 是 `body_metrics.active_calories`，但 Apple Watch shortcut 通常是傍晚/深夜才同步。所以白天時段一律走 Priority 2/3，這是預期行為，但要確認 Bug 3 修完後白天的數字行為仍合理。

### O4：morning_plan_reply 跟 /休息 按鈕不一致

morning check-in 的「😴 今天休息」按鈕送 `/休息`（slash command），不會觸發 `_morning_plan_reply`。但用戶手打「今天休息」會觸發 `_morning_plan_reply` → 回「休息日加油」。修 Bug 1 時可以順便把這兩條路徑的回覆內容對齊。

---

## 推薦處理順序

1. **Bug 1**（最影響感覺）— 寫 `handle_rest` 的測試 → 加摘要輸出。
2. **Bug 2**（順手）— 改 label 為單字統一加「日」，修 today.py + meal.py。
3. **O1**（順手）— 刪 dead code。
4. **Bug 3 + O2**（一起改最划算）— 重寫 Priority 2 邏輯，讀 `estimated_calories`，用最後一筆 workout 定調當日類型。

每個改動配 unit test，跑 `pytest tests/` 全綠再 commit。
