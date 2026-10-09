@echo off
setlocal
if not defined S4_PYTHON set "S4_PYTHON=%USERPROFILE%\anaconda3\envs\s4_updated\python.exe"
if not exist "%S4_PYTHON%" set "S4_PYTHON=python"
"%S4_PYTHON%" -m pip install -r "%~dp0requirements-desktop.txt"
if errorlevel 1 pause
