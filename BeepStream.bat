@echo off
REM Arranca BEEP STREAM sin ventana de consola detras.
cd /d "%~dp0"

py -3.11 --version >nul 2>&1
if not errorlevel 1 (
    start "" pyw -3.11 main.py
    exit /b 0
)

pythonw --version >nul 2>&1
if not errorlevel 1 (
    start "" pythonw main.py
    exit /b 0
)

echo No se encuentra Python. Ejecuta primero instalar.bat
pause
