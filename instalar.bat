@echo off
REM ===================================================================
REM  BEEP STREAM - preparar el entorno de desarrollo
REM
REM  Instala las dependencias de Python y descarga el modelo de voz.
REM  Solo hace falta ejecutarlo una vez, con doble clic.
REM
REM  Para USAR el programa no hace falta nada de esto: hay un
REM  instalador en la pagina de Releases.
REM ===================================================================
setlocal
cd /d "%~dp0"
title BEEP STREAM - Preparar el entorno

echo.
echo  ==================================================
echo    BEEP STREAM - preparar el entorno
echo  ==================================================
echo.

REM --- Python -------------------------------------------------------
set PY=
py -3.11 --version >nul 2>&1 && set PY=py -3.11
if not defined PY ( python --version >nul 2>&1 && set PY=python )

if not defined PY (
    echo  [FALLO] No se encuentra Python.
    echo.
    echo  Instalalo desde https://www.python.org/downloads/
    echo  IMPORTANTE: marca "Add Python to PATH" durante la instalacion.
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%v in ('%PY% --version 2^>^&1') do echo  [OK] %%v

REM --- Dependencias -------------------------------------------------
echo.
echo  Instalando dependencias...
echo.
%PY% -m pip install --upgrade pip --quiet
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo  [FALLO] No se han podido instalar las dependencias.
    echo  Revisa tu conexion a internet y vuelve a intentarlo.
    pause
    exit /b 1
)

REM --- Modelo de voz ------------------------------------------------
echo.
if exist "model\am" (
    echo  [OK] Modelo de espanol ya presente.
) else (
    echo  Descargando el modelo de espanol ^(unos 40 MB^)...
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "$ErrorActionPreference='Stop';" ^
      "$u='https://alphacephei.com/vosk/models/vosk-model-small-es-0.42.zip';" ^
      "Invoke-WebRequest $u -OutFile '_model.zip' -UseBasicParsing;" ^
      "Expand-Archive '_model.zip' '_modeltmp' -Force;" ^
      "Move-Item (Get-ChildItem '_modeltmp' -Directory)[0].FullName 'model' -Force;" ^
      "Remove-Item '_model.zip','_modeltmp' -Recurse -Force"
    if errorlevel 1 (
        echo  [FALLO] No se ha podido descargar el modelo.
        echo  Descargalo a mano de https://alphacephei.com/vosk/models
        echo  y descomprime la carpeta interior como  model\
        pause
        exit /b 1
    )
    echo  [OK] Modelo instalado.
)

REM --- Comprobacion final -------------------------------------------
echo.
echo  ==================================================
echo    Comprobando el sistema
echo  ==================================================
%PY% comprobar.py

echo.
echo  ==================================================
echo    Para arrancar:            BeepStream.bat
echo    Para generar el .exe:     construir.bat
echo  ==================================================
echo.
pause
