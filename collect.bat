@echo off
REM Step 2: download channel + video data into data\raw\ (about 121 of 10,000 daily quota units).
REM Safe to run again: an unfinished run continues; a finished one asks before downloading again.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo Run setup.bat first.
    pause
    exit /b 1
)
.venv\Scripts\python.exe src\collect.py %*
pause
