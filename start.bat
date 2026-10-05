@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title 咏伴 Utatomo - 后端日志
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
echo.
echo   咏伴 Utatomo ^| 歌词跟唱助手
echo   作者 @朝禊ASOGI  https://space.bilibili.com/315312
echo   关闭此日志窗口或前端窗口，工具将一起退出。
echo.
if not exist ".venv\Scripts\python.exe" goto setup
".venv\Scripts\python.exe" -c "import PySide6, fugashi, cmudict, websocket, winrt.windows.media.control" >nul 2>nul
if errorlevel 1 goto setup
goto run
:setup
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap.ps1"
if errorlevel 1 goto failed
:run
".venv\Scripts\python.exe" main.py %*
if errorlevel 1 goto failed
exit /b 0
:failed
echo.
echo   启动失败。请查看上方错误或 data\logs\utatomo.log。
pause
exit /b 1
