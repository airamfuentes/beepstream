@echo off
REM ===================================================================
REM  BEEP STREAM - genera el ejecutable y el instalador
REM
REM  Dos pasos:
REM    1. PyInstaller deja la aplicacion en  dist\BeepStream\
REM    2. Inno Setup empaqueta esa carpeta en un instalador unico,
REM       que queda en  publicar\BeepStream-X.Y.Z-instalador.exe
REM
REM  Si solo hace falta la carpeta suelta:  construir.bat sininstalador
REM ===================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title BEEP STREAM - Construccion

REM --- Python -------------------------------------------------------
set PY=
py -3.11 --version >nul 2>&1 && set PY=py -3.11
if not defined PY ( python --version >nul 2>&1 && set PY=python )
if not defined PY (
    echo  [FALLO] No se encuentra Python. Ejecuta primero instalar.bat
    pause & exit /b 1
)

REM --- Requisitos ---------------------------------------------------
if not exist "model\am" (
    echo  [FALLO] Falta la carpeta model\. Ejecuta primero instalar.bat
    pause & exit /b 1
)

%PY% -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo  Instalando PyInstaller...
    %PY% -m pip install pyinstaller
    if errorlevel 1 ( echo  [FALLO] No se ha podido instalar. & pause & exit /b 1 )
)

REM La version vive en config.py y de ahi la lee todo lo demas.
for /f "delims=" %%v in ('%PY% -c "import config; print(config.VERSION)"') do set VERSION=%%v
if not defined VERSION (
    echo  [FALLO] No se puede leer la version de config.py
    pause & exit /b 1
)

echo.
echo  ==================================================
echo    BEEP STREAM %VERSION%
echo  ==================================================

REM --- Iconos -------------------------------------------------------
REM Se regeneran siempre: son baratos y asi no se publica nunca un
REM ejecutable con un icono viejo.
%PY% -c "import PIL" >nul 2>&1
if not errorlevel 1 (
    echo.
    echo  Generando iconos e imagenes...
    %PY% herramientas\generar_iconos.py
) else (
    echo  [AVISO] Sin Pillow no se regeneran los iconos. Se usan los que hay.
)

REM --- Empaquetado --------------------------------------------------
echo.
echo  Limpiando compilaciones anteriores...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo.
echo  Empaquetando ^(un par de minutos^)...
echo.

REM --onedir y no --onefile a proposito: con --onefile Windows
REM descomprime el modelo de voz en un temporal en cada arranque, lo que
REM anade varios segundos de espera y hace que algunos antivirus marquen
REM el ejecutable.
%PY% -m PyInstaller ^
    --name BeepStream ^
    --onedir ^
    --windowed ^
    --noconfirm ^
    --clean ^
    --icon recursos\icono.ico ^
    --collect-all vosk ^
    --collect-all sounddevice ^
    --collect-all pyaudiowpatch ^
    --add-data "model;model" ^
    --add-data "recursos;recursos" ^
    --add-data "palabras.txt;." ^
    --add-data "palabras_seguras.txt;." ^
    --add-data "beep.wav;." ^
    main.py

if errorlevel 1 (
    echo.
    echo  [FALLO] El empaquetado ha fallado. Revisa los mensajes de arriba.
    pause & exit /b 1
)

REM Los ficheros que el usuario tiene que poder editar van sueltos, no
REM dentro de _internal, donde no se pueden tocar comodamente.
REM config.json NO se copia: lo crea el programa en el primer arranque
REM con los valores por defecto, para no repartir los dispositivos de
REM audio de quien haya compilado.
echo.
echo  Copiando ficheros editables...
copy /y palabras.txt         "dist\BeepStream\" >nul
copy /y palabras_seguras.txt "dist\BeepStream\" >nul
copy /y beep.wav             "dist\BeepStream\" >nul
copy /y LEEME.txt            "dist\BeepStream\" >nul

if /i "%~1"=="sininstalador" goto :solo_carpeta

REM --- Instalador ---------------------------------------------------
set ISCC=
for %%p in (
    "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
    "%ProgramFiles%\Inno Setup 6\ISCC.exe"
    "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
) do if exist %%p set ISCC=%%~p

if not defined ISCC (
    echo.
    echo  Inno Setup no esta instalado: hace falta para crear el instalador.
    where winget >nul 2>&1
    if errorlevel 1 (
        echo  Descargalo de https://jrsoftware.org/isdl.php y repite.
        goto :solo_carpeta
    )
    echo  Instalandolo con winget...
    winget install --id JRSoftware.InnoSetup --silent --accept-source-agreements --accept-package-agreements
    for %%p in (
        "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
        "%ProgramFiles%\Inno Setup 6\ISCC.exe"
        "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
    ) do if exist %%p set ISCC=%%~p
)

if not defined ISCC (
    echo  [AVISO] Sigue sin encontrarse Inno Setup. Se deja solo la carpeta.
    goto :solo_carpeta
)

echo.
echo  Creando el instalador...
if not exist publicar mkdir publicar
"%ISCC%" /DVersion=%VERSION% "instalador\BeepStream.iss"
if errorlevel 1 (
    echo.
    echo  [FALLO] Inno Setup ha dado error.
    pause & exit /b 1
)

echo.
echo  ==================================================
echo    LISTO
echo.
echo    publicar\BeepStream-%VERSION%-instalador.exe
echo.
echo    Eso es lo unico que hay que repartir.
echo  ==================================================
echo.
pause
exit /b 0

:solo_carpeta
echo.
echo  ==================================================
echo    LISTO ^(sin instalador^)
echo.
echo    dist\BeepStream\BeepStream.exe
echo.
echo    Copia la carpeta  dist\BeepStream  entera.
echo  ==================================================
echo.
pause
exit /b 0
