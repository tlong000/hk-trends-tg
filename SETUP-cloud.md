# SETUP-cloud：GitHub Actions 部署（免 24/7 開電腦）

跑喺 GitHub 免費 runner，每 10 分鐘自動檢查一次（香港 + 歐美兩個群）。冇 server、冇本地模型、唔使開機。
客戶喺 Telegram 入面睇狀態同開關；你自己用 GitHub Actions 頁面做 debug 面板。

---

## 架構

```
GitHub Actions 長命 job（hk-trends-loop.yml，內部每 10 分鐘一圈）
  └─ 每一圈順序跑兩次同一個程式，靠環境變數分身：
     ① HK：TRENDS_GEO=HK  state.json     → 推去 TG_CHAT_ID（香港群）
     ② US：TRENDS_GEO=US  state_us.json  → 推去 TG_CHAT_ID_US（歐美群）
  └─ 每次嘅步驟：
       0. 讀 getUpdates → 處理 /pause /resume /status /runnow + 按鈕（只有 HK 做）
       1. 若「已暫停」→ 只更新心跳，收工
       2. 抓 trends.google.com 內部 RPC → 過濾（N 小時 / 搜尋量門檻 / 進行中）
       3. 官方 Trending RSS 補新聞標題；對唔上就抓嗰個關鍵詞嘅 Google 新聞 RSS
       4. 逐條 call 雲端 LLM（api.zetaapi.ai，OpenAI 相容）→ 短解讀
       5. sendMessage 去推送群
       6. edit 一條 pinned「心跳」訊息顯示運行狀態
  └─ commit state.json + state_us.json 返 repo（去重 + offset + 狀態嘅持久層）
```

> **兩個地區點解共用一個 job**：慳一半 runner 時間，而且兩邊時序一致。
>
> **Bot token 有兩種玩法**（睇你有冇填 `TG_BOT_TOKEN_US` secret，自動切換）：
>
> | | 共用一個 bot（唔填） | 歐美群另開一個 bot（填咗）|
> |---|---|---|
> | 歐美群見到嘅 bot | 同香港群同一個 | 自己嘅名同頭像 |
> | 歐美嘅 `/pause` `/status` | ✗ 冇（`TG_CONTROLS=0`）| ✓ 有 |
> | 歐美心跳按鈕 | ✗ 唔會畫出嚟 | ✓ 有 |
> | 要做嘅嘢 | 冇 | BotFather 開多個 bot、加入歐美群同管理 chat |
>
> 共用 token 嗰陣一定要關 US 嘅指令：兩個 instance 同時 `getUpdates` 會互相
> 食咗對方嘅指令流。程式亦都唔會喺呢個情況畫按鈕出嚟（畫咗係死掣）。
> **建議另開一個 bot** —— 一個專屬群配一個專屬 bot，兩邊完全獨立，冇呢個限制。

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

### 2. 攞三個 Telegram chat id
- **香港推送群** `TG_CHAT_ID` / **歐美推送群** `TG_CHAT_ID_US`：
  把 bot 加入嗰個群 → 群內發一句 → 開
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
| `TG_CHAT_ID` | 香港推送群 id（`-100…`） |
| `TG_CHAT_ID_US` | 歐美推送群 id（`-100…`） |
| `TG_ADMIN_CHAT_ID` | 管理 chat id（兩個地區共用，會見到兩條心跳） |
| `TG_BOT_TOKEN_US` | **選填**。填咗＝歐美群用自己嗰個 bot，指令／按鈕齊全；<br>唔填＝同香港共用一個 bot，歐美嗰邊冇指令冇按鈕。 |

（模型 `gpt-5.6-luna` 同 base url 寫喺兩份 workflow 的 `env`，要換就兩份一齊改。）

### 4. 開 workflow
Repo → **Actions** tab → 見到 `trends-tg loop (HK + US)` 同 `trends-tg (manual run-now)`
→ 若問就撳 **Enable**。喺 manual 嗰個撳 **Run workflow**（地區揀 `both`）跑一次
→ 展開個 run 睇 log：
- 應該見「RPC 共 N 條」→「符合門檻 X 條」。
- log 應該見到「US 用獨立 bot token…」或者「US 同 HK 共用 bot token…」其中一句。
- 管理 chat 收到 **兩條** pinned 狀態訊息 = 成功：「📊 香港熱搜推送 · 狀態」同
  「📊 歐美熱搜推送 · 狀態」。歐美嗰條有冇開關按鈕，睇你有冇填 `TG_BOT_TOKEN_US`。

---

## 客戶日常用法（全部喺 Telegram）

- **睇係咪 run 緊**：管理 chat 置頂嗰條心跳訊息，`最後檢查：X 分鐘前`。
  正常應該 ≤ 20 分鐘。過咗一個鐘冇更新 = 有事。
- **一鍵開關**：心跳訊息下面 `⏸ 暫停` / `▶️ 開` 按鈕。亦可打字：
  - `/pause` — 停止推送（仍會更新心跳顯示「已暫停」）
  - `/resume` — 恢復
  - `/status` — 即時回一份狀態
  - `/runnow` — 提示（真正「即刻跑」用下面 GitHub 方法）

