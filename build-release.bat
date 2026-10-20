@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\build_release.ps1"
if errorlevel 1 (
  echo.
  echo Build failed. See the log path above.
  pause
  exit /b 1
)
echo.
echo Build complete.
pause
