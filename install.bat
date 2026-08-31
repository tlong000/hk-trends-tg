@echo off
chcp 65001 >nul
rem Windows one-click installer - double click this file
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
echo.
pause
