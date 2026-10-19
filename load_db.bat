@echo off
REM Step 3: load data\raw\ snapshots into db\youtube.db. No API calls. Safe to run again (no duplicates).
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo Run setup.bat first.
    pause
    exit /b 1
)
.venv\Scripts\python.exe src\load_db.py
pause
