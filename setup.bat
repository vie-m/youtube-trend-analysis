@echo off
REM One-time setup: makes a private Python environment (.venv) and installs the packages.
cd /d "%~dp0"

if exist .venv\Scripts\python.exe goto install

echo Creating Python environment in .venv ...
py -3.12 -m venv .venv 2>nul || python -m venv .venv
if not exist .venv\Scripts\python.exe (
    echo Could not create .venv. Is Python 3.10+ installed?
    pause
    exit /b 1
)

:install
echo Installing packages from requirements.txt (first time takes a few minutes) ...
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Install FAILED. Scroll up to read the error.
    pause
    exit /b 1
)

if not exist .env (
    copy .env.example .env >nul
    echo Created .env from .env.example. Open it and paste your API key.
)

echo.
echo Setup finished.
pause
