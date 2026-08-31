#!/bin/bash
# launchd 會 call 呢個 wrapper：載入 .env → 執行 Python → 寫 log
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

# 載入 .env（同一資料夾）
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

# 搵可用嘅 python3（Homebrew / 系統 都照顧到）
PY="$(command -v python3 || true)"
[ -z "$PY" ] && PY="/usr/bin/python3"

exec "$PY" "$HERE/trends_tg_bot.py" >> "$HERE/run.log" 2>&1
