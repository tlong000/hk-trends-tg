# install.ps1 — Windows 一鍵安裝精靈（由 install.bat 叫起）
# 自動：偵測本地模型、驗 Telegram token、搵群組 chat id、寫 .env、測試、開排程。
# 你只需要：貼一次 bot token + 喺群組發一句嘢。

$ErrorActionPreference = 'Stop'
$DIR = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
Set-Location $DIR

function Line { Write-Host ("-" * 44) }
function Die($msg) { Write-Host "X $msg" -ForegroundColor Red; Write-Host; Read-Host "按 Enter 離開" | Out-Null; exit 1 }

Write-Host "香港熱搜 -> 本地模型 -> Telegram   安裝精靈"
Write-Host "資料夾：$DIR"
Line

# ---- 1. Python ----
$PY = $null
foreach ($c in @('python','python3','py')) {
  $p = Get-Command $c -ErrorAction SilentlyContinue
  if ($p) { $PY = if ($c -eq 'py') { 'py -3' } else { $p.Source }; break }
}
if (-not $PY) { Die "搵唔到 Python 3。去 python.org 裝，安裝時剔『Add python.exe to PATH』，再雙擊 install.bat。" }
Write-Host "OK  Python: $PY"

# ---- 2. 偵測本地模型 ----
$MODEL_API = $null; $MODEL_BASE = $null; $MODEL_NAME = $null
try {
  $m = Invoke-RestMethod -Uri 'http://127.0.0.1:1234/v1/models' -TimeoutSec 4
  if ($m.data) { $MODEL_API='openai'; $MODEL_BASE='http://127.0.0.1:1234'; $MODEL_NAME=$m.data[0].id }
} catch {}
if (-not $MODEL_API) {
  try {
    $o = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 4
    if ($o.models) { $MODEL_API='ollama'; $MODEL_BASE='http://127.0.0.1:11434'; $MODEL_NAME=$o.models[0].name }
  } catch {}
}
if (-not $MODEL_API) {
  Die "偵測唔到本地模型。LM Studio：Developer 分頁 -> Server -> Start（port 1234），載入模型時 Context Length 設 8192，再重試。"
}
Write-Host "OK  偵測到 $MODEL_API   model = $MODEL_NAME"

# ---- 3. Telegram token ----
Line
Write-Host "貼上你嘅 Telegram bot token（BotFather 嗰串，例 123456:AAE...）"
$TOKEN = $null
while ($true) {
  $TOKEN = (Read-Host "token").Trim().Trim('"')
  try {
    $me = Invoke-RestMethod -Uri "https://api.telegram.org/bot$TOKEN/getMe" -TimeoutSec 8
    if ($me.ok) { Write-Host ("OK  認證成功: @" + $me.result.username); break }
  } catch {}
  Write-Host "X  呢個 token 唔通過，再試。" -ForegroundColor Yellow
}

# ---- 4. 自動搵群組 chat id ----
Line
Write-Host "而家去你個 Telegram 群組（bot 要已經喺入面），隨便發一句嘢，例如: ping"
Read-Host "發咗就按 Enter" | Out-Null
$CHAT = $null
try {
  $u = Invoke-RestMethod -Uri "https://api.telegram.org/bot$TOKEN/getUpdates" -TimeoutSec 8
  $g = $u.result | ForEach-Object {
        $msg = $_.message; if (-not $msg) { $msg = $_.channel_post }
        if ($msg -and $msg.chat -and ($msg.chat.type -in @('group','supergroup'))) { $msg.chat }
      }
  if ($g) { $CHAT = ($g | Select-Object -Last 1).id }
} catch {}
if (-not $CHAT) {
  Write-Host "X  自動攞唔到（bot 未入群 / 未關 Group Privacy）。" -ForegroundColor Yellow
  $CHAT = Read-Host "已知就打 chat id（負數），唔知就直接 Enter 收工"
  if (-not $CHAT) { Die "冇 chat id，停。見 SETUP-slim.md Part 2。" }
}
Write-Host "OK  群組 chat id = $CHAT"

# ---- 5. 寫 .env ----
$envLines = @(
  "TRENDS_GEO=HK","TRENDS_HOURS=6","MIN_TRAFFIC=500","INCLUDE_ENDED=0",
  "MAX_PUSH_PER_RUN=5","DEDUP_TTL_HOURS=48","MAX_CHARS=100",
  "STATE_FILE=state.json","PROMPT_FILE=analysis_prompt.md",
  "MODEL_API=$MODEL_API","MODEL_BASE_URL=$MODEL_BASE","MODEL_NAME=$MODEL_NAME",
  "MODEL_API_KEY=","MODEL_TIMEOUT=120","MODEL_NUM_CTX=4096",
  "TG_BOT_TOKEN=$TOKEN","TG_CHAT_ID=$CHAT","DRY_RUN=0"
)
Set-Content -Path (Join-Path $DIR '.env') -Value $envLines -Encoding UTF8
Write-Host "OK  .env 已寫好"

