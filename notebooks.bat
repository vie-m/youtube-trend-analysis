@echo off
REM Opens JupyterLab in your browser, in the notebooks folder. Close this window to stop it.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo Run setup.bat first.
    pause
    exit /b 1
)
.venv\Scripts\python.exe -m jupyter lab --notebook-dir=notebooks
pause
