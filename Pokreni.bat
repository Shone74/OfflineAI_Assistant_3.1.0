@echo off
rem Offline AI Assistant launcher (Python 3.11)
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto use_venv

py -3.11 -V >nul 2>&1
if not errorlevel 1 goto use_py_launcher

set "PY311=C:\Users\Bota\AppData\Local\Programs\Python\Python311\python.exe"
if exist "%PY311%" goto use_python_path

echo [ERROR] Python 3.11 was not found.
pause
exit /b 1

:use_venv
".venv\Scripts\python.exe" run.py %*
exit /b %errorlevel%

:use_py_launcher
py -3.11 run.py %*
exit /b %errorlevel%

:use_python_path
"%PY311%" run.py %*
exit /b %errorlevel%
