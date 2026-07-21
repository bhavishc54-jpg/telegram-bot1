@echo off
cd /d "C:\Users\vashu\OneDrive\Documents\Telegram Bot"
".venv\Scripts\python.exe" -m app.main >> "bot-startup.log" 2>&1
