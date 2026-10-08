@echo off
title Air Canvas AI
echo ===================================================
echo               Launching Air Canvas AI...
echo ===================================================
echo.
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" main.py
) else (
    python main.py
)
if errorlevel 1 (
    echo.
    echo Application exited with an error.
    pause
)
