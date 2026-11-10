@echo off
setlocal
cd /d "%~dp0"
if not exist logs mkdir logs
python daily_runner.py >> logs\daily_runner.log 2>&1
exit /b %errorlevel%
