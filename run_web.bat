@echo off
title Air Canvas AI — Web App Launcher
echo ===================================================
echo       Launching Air Canvas AI (Web Version)...
echo ===================================================
echo.
cd /d "%~dp0"
if exist ".venv\Scripts\streamlit.exe" (
    ".venv\Scripts\streamlit.exe" run app.py
) else (
    streamlit run app.py
)
if errorlevel 1 (
    echo.
    echo Web app failed to start.
    pause
)
