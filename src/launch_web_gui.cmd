@echo off
setlocal
rem Prefer the existing environment containing the compatible MKL 2023 runtime.
if not defined S4_PYTHON set "S4_PYTHON=%USERPROFILE%\anaconda3\envs\s4_updated\python.exe"
if not exist "%S4_PYTHON%" set "S4_PYTHON=python"
"%S4_PYTHON%" "%~dp0app.py" %*
if errorlevel 1 (
  echo.
  echo Use 64-bit Python 3.12 with the project's MKL 2023.1 dependencies.
  echo See PEAK_SEARCH_GUIDE.md for details.
  pause
)
