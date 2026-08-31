# SETUP-slim：精簡部署步驟（macOS）

> **Windows 用戶 → 睇 `SETUP-win.md`**（launchd 呢度嘅步驟唔適用）。
> 同 `SETUP.md` 一樣，但冇內嵌程式碼，方便 context 細嘅助手 / 人手照做。
> 程式檔已經喺同一個資料夾。全部指令喺資料夾內執行，預設 `~/hk-trends-tg/`。
> Telegram bot token 由用戶親手貼入 `.env`，唔好代填。

## 0. 前置

```bash
python3 --version || xcode-select --install
curl -s --max-time 3 http://127.0.0.1:11434/api/tags ; echo   # 有回應 = Ollama
curl -s --max-time 3 http://127.0.0.1:1234/v1/models  ; echo   # 有回應 = LM Studio(openai 相容)
```

- Ollama → `MODEL_API=ollama`，`MODEL_BASE_URL=http://127.0.0.1:11434`，模型名睇 `ollama list`
- LM Studio → `MODEL_API=openai`，`MODEL_BASE_URL=http://127.0.0.1:1234`，模型名照抄上面 `/v1/models` 回應嘅 `id`（唔好自己作）
- **模型載入時 Context Length 要 ≥ 4096**（本程式每次 prompt <1000 token；報 `context ... too small` 就係呢度太細）

### LM Studio 專用檢查（用 qwen 9B 呢類）
1. 打開 **Developer（開發者）分頁 → Server**，確認 Server 已 Start、port 係 1234。
2. 頂部 model 選單 → 揀你個模型 → 展開 **Load / 載入設定** → **Context Length 設 8192**（VRAM/RAM 唔夠就 4096，並調低 GPU Offload 層數）→ **Reload**。
3. `curl -s http://127.0.0.1:1234/v1/models` → 抄低回應入面個 `"id"` 做 `MODEL_NAME`，而且確保呢個 model 係 loaded 狀態。
4. 唔好將成份 `SETUP.md` 貼入 LM Studio chat 叫佢做嘢——用呢份 slim，或者你自己跑下面幾句就得。

## 1. 放檔＋檢查

```bash
cd ~/hk-trends-tg
ls -1                         # 應見 trends_tg_bot.py analysis_prompt.md run.sh
                              #     com.user.hk-trends-tg.plist config.example.env
python3 -m py_compile trends_tg_bot.py && echo OK
chmod +x run.sh trends_tg_bot.py
```

## 2. 攞 Telegram 群組 chat id

先喺群組發一句嘢，再：

```bash
curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates" | python3 -m json.tool
```

搵 `"chat":{"id":-100XXXXXXXXXX,...}`，嗰個負數就係 `TG_CHAT_ID`。
（搵唔到 → @BotFather → Bot Settings → Group Privacy → Disabled，再喺群發言。）

## 3. .env

```bash
cd ~/hk-trends-tg
cp config.example.env .env
chmod 600 .env
```

改 `.env` 呢 5 行：`MODEL_API`、`MODEL_BASE_URL`、`MODEL_NAME`、`TG_BOT_TOKEN`（用戶貼）、`TG_CHAT_ID`。
其餘保持預設。

## 4. 三段式測試

```bash
cd ~/hk-trends-tg
MODEL_API=mock DRY_RUN=1 ./run.sh ; tail -n 60 run.log   # a. 只測抓取+過濾
DRY_RUN=1 ./run.sh ; tail -n 60 run.log                  # b. 加真模型，未發 TG
./run.sh ; tail -n 60 run.log                            # c. 正式發一次 → 去群組睇
```

`符合門檻 0 條` = 嗰刻冇夠熱嘅新熱點，正常；想強制試：`TRENDS_HOURS=48 MIN_TRAFFIC=200 ...`。

## 5. 清測試殘留

```bash
rm -f ~/hk-trends-tg/state.json
```

## 6. launchd 排程（每 2 分鐘）

```bash
cd ~/hk-trends-tg
sed -i '' "s|/Users/YOURNAME/hk-trends-tg|$HOME/hk-trends-tg|g" com.user.hk-trends-tg.plist
cp com.user.hk-trends-tg.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.user.hk-trends-tg.plist 2>/dev/null \
  || launchctl load ~/Library/LaunchAgents/com.user.hk-trends-tg.plist
launchctl start com.user.hk-trends-tg
sleep 5 && tail -n 40 run.log
```

改設定後重載：

```bash
launchctl bootout gui/$(id -u)/com.user.hk-trends-tg 2>/dev/null \
  || launchctl unload ~/Library/LaunchAgents/com.user.hk-trends-tg.plist
# 再重做上面 bootstrap/load
```

## 常見錯誤

| run.log / 畫面 | 處理 |
|---|---|
| `context length ... too small` | 模型載入 context 太細 → LM Studio 設 Context Length ≥ 4096 重載；Ollama 確認 `.env` `MODEL_NUM_CTX=4096`。**唔好將長文件餵本地模型。** |
| `FATAL: 搵唔到 prompt 檔` | `analysis_prompt.md` 唔喺同資料夾 |
| `WARN: 抓 Trending Now 暫時失敗` | 偶爾出現無妨；連續出現（尤其 `RPC HTTP 429`）→ plist `StartInterval` 由 120 調到 300+ |
| `FATAL: ...解析失敗（介面可能改咗）` | Google 內部介面變咗，見 `SETUP.md` Plan B |
| `[XXX] 失敗，跳過：Connection refused` | 本地模型未開 / `MODEL_BASE_URL` 錯 |
| `[XXX] 失敗，跳過：Telegram 回傳錯誤` | token / chat_id 錯，或 bot 唔喺群 |
| Telegram 冇反應但 log 話已推送 | `TG_CHAT_ID` 要係負數 supergroup id，重攞 |
| launchd 冇跑 | plist 路徑未 `sed` / 未 bootstrap |

## 調參（改 `.env`）

`TRENDS_HOURS`(6) `MIN_TRAFFIC`(500) `INCLUDE_ENDED`(0) `MAX_PUSH_PER_RUN`(5)
`DEDUP_TTL_HOURS`(48) `MAX_CHARS`(100) `MODEL_TIMEOUT`(90) `MODEL_NUM_CTX`(4096)
排程秒數改 plist 的 `<integer>`。