function RunPy($extraEnv) {
  foreach ($k in $extraEnv.Keys) { Set-Item "env:$k" $extraEnv[$k] }
  try {
    if ($PY -eq 'py -3') { $o = & py -3 (Join-Path $DIR 'trends_tg_bot.py') 2>&1 }
    else                 { $o = & $PY   (Join-Path $DIR 'trends_tg_bot.py') 2>&1 }
  } catch { $o = "$_" }
  foreach ($k in $extraEnv.Keys) { Remove-Item "env:$k" -ErrorAction SilentlyContinue }
  $o | ForEach-Object { Write-Host $_ }
  return ($o -join "`n")
}

# ---- 6. 測試 ----
Line; Write-Host "測試 1/3：抓取+過濾（唔會發 TG）"
[void](RunPy @{ MODEL_API='mock'; DRY_RUN='1' })

Line; Write-Host "測試 2/3：直接叫本地模型答一句（確認 LM Studio + context OK）"
try {
  $body = @{ model=$MODEL_NAME; stream=$false; temperature=0.3;
             messages=@(@{role='user'; content='用繁體中文一句話自我介紹。'}) } | ConvertTo-Json -Depth 5
  $r = Invoke-RestMethod -Uri "$MODEL_BASE/v1/chat/completions" -Method Post -ContentType 'application/json; charset=utf-8' -Body $body -TimeoutSec 60
  $reply = $r.choices[0].message.content
  if ($reply) { Write-Host ("模型回應: " + $reply) }
} catch {
  $msg = "$_"
  Write-Host ("X  叫模型失敗: " + $msg) -ForegroundColor Yellow
  if ($msg -match 'context .*too small|context length|too small for this request') {
    Die "LM Studio 報 context 太細: 喺 LM Studio 重新載入個模型, Context Length 設 8192, 再雙擊 install.bat。"
  }
  Write-Host "   (唔阻住繼續, 但正式運行都可能失敗。檢查 LM Studio Server 有冇 Start、model 名啱唔啱。)" -ForegroundColor Yellow
}

Line; Write-Host "測試 3/3：完整流程（真模型，唔發 TG）"
$out3 = RunPy @{ DRY_RUN='1' }
if ($out3 -match 'context .*too small|context length|too small for this request') {
  Die "LM Studio 報 context 太細: 重新載入模型, Context Length 設 8192, 再雙擊 install.bat。"
}
if ($out3 -match '：0 條') {
  Write-Host "(呢刻冇夠熱嘅新熱點, 所以未真正生成解讀 —— 正常。排程開咗之後有熱點自然會推。)" -ForegroundColor DarkGray
}

Line
$ans = Read-Host "打 y 而家強制發一次測試訊息去群組（會臨時放寬門檻），其他鍵跳過"
if ($ans -eq 'y') {
  Remove-Item (Join-Path $DIR 'state.json') -ErrorAction SilentlyContinue
  [void](RunPy @{ MIN_TRAFFIC='1'; INCLUDE_ENDED='1'; MAX_PUSH_PER_RUN='1' })
  Write-Host "-> 去 Telegram 群組睇下收到未（呢條係放寬門檻嘅測試訊息）。"
}

# ---- 7. 排程（每 2 分鐘） ----
Line
$ans = Read-Host "打 y 開『每 2 分鐘自動跑』排程, 其他鍵之後自己開"
if ($ans -eq 'y') {
  $vbs = Join-Path $DIR 'run_hidden.vbs'
  $done = $false
  # 首選：ScheduledTasks 模組（Win8+），冇引號地獄
  try {
    $act = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument ('"{0}"' -f $vbs) -WorkingDirectory $DIR
    $trg = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
             -RepetitionInterval (New-TimeSpan -Minutes 2) -RepetitionDuration ([TimeSpan]::FromDays(3650))
    $set = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
             -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName 'hk-trends-tg' -Action $act -Trigger $trg -Settings $set -Force -ErrorAction Stop | Out-Null
    Start-ScheduledTask -TaskName 'hk-trends-tg' -ErrorAction SilentlyContinue
    $done = $true
  } catch { Write-Host ("（Register-ScheduledTask 唔得: " + $_ + " —— 改用 schtasks）") -ForegroundColor DarkGray }

  if (-not $done) {
    try {
      & schtasks /Create /TN hk-trends-tg /TR ('"{0}"' -f $vbs) /SC MINUTE /MO 2 /RL LIMITED /F | Out-Null
      & schtasks /Run /TN hk-trends-tg | Out-Null
      $done = $true
    } catch { Write-Host ("X  schtasks 都失敗: " + $_) -ForegroundColor Yellow }
  }

  if ($done) {
    Start-Sleep -Seconds 6
    Write-Host "OK  排程『hk-trends-tg』已建立。log: $DIR\run.log"
    if (Test-Path (Join-Path $DIR 'run.log')) { Write-Host '--- run.log 最後幾行 ---'; Get-Content (Join-Path $DIR 'run.log') -Tail 15 }
    Write-Host "    停:   schtasks /Delete /TN hk-trends-tg /F"
    Write-Host "    改頻率: schtasks /Change /TN hk-trends-tg /RI 5   (或用「工作排程器」GUI)"
  } else {
    Write-Host "自己喺 PowerShell 行呢句開排程:" -ForegroundColor Yellow
    Write-Host ('  schtasks /Create /TN hk-trends-tg /TR ''"{0}"'' /SC MINUTE /MO 2 /F' -f $vbs)
  }
}

Line; Write-Host "全部搞掂" -ForegroundColor Green
Read-Host "按 Enter 關閉" | Out-Null
