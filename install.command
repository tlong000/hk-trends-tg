#!/bin/bash
# 安裝.command — 喺第二部電腦（LM Studio 嗰部）雙擊執行
# 會自動偵測本地模型、驗證 Telegram、寫 .env、測試、（可選）開排程。
# 你只需要：貼一次 bot token + 喺群組發一句嘢。

cd "$(dirname "$0")" || exit 1
DIR="$(pwd)"
PY="$(command -v python3 || echo /usr/bin/python3)"

line() { printf '\n──────────────────────────────────────\n'; }
pause_exit() { echo; read -r -p "按 Enter 關閉視窗"; exit "${1:-0}"; }

echo "香港熱搜 → 本地模型 → Telegram   安裝精靈"
echo "資料夾：$DIR"
line

# ---- 1. Python ----
if ! "$PY" --version >/dev/null 2>&1; then
  echo "✗ 搵唔到 python3。請喺 Terminal 行： xcode-select --install  裝完再雙擊 install.command。"
  pause_exit 1
fi
echo "✓ python3： $("$PY" --version 2>&1)"

# ---- 2. 偵測本地模型 ----
MODEL_API=""; MODEL_BASE_URL=""; MODEL_NAME=""
LMS=$(curl -s --max-time 4 http://127.0.0.1:1234/v1/models 2>/dev/null || true)
if printf '%s' "$LMS" | grep -q '"data"'; then
  MODEL_API="openai"; MODEL_BASE_URL="http://127.0.0.1:1234"
  MODEL_NAME=$(printf '%s' "$LMS" | "$PY" -c "import sys,json;d=json.load(sys.stdin);print(d['data'][0]['id'])" 2>/dev/null)
  echo "✓ 偵測到 LM Studio： model = $MODEL_NAME"
else
  OLL=$(curl -s --max-time 4 http://127.0.0.1:11434/api/tags 2>/dev/null || true)
  if printf '%s' "$OLL" | grep -q '"models"'; then
    MODEL_API="ollama"; MODEL_BASE_URL="http://127.0.0.1:11434"
    MODEL_NAME=$(printf '%s' "$OLL" | "$PY" -c "import sys,json;d=json.load(sys.stdin);print(d['models'][0]['name'])" 2>/dev/null)
    echo "✓ 偵測到 Ollama： model = $MODEL_NAME"
  fi
fi
if [ -z "$MODEL_API" ]; then
  echo "✗ 偵測唔到本地模型服務。"
  echo "  LM Studio：Developer 分頁 → Server → Start（port 1234），"
  echo "             載入模型時 Context Length 設 8192。搞掂再雙擊 install.command。"
  pause_exit 1
fi

# ---- 3. Telegram bot token ----
line
echo "貼上你嘅 Telegram bot token（BotFather 俾嗰串，例 123456:AAE...）"
GETME=""
while :; do
  read -r -p "token： " TG_BOT_TOKEN
  TG_BOT_TOKEN=$(printf '%s' "$TG_BOT_TOKEN" | tr -d ' "')
  GETME=$(curl -s --max-time 8 "https://api.telegram.org/bot${TG_BOT_TOKEN}/getMe" || true)
  printf '%s' "$GETME" | grep -q '"ok":true' && break
  echo "  ✗ 呢個 token 唔通過，再試一次。"
done
BOTNAME=$(printf '%s' "$GETME" | "$PY" -c "import sys,json;print(json.load(sys.stdin)['result']['username'])" 2>/dev/null)
echo "  ✓ 認證 OK： @$BOTNAME"

# ---- 4. 自動搵群組 chat id ----
line
echo "而家去你個 Telegram 群組（bot 要已經喺入面），隨便發一句嘢，例如： ping"
read -r -p "發咗未？發咗就按 Enter " _
TG_CHAT_ID=$(curl -s --max-time 8 "https://api.telegram.org/bot${TG_BOT_TOKEN}/getUpdates" | "$PY" -c "
import sys,json
try: d=json.load(sys.stdin)
except Exception: sys.exit()
picks=[]
for u in d.get('result',[]):
    m=u.get('message') or u.get('channel_post') or {}
    c=m.get('chat',{})
    if c.get('type') in ('group','supergroup'):
        picks.append(c['id'])
print(picks[-1] if picks else '')
" 2>/dev/null)
if [ -z "$TG_CHAT_ID" ]; then
  echo "  ✗ 自動攞唔到（可能 bot 唔喺群，或要去 @BotFather 關咗 Group Privacy 再試）。"
  read -r -p "  如果你已知 chat id，打入嚟（負數）；唔知就直接 Enter 收工： " TG_CHAT_ID
  [ -z "$TG_CHAT_ID" ] && pause_exit 1
fi
echo "  ✓ 群組 chat id = $TG_CHAT_ID"

# ---- 5. 寫 .env ----
cat > .env <<EOF
TRENDS_GEO=HK
TRENDS_HOURS=6
MIN_TRAFFIC=500
INCLUDE_ENDED=0
MAX_PUSH_PER_RUN=5
DEDUP_TTL_HOURS=48
MAX_CHARS=100
STATE_FILE=state.json
PROMPT_FILE=analysis_prompt.md
MODEL_API=$MODEL_API
MODEL_BASE_URL=$MODEL_BASE_URL
MODEL_NAME=$MODEL_NAME
MODEL_API_KEY=
MODEL_TIMEOUT=120
MODEL_NUM_CTX=4096
TG_BOT_TOKEN=$TG_BOT_TOKEN
TG_CHAT_ID=$TG_CHAT_ID
DRY_RUN=0
EOF
chmod 600 .env
chmod +x run.sh trends_tg_bot.py 2>/dev/null
echo "✓ .env 已寫好（chmod 600，唔會入 git）"

# ---- 6. 測試 ----
line; echo "測試 1／2：抓取＋過濾（唔會發去 Telegram）"
MODEL_API=mock DRY_RUN=1 ./run.sh
tail -n 25 run.log

line; echo "測試 2／2：用你嘅本地模型寫解讀（仍然唔會發去 Telegram）"
DRY_RUN=1 ./run.sh
tail -n 30 run.log
if grep -qi "context .*too small\|context length" run.log; then
  line
  echo "⚠ LM Studio 報 context 太細：去 LM Studio 重新載入模型，Context Length 設 8192，"
  echo "  然後再雙擊 install.command一次即可。"
  pause_exit 1
fi

line
read -r -p "上面段解讀 OK 嗎？ 打 y 就正式發一次去群組，其他鍵跳過： " ans
if [ "$ans" = "y" ] || [ "$ans" = "Y" ]; then
  rm -f state.json
  ./run.sh
  tail -n 30 run.log
  echo "→ 去 Telegram 群組睇下收到未。"
fi

# ---- 7. 排程 ----
line
read -r -p "要而家開『每 2 分鐘自動跑』嗎？ 打 y 開，其他鍵之後自己開： " ans
if [ "$ans" = "y" ] || [ "$ans" = "Y" ]; then
  sed -i '' "s|/Users/YOURNAME/hk-trends-tg|$DIR|g" com.user.hk-trends-tg.plist
  cp com.user.hk-trends-tg.plist "$HOME/Library/LaunchAgents/"
  launchctl bootout "gui/$(id -u)/com.user.hk-trends-tg" 2>/dev/null
  launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.user.hk-trends-tg.plist" 2>/dev/null \
    || launchctl load "$HOME/Library/LaunchAgents/com.user.hk-trends-tg.plist"
  launchctl start com.user.hk-trends-tg
  echo "✓ 已開。log 睇 $DIR/run.log"
  echo "  想停： launchctl bootout gui/$(id -u)/com.user.hk-trends-tg"
  echo "  想改頻率： 改 com.user.hk-trends-tg.plist 個 <integer> 秒數，再雙擊 install.command一次。"
fi

line; echo "全部搞掂 ✅"
pause_exit 0
