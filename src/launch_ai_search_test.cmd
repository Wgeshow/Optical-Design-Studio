@echo off
setlocal
if not defined S4_PYTHON set "S4_PYTHON=%USERPROFILE%\anaconda3\envs\s4_updated\pythonw.exe"
if not exist "%S4_PYTHON%" set "S4_PYTHON=python"
start "AI Search test" "%S4_PYTHON%" "%~dp0qt_app.py" --library "%~dp0..\ai-search-test" --project "%~dp0..\ai-search-test\AI_Search_Test.json" --page "AI Search" %*
