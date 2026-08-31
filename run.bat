@echo off
rem 排程器每 2 分鐘會經 run_hidden.vbs 叫呢個檔。手動跑亦得。
cd /d "%~dp0"

set "PY="
where python  >nul 2>nul && set "PY=python"
if not defined PY where py      >nul 2>nul && set "PY=py -3"
if not defined PY where python3 >nul 2>nul && set "PY=python3"
if not defined PY (
  echo [run.bat] 搵唔到 Python，請先裝 Python 3 並剔 "Add to PATH">> run.log
  exit /b 1
)

%PY% "%~dp0trends_tg_bot.py" >> "%~dp0run.log" 2>&1
