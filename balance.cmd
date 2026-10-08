@echo off
setlocal
set "PYTHON_EXE=python"
if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if defined BALANCE_PYTHON set "PYTHON_EXE=%BALANCE_PYTHON%"
"%PYTHON_EXE%" -X utf8 "%~dp0balance.py" %*
exit /b %errorlevel%
