# 香港 Google Trends 熱搜 → 本地模型解讀 → Telegram 推送

零第三方套件（淨用 Python 標準庫）。Python 3.8 或以上即可。

## 檔案

| 檔案 | 作用 |
|---|---|
| `trends_tg_bot.py` | 主程式：抓 Trending Now → 過濾 → call 本地模型 → 發 Telegram |
| `analysis_prompt.md` | 俾本地模型嘅提示（system / user 兩段）。改寫法就改呢個檔 |
| `config.example.env` | 設定樣本，複製成 `.env` |
| `run.sh` | launchd wrapper：載入 `.env` → 跑 Python → 寫 `run.log` |
| `com.user.hk-trends-tg.plist` | launchd 排程設定（`StartInterval` 秒數，預設 120＝2 分鐘） |
| `state.json` | 自動產生，記錄已推送關鍵詞（去重用） |

## 運作邏輯

1. 抓 `https://trends.google.com/trending?geo=HK` 呢個頁面背後嘅內部介面
   （`batchexecute` RPC，RPC id `i0OFE`），直接要求「過去 `TRENDS_HOURS` 小時」嘅資料。
2. 每條熱點取：關鍵詞、**數值搜尋量**（100 / 200 / 500 / 2000 / 20000…）、起始時間、
   係咪已完結、相關搜尋詞。
3. 另外抓官方 Trending RSS，按關鍵詞比對補上真實新聞標題＋連結（best-effort，失敗照跑；
   配唔到就用 Google News 搜尋連結兜底）。
4. 過濾：`起始時間` 喺最近 `TRENDS_HOURS`（預設 6）小時內、搜尋量 `>= MIN_TRAFFIC`（預設 500）、
   而且 trend 仍然「進行中」（`INCLUDE_ENDED=1` 可放寬）。
5. 去重：`state.json` 有嘅關鍵詞 48 小時內唔再推。
6. 每條合格熱點：用 `analysis_prompt.md` + 新聞／相關詞砌 prompt，call 本地模型出「≤100 字」
   解讀，程式再硬性截到 100 字。
7. 發去 Telegram 群組。任何一步失敗只跳過該條，唔會 crash。

## 安裝步驟（喺第二部電腦）

```bash
mkdir -p ~/hk-trends-tg && cd ~/hk-trends-tg
# 將 trends_tg_bot.py / analysis_prompt.md / run.sh / config.example.env / plist 放入呢個資料夾
cp config.example.env .env
chmod +x run.sh trends_tg_bot.py
```

編輯 `.env`：

- `MODEL_API`：本地模型用 Ollama 就填 `ollama`；LM Studio / vLLM / llama.cpp server 就填 `openai`
- `MODEL_BASE_URL`：Ollama 預設 `http://127.0.0.1:11434`；LM Studio 預設 `http://127.0.0.1:1234`
- `MODEL_NAME`：例 `qwen2.5:7b`
- `TG_BOT_TOKEN` / `TG_CHAT_ID`：你已有嘅 bot token 同群組 id

### 攞群組 chat id 嘅方法

1. 將個 bot 加入群組。
2. 喺群組隨便發一句嘢。
3. 瀏覽器打開 `https://api.telegram.org/bot<你嘅TOKEN>/getUpdates`，搵 `"chat":{"id":-100...}`。

## 測試

```bash
# 只抓 + 過濾 + 印訊息，唔 call 真模型、唔發 Telegram
MODEL_API=mock DRY_RUN=1 ./run.sh ; tail -n 40 run.log

# call 真模型，但仍然唔發 Telegram（睇解讀質素）
DRY_RUN=1 ./run.sh ; tail -n 40 run.log

# 正式：發一次
./run.sh ; tail -n 40 run.log
```

## 排程（launchd）

```bash
# 改 plist 入面 3 個 /Users/YOURNAME/hk-trends-tg 做真實絕對路徑
cp com.user.hk-trends-tg.plist ~/Library/LaunchAgents/
launchctl load  ~/Library/LaunchAgents/com.user.hk-trends-tg.plist
launchctl list | grep hk-trends-tg          # 確認已載入
launchctl start com.user.hk-trends-tg       # 即刻手動觸發一次

# 之後改咗設定要重載：
launchctl unload ~/Library/LaunchAgents/com.user.hk-trends-tg.plist
launchctl load   ~/Library/LaunchAgents/com.user.hk-trends-tg.plist
```

`StartInterval` 預設 120 秒（2 分鐘）；`state.json` 去重，唔會重覆推。
留意：Trending 資料唔會每 2 分鐘變，頻繁 poll 對無官方文件嘅內部介面有 429 風險；
`fetch_trends()` 已內建 3 次退避重試，連續 429 就把 `StartInterval` 調大到 300 以上。

## 調參

| env | 預設 | 意思 |
|---|---|---|
| `TRENDS_GEO` | HK | 地區碼 |
| `TRENDS_HOURS` | 6 | 過去 N 小時窗口（server 端過濾） |
| `MIN_TRAFFIC` | 500 | 數值搜尋量門檻 |
| `INCLUDE_ENDED` | 0 | =1 連已完結嘅 trend 都推 |
| `MAX_PUSH_PER_RUN` | 5 | 每次最多推幾多條（防洗版） |
| `DEDUP_TTL_HOURS` | 48 | 同一詞幾耐內唔重推 |
| `MAX_CHARS` | 100 | 解讀硬性截字 |
| `MODEL_TIMEOUT` | 90 | 等模型回應秒數 |

## 已知限制

- 搜尋量係 Google 嘅粗桶（100 / 200 / 500 / 2000 / 20000…），唔係精確次數；Google 冇公開精確數字。「>= 500」= 桶值 500 或以上。
- `batchexecute` RPC（`i0OFE`）係 Trending Now 頁面嘅**內部介面**，Google 冇正式文件，理論上將來可能改格式。`fetch_trends()` 已對 `)]}'` 前綴、envelope 結構、每行欄位做咗防禦性解析，並對 HTTP 429/5xx 做 3 次退避重試。暫時性錯誤（斷網／限流）→ log `WARN …今次略過` + exit 0；真係解析唔到（格式變咗）→ log `FATAL …解析失敗` + exit 1。舊 RSS 端點仍保留喺 `fetch_rss_news_map()` 補新聞用，亦係 Plan B 骨架。
- 新聞標題靠 RSS 按關鍵詞比對；RSS 未必有每一個 6 小時新熱點，配唔到就用 Google News 搜尋連結兜底，模型仍有「相關搜尋詞」做背景。
- 本地模型輸出質素／字數靠 prompt 控制 + 程式截字兜底；細模型偶爾會離題，觀察頭幾日再收緊 `analysis_prompt.md`。
