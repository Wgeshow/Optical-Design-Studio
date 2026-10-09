@echo off
setlocal
if not defined S4_PYTHON set "S4_PYTHON=%USERPROFILE%\anaconda3\envs\s4_updated\python.exe"
if not exist "%S4_PYTHON%" set "S4_PYTHON=python"
"%S4_PYTHON%" "%~dp0qt_app.py" %*
if errorlevel 1 (
  echo.
  echo Run install_desktop_dependencies.cmd in the S4 Python 3.12 environment.
  echo See DESKTOP_GUIDE.md for setup and troubleshooting.
  pause
)
