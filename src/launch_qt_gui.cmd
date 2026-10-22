@echo off
setlocal
if defined S4_PYTHON (
  "%S4_PYTHON%" "%~dp0qt_app.py" %*
) else (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_windows.ps1" -Launch %*
)
if errorlevel 1 (
  echo.
  echo Automatic setup or application startup did not complete. Review the message above and retry.
  echo A custom S4_PYTHON override must include the complete desktop and native dependencies.
  pause
)
