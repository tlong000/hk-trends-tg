# SETUP（Windows）

第二部電腦係 Windows + LM Studio 就睇呢份。macOS 睇 `SETUP-slim.md`。

## 最快：一鍵安裝

1. 成個資料夾放去 Windows 電腦，例如 `C:\hk-trends-tg\`。
2. 裝好 **Python 3**（python.org），安裝時**剔「Add python.exe to PATH」**。
3. **LM Studio**：`Developer` 分頁 → `Server` → **Start**（port 1234）；
   載入你個 qwen 模型時，**Context Length 設 8192**。
4. 雙擊 **`install.bat`**。
   - SmartScreen 攔：撳「其他資訊」→「仍要執行」。
   - 精靈會：偵測模型、叫你貼一次 bot token、叫你喺群組發一句嘢，
     然後自動寫 `.env`、跑測試、（問你）開「每 2 分鐘」排程。

你要準備：Telegram bot token（BotFather）＋ bot 已加入你目標群組。

## 手動（一鍵失敗時）

開 **PowerShell**，`cd C:\hk-trends-tg`：

```powershell
# 1. 確認模型服務
Invoke-RestMethod http://127.0.0.1:1234/v1/models        # LM Studio，記低 data[0].id

# 2. 攞群組 chat id（先喺群組發一句嘢；<TOKEN> 換你嘅）
(Invoke-RestMethod "https://api.telegram.org/bot<TOKEN>/getUpdates").result.message.chat |
  Where-Object { $_.type -match 'group' } | Select-Object -Last 1 id,title

# 3. 由樣本整 .env
Copy-Item config.example.env .env
notepad .env
#   改：MODEL_NAME=<上面個 id>   TG_BOT_TOKEN=<你嘅>   TG_CHAT_ID=<負數>

# 4. 測試
$env:MODEL_API='mock'; $env:DRY_RUN='1'; python trends_tg_bot.py; ri env:MODEL_API,env:DRY_RUN
$env:DRY_RUN='1';       python trends_tg_bot.py; ri env:DRY_RUN     # 用真模型，未發 TG
python trends_tg_bot.py                                             # 正式發一次

# 5. 排程每 2 分鐘（靜默，冇黑框）
schtasks /Create /TN hk-trends-tg /TR "wscript.exe `"$PWD\run_hidden.vbs`"" /SC MINUTE /MO 2 /RL LIMITED /F
schtasks /Run /TN hk-trends-tg
Get-Content run.log -Tail 30
```

停 / 改：

```powershell
schtasks /Delete /TN hk-trends-tg /F          # 停埋刪除
schtasks /Change /TN hk-trends-tg /RI 5       # 改成每 5 分鐘（或用「工作排程器」GUI）
```

## 檔案（Windows 用到嘅）

| 檔 | 作用 |
|---|---|
| `install.bat` / `install.ps1` | 一鍵安裝精靈 |
| `run.bat` | 執行一次（排程器經 `run_hidden.vbs` 叫佢）|
| `run_hidden.vbs` | 靜默啟動 `run.bat`，唔會彈黑框 |
| `trends_tg_bot.py` | 主程式（自己會讀同資料夾嘅 `.env`）|
| `analysis_prompt.md` | 俾模型嘅提示（改語氣改呢個）|

## 常見錯誤（睇 `run.log`）

| 訊息 | 處理 |
|---|---|
| `context ... too small` | LM Studio 重載模型，Context Length ≥ 4096（建議 8192）|
| `搵唔到 Python` | 重裝 Python 並剔 Add to PATH；或用 `py -3` |
| `[XXX] 失敗，跳過：...Connection refused` | LM Studio Server 未 Start，或 port 唔係 1234 |
| `[XXX] 失敗，跳過：Telegram 回傳錯誤` | token / chat_id 錯，或 bot 唔喺群 |
| `WARN: 抓 Trending Now 暫時失敗` | 偶爾無妨；連續（尤其 `RPC HTTP 429`）→ `schtasks /Change /TN hk-trends-tg /RI 5` |
| `FATAL: ...解析失敗（介面可能改咗）` | Google 內部介面變咗，見 `SETUP.md` Plan B |

執行政策阻住 `install.ps1`？→ `install.bat` 已經用 `-ExecutionPolicy Bypass`；
直接跑就用：`powershell -ExecutionPolicy Bypass -File install.ps1`
