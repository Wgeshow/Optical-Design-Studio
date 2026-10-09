@echo off
setlocal
if not defined S4_PYTHON set "S4_PYTHON=%USERPROFILE%\anaconda3\envs\s4_updated\pythonw.exe"
if not exist "%S4_PYTHON%" set "S4_PYTHON=python"
start "AI Search" "%S4_PYTHON%" "%~dp0qt_app.py" --page "AI Search" %*
