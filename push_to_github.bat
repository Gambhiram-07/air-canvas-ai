@echo off
title Push Air Canvas AI to GitHub
echo ========================================================
echo       Pushing Air Canvas AI to Gambhiram-07/air-canvas-ai
echo ========================================================
echo.
cd /d "%~dp0"
echo Current directory: %CD%
echo.
echo Setting up remote and branch...
git remote set-url origin https://github.com/Gambhiram-07/air-canvas-ai.git
git branch -M main
echo.
echo Pushing to GitHub...
git push -u origin main
echo.
if errorlevel 1 (
    echo.
    echo Push failed. If it asked to authenticate, please sign in with your GitHub account.
) else (
    echo.
    echo ========================================================
    echo SUCCESS! Your code is now live on GitHub:
    echo https://github.com/Gambhiram-07/air-canvas-ai
    echo ========================================================
)
echo.
pause
