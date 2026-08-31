# SETUP-cloud：GitHub Actions 部署（免 24/7 開電腦）

跑喺 GitHub 免費 runner，每 15 分鐘自動檢查一次。冇 server、冇本地模型、唔使開機。
客戶喺 Telegram 入面睇狀態同開關；你自己用 GitHub Actions 頁面做 debug 面板。

---

## 架構

```
GitHub Actions 排程（cron */15）
  └─ python3 trends_tg_bot.py
       0. 讀 getUpdates → 處理 /pause /resume /status /runnow + 按鈕
       1. 若「已暫停」→ 只更新心跳，收工
       2. 抓 trends.google.com 內部 RPC → 過濾（6h / 搜尋量≥500 / 進行中）
       3. 逐條 call 雲端 LLM（api.zetaapi.ai，OpenAI 相容）→ ≤100 字解讀
       4. sendMessage 去推送群
       5. edit 一條 pinned「心跳」訊息顯示運行狀態
  └─ commit state.json 返 repo（去重 + offset + 狀態嘅持久層）
```

---

## 一次性設定

### 1. 開 repo
把成個 `hk-trends-tg/` 資料夾 push 上一個 **private** GitHub repo（`state.json` 要一齊入，`.env` 唔好入）。

```bash
cd hk-trends-tg
git init && git add . && git commit -m "init"
git branch -M main
git remote add origin git@github.com:<你>/<repo>.git
git push -u origin main
```

### 2. 攞兩個 Telegram chat id
- **推送群** `TG_CHAT_ID`：把 bot 加入客戶群 → 群內發一句 → 開
  `https://api.telegram.org/bot<TOKEN>/getUpdates` → 搵 `"chat":{"id":-100...}`。
- **管理 chat** `TG_ADMIN_CHAT_ID`：心跳訊息同開關掣會出喺呢度。
  建議係 **客戶同 bot 嘅一對一私訊**（客戶搵個 bot 撳 Start，再開 getUpdates 攞佢個正數 id），
  或者一個得你同客戶嘅細管理群。唔想分開就填返推送群個 id。

> 想 `/status` 呢類指令喺群組收到：@BotFather → 你個 bot → Bot Settings →
> Group Privacy → **Disable**（私訊唔受影響）。

### 3. Repo secrets
GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**，加：

| Secret | 值 |
|---|---|
| `MODEL_API_KEY` | 你 api.zetaapi.ai 個 key |
| `TG_BOT_TOKEN` | BotFather 個 token |
| `TG_CHAT_ID` | 推送群 id（`-100…`） |
| `TG_ADMIN_CHAT_ID` | 管理 chat id |

（模型 `gpt-5.6-luna` 同 base url 已經寫死喺 `.github/workflows/hk-trends-tg.yml` 的 `env`，要換就改嗰度。）

### 4. 開 workflow
Repo → **Actions** tab → 見到 `hk-trends-tg` → 若問就撳 **Enable**。
撳 **Run workflow** 手動跑一次 → 展開個 run 睇 log：
- 應該見「RPC 共 N 條」→「符合門檻 X 條」。
- 管理 chat 收到一條 pinned「📊 香港熱搜推送 · 狀態」訊息 = 成功。

---

## 客戶日常用法（全部喺 Telegram）

- **睇係咪 run 緊**：管理 chat 置頂嗰條心跳訊息，`最後檢查：X 分鐘前`。
  正常應該 ≤ 20 分鐘。過咗一個鐘冇更新 = 有事。
- **一鍵開關**：心跳訊息下面 `⏸ 暫停` / `▶️ 開` 按鈕。亦可打字：
  - `/pause` — 停止推送（仍會更新心跳顯示「已暫停」）
  - `/resume` — 恢復
  - `/status` — 即時回一份狀態
  - `/runnow` — 提示（真正「即刻跑」用下面 GitHub 方法）

> 按鈕／指令最多要等**一個排程週期（~15 分鐘）**先生效，因為冇長開 process，
> 係下次 cron 跑先讀到。要即時，用 GitHub「Run workflow」。

---

## 你嘅 debug 面板：GitHub Actions 頁面

- **Actions** tab = 每次 run 綠剔／紅叉 + 時間 + 完整 log。
- **Disable workflow** = 徹底停（連心跳都唔會動）。**Enable** = 開返。
- **Run workflow** = 即刻檢查一次（唔使等 cron）。
- 介面若真係壞（Google 改咗），run 會 exit 1 兼發一條 `⚠️` DM 去管理 chat。

---

## 調參

改 `.github/workflows/hk-trends-tg.yml` 的 `env:` 就得，唔使掂程式：

| key | 預設 | 意思 |
|---|---|---|
| `cron` | `*/15` | 排程密度（`*/10`、`*/5` 更密；GitHub 最密 5 分鐘且繁忙時會延遲） |
| `TRENDS_HOURS` | 6 | 過去 N 小時窗口 |
| `MIN_TRAFFIC` | 500 | 搜尋量桶門檻 |
| `MAX_PUSH_PER_RUN` | 5 | 每次最多推幾多條 |
| `NEXT_RUN_MINUTES` | 15 | 心跳「下次約」顯示用，跟 cron 填 |

改咗 `cron` 記得同步改 `NEXT_RUN_MINUTES`。

---

## 疑難

| 現象 | 處理 |
|---|---|
| run 綠色但冇推送 | 正常，嗰刻冇夠熱嘅新熱點（log 尾「符合門檻 0 條」） |
| 心跳訊息冇出 | `TG_ADMIN_CHAT_ID` secret 冇填 / bot 未喺嗰個 chat |
| 指令冇反應 | ①未過 15 分鐘 ②群組要 Disable Group Privacy ③bot 設過 webhook（`getUpdates 失敗` log）→ 開 `api.telegram.org/bot<TOKEN>/deleteWebhook` |
| `git push` 失敗（persist state） | repo 開咗 branch protection → 關咗佢，或畀 Actions 例外 |
| run 紅色 exit 1 + `⚠️` DM | Google 內部介面改咗格式，要跟進（見 `SETUP.md` Plan B：改返用舊 RSS 主來源） |
| `[XXX] 失敗，跳過：Telegram 回傳錯誤` | token / chat_id 錯，或 bot 唔喺群 |
| 模型回應慢／timeout | `MODEL_TIMEOUT` 調大；或 `MAX_PUSH_PER_RUN` 調細 |

---

## state.json 持久化點解要 commit

雲端 runner 每次都係全新機，`state.json`（記住「已推過邊啲關鍵詞」「指令 offset」「今日推咗幾多」）
要有地方擺低。做法係 run 完 `git commit` 返 repo。所以你會見到一堆
`chore: update state [skip ci]` commit，正常。唔想見到就用 `actions/cache`（有機會被清，48h 內
被清會重推），或改存做一條 Telegram 訊息。
