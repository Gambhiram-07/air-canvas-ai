@echo off
title Building Air Canvas AI Standalone Executable...
echo ===================================================
echo     Building Air Canvas AI Standalone Executable
echo ===================================================
echo.
cd /d "%~dp0"
if exist ".venv\Scripts\pyinstaller.exe" (
    ".venv\Scripts\pyinstaller.exe" --noconfirm --onedir --windowed --name "AirCanvasAI" --collect-all mediapipe --collect-all cv2 main.py
    echo.
    echo ===================================================
    echo Build complete!
    echo Output directory: dist\AirCanvasAI\
    echo Executable:       dist\AirCanvasAI\AirCanvasAI.exe
    echo ===================================================
) else (
    echo Error: PyInstaller not found in .venv.
)
pause
