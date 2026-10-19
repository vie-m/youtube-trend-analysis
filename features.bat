@echo off
REM Step 4: clean data + add features -> SQLite table video_features and data\processed\video_features.csv
REM No API calls. Run again any time (the table is rebuilt from scratch).
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo Run setup.bat first.
    pause
    exit /b 1
)
.venv\Scripts\python.exe src\features.py
pause