> 按鈕／指令最多要等**一個週期（~10 分鐘）**先生效，因為冇長開 process，
> 係下一圈跑先讀到。要即時，用 GitHub「Run workflow」。
>
> 暫停係**分開兩個地區**嘅：香港嗰條心跳嘅按鈕只暫停香港。歐美嗰邊要有得暫停，
> 就要填 `TG_BOT_TOKEN_US`（見上面）——之後歐美嗰條心跳一樣有自己嘅按鈕同指令。
> 冇填嘅話，要停歐美就只有 Disable 成個 loop workflow（連香港一齊停）。

---

## 你嘅 debug 面板：GitHub Actions 頁面

- **Actions** tab = 每次 run 綠剔／紅叉 + 時間 + 完整 log。
- **Disable workflow** = 徹底停（連心跳都唔會動）。**Enable** = 開返。
- **Run workflow** = 即刻檢查一次（唔使等 cron）。
- 介面若真係壞（Google 改咗），run 會 exit 1 兼發一條 `⚠️` DM 去管理 chat。

---

## 調參

改 `.github/workflows/hk-trends-loop.yml` 的 `env:`（排程用嗰個）就得，唔使掂程式。
`hk-trends-tg.yml` 係手動即刻跑，記得兩份一齊改，唔係手動跑同排程跑會唔同結果。

| key | HK | US | 意思 |
|---|---|---|---|
| `TRENDS_GEO` | HK | US | 地區碼 |
| `TRENDS_HOURS` | 6 | 6 | 過去 N 小時窗口 |
| `MIN_TRAFFIC` | 500 | 10000 | 搜尋量桶門檻 |
| `MAX_PUSH_PER_RUN` | 5 | 3 | 每次最多推幾多條 |
| `MAX_CHARS` | 100 | 200 | 解讀字數上限（超出會斬喺最後一個句號，收唔到尾先加「…」）|
| `INTERVAL_SECONDS` | 600 | 600 | 兩圈之間隔幾耐（兩個地區共用） |
| `NEXT_RUN_MINUTES` | 10 | 10 | 心跳「下次約」顯示用，跟上面填 |
| `LOCAL_TZ` | Asia/Hong_Kong | America/New_York | 「今日已推」日界 + 心跳時間 |
| `NEWS_FALLBACK` | 0 | 1 | 官方 RSS 對唔上就抓 Google 新聞 RSS |
| `TG_CONTROLS` | 1 | 自動 | 讀唔讀指令；US 跟有冇 `TG_BOT_TOKEN_US` 自動 1／0 |

**門檻點解 US 要 10000**：實測同一個 6 小時窗，HK 嘅 RPC 回 2–10 條，
US 回 91–123 條（差約 40 倍）。US 用返 HK 嘅 500 會一個窗撞到 38 條，即係洗版。
10000 大約係 6 小時 8–14 條，扣返去重同單次上限，實際每日 20–30 條。
想再靜就調上 20000（6 小時約 3 條），想密啲就 5000（6 小時約 17 條）。

**`NEWS_FALLBACK` 點解 US 一定要開**：官方 Trending RSS 只回每日榜約 10 個關鍵詞。
HK 一個窗得幾條，條條都喺 top-10 入面，配對率 100%；US 一個窗 100+ 條，
實測配對率 0/14 —— 即係每條都冇真新聞標題可以餵俾模型。開咗之後實測 3/3 命中。

---

## 疑難

| 現象 | 處理 |
|---|---|
| run 綠色但冇推送 | 正常，嗰刻冇夠熱嘅新熱點（log 尾「符合門檻 0 條」） |
| 心跳訊息冇出 | `TG_ADMIN_CHAT_ID` secret 冇填 / bot 未喺嗰個 chat |
| 指令冇反應 | ①未過 10 分鐘 ②群組要 Disable Group Privacy ③bot 設過 webhook（`getUpdates 失敗` log）→ 開 `api.telegram.org/bot<TOKEN>/deleteWebhook` |
| `git push` 失敗（persist state） | repo 開咗 branch protection → 關咗佢，或畀 Actions 例外 |
| run 紅色 exit 1 + `⚠️` DM | Google 內部介面改咗格式，要跟進（見 `SETUP.md` Plan B：改返用舊 RSS 主來源） |
| `[XXX] 失敗，跳過：Telegram 回傳錯誤` | token / chat_id 錯，或 bot 唔喺群 |
| 模型回應慢／timeout | `MODEL_TIMEOUT` 調大；或 `MAX_PUSH_PER_RUN` 調細 |

---

## state.json 持久化點解要 commit

雲端 runner 每次都係全新機，`state.json` / `state_us.json`（記住「已推過邊啲關鍵詞」「指令 offset」「今日推咗幾多」）
要有地方擺低。做法係 run 完 `git commit` 返 repo。所以你會見到一堆
`chore: update state [skip ci]` commit，正常。

排程 loop 同手動 run 有機會同時寫同一個 state 檔，其中一邊 `git push` 會被 reject。
`merge_state.py` 負責喺重試前同遠端最新版做 **union**（兩邊嘅「已推過」記錄全部保留），
而唔係邊份贏——漏咗一個標記即係下次會重推，群組收到重複訊息。唔想見到就用 `actions/cache`（有機會被清，48h 內
被清會重推），或改存做一條 Telegram 訊息。
