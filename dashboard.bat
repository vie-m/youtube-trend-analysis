@echo off
REM Opens the Streamlit dashboard in your browser. Close this window to stop it.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo Run setup.bat first.
    pause
    exit /b 1
)
.venv\Scripts\python.exe -m streamlit run dashboard\app.py
pause
