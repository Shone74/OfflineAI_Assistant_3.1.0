@echo off
rem Offline AI Assistant — launcher (uveren Python 3.11 okruzenje)
rem "python" na PATH-u pokrece 3.14 koji nema zavisnosti; 3.11 je verified env.
setlocal
set PY311=C:\Users\Bota\AppData\Local\Programs\Python\Python311\python.exe
if not exist "%PY311%" (
    echo [GRESKA] Python 3.11 nije pronadjen na: %PY311%
    pause
    exit /b 1
)
cd /d "%~dp0"
"%PY311%" run.py %*
endlocal
