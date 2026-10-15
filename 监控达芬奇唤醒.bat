@echo off
setlocal
set "MONITOR=%~dp0scripts\monitor_resolve_wake.ps1"
if not exist "%MONITOR%" (
  echo Monitor script not found:
  echo %MONITOR%
  pause
  exit /b 1
)
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%MONITOR%"
echo.
pause
