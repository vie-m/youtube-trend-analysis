@echo off
REM Tests that the API key in .env works (uses 1 of 10,000 free daily quota units).
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo Run setup.bat first.
    pause
    exit /b 1
)
.venv\Scripts\python.exe src\check_setup.py
pause
