@echo off
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0BUILD_WINDOWS.ps1"
if errorlevel 1 (
  echo.
  echo BUILD FAILED. See the error above.
  pause
  exit /b 1
)
echo.
echo BUILD COMPLETED. Opening the release folder.
start "" explorer.exe "%~dp0release"
pause
