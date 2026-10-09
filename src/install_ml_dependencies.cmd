@echo off
setlocal
set "S4_PYTHON=%USERPROFILE%\anaconda3\envs\s4_updated\python.exe"
if not exist "%S4_PYTHON%" set "S4_PYTHON=python"
"%S4_PYTHON%" -m pip install --only-binary=:all: --no-deps --target "%~dp0ml_dependencies" -r "%~dp0requirements-ml.txt"
if errorlevel 1 pause
