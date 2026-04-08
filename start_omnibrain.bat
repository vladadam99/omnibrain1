@echo off
title OMNIBRAIN Cosmic Launcher
cd /d %~dp0

REM === ACTIVATE VENV ===
call venv\Scripts\activate

REM === START AUTO_TRADE BACKEND ===
start cmd /k "python auto_trade.py"

REM === START FRONTEND ===
cd frontend
start cmd /k "npm run dev"

REM === OPEN DASHBOARD (adjust port if needed) ===
timeout /t 3 >nul
start http://localhost:3000

exit
