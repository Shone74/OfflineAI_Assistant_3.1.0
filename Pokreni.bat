@echo off
rem Offline AI Assistant — launcher (portable Python 3.11 resolution)
rem Priority: project .venv -> py -3.11 launcher -> hardcoded path -> fail with guidance.
setlocal
rem 1) Prefer project .venv if it exists
if exist "%~dp0.venv\Scripts\python.exe" (
    set PYTHON_EXE=%~dp0.venv\Scripts\python.exe
) else (
    rem 2) Use py launcher to locate Python 3.11 (works on Windows with py launcher)
    py -3.11 -c "import sys; exit(0)" >nul 2>&1
    if not errorlevel 1 (
        set PYTHON_EXE=py -3.11
    ) else (
        rem 3) Fallback: explicit verified path (machine-specific)
        set PY311=C:\Users\Bota\AppData\Local\Programs\Python\Python311\python.exe
        if exist "%PY311%" (
            set PYTHON_EXE=%PY311%
        ) else (
            echo [GRESKA] Python 3.11 nije pronadjen (ni .venv, ni 'py -3.11', ni hardkodiran put).
            pause
            exit /b 1
        )
    )
cd /d "%~dp0"
"%PYTHON_EXE%" run.py %*
endlocal
