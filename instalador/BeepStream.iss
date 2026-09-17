; Instalador de BEEP STREAM para Inno Setup 6.
;
; No se compila a mano: lo hace construir.bat, que antes empaqueta el
; programa con PyInstaller y le pasa aqui la version leida de config.py.
;
;     construir.bat
;
; Se instala en la carpeta del usuario y no en Archivos de programa, a
; proposito. El programa guarda al lado del ejecutable su config.json y
; su palabras.txt, que es justo lo que el usuario tiene que poder
; editar con el bloc de notas; en Archivos de programa Windows lo
; impediria sin permisos de administrador. Instalando para un solo
; usuario no hace falta aceptar ningun aviso de administrador y los
; ficheros quedan donde se pueden tocar.

#ifndef Version
  #define Version "1.0.0"
#endif

#define Nombre      "BEEP STREAM"
#define Autor       "Airam Fuentes"
#define Web         "https://github.com/airamfuentes/beepstream"
#define Ejecutable  "BeepStream.exe"

[Setup]
AppId={{8E3B7A42-5C19-4F7D-9B2E-6A1D4C8F3E50}
AppName={#Nombre}
AppVersion={#Version}
AppVerName={#Nombre} {#Version}
AppPublisher={#Autor}
AppPublisherURL={#Web}
AppSupportURL={#Web}/issues
AppUpdatesURL={#Web}/releases
VersionInfoVersion={#Version}
VersionInfoDescription=Censor de audio en tiempo real para directos

DefaultDirName={autopf}\{#Nombre}
DefaultGroupName={#Nombre}
DisableProgramGroupPage=yes
DisableDirPage=auto
AllowNoIcons=yes

; Sin permisos de administrador: instalacion para el usuario actual.
; No se ofrece la alternativa de instalar para todos, porque esa acaba
; en Archivos de programa y ahi el programa no podria escribir su
; config.json ni dejar editar palabras.txt.
PrivilegesRequired=lowest

OutputDir=..\publicar
OutputBaseFilename=BeepStream-{#Version}-instalador
SetupIconFile=..\recursos\icono.ico
UninstallDisplayIcon={app}\{#Ejecutable}
UninstallDisplayName={#Nombre} {#Version}
WizardStyle=modern
; La ventana del instalador, en blanco y negro como el programa. Se dan
; las cuatro medidas separadas por comas y Inno elige la que toque
; segun el escalado de la pantalla.
WizardImageFile=lateral.bmp,lateral-125.bmp,lateral-150.bmp,lateral-200.bmp
WizardSmallImageFile=esquina.bmp,esquina-125.bmp,esquina-150.bmp,esquina-200.bmp
WizardImageStretch=no
; El estilo moderno se salta la pagina de bienvenida, que es justo la
; unica donde se ve la imagen grande.
DisableWelcomePage=no

; lzma2/max deja el instalador en torno a la mitad: la mayor parte del
; peso es el modelo de voz, que comprime muy bien.
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

LicenseFile=..\LICENSE

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "escritorio"; Description: "Crear un acceso directo en el escritorio"; \
    GroupDescription: "Accesos directos:"
Name: "inicio"; Description: "Arrancar BEEP STREAM al encender el ordenador"; \
    GroupDescription: "Opciones:"; Flags: unchecked

[Files]
; La carpeta entera que deja PyInstaller: ejecutable, librerias, modelo
; de voz, tipografias e iconos.
Source: "..\dist\BeepStream\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

; Estos dos van sueltos y se pueden editar. onlyifdoesntexist evita que
; una actualizacion se lleve por delante las palabras que haya añadido
; el usuario.
Source: "..\palabras.txt"; DestDir: "{app}"; Flags: onlyifdoesntexist
Source: "..\palabras_seguras.txt"; DestDir: "{app}"; Flags: onlyifdoesntexist
Source: "..\LEEME.txt"; DestDir: "{app}"; Flags: ignoreversion isreadme

[Icons]
Name: "{group}\{#Nombre}"; Filename: "{app}\{#Ejecutable}"
Name: "{group}\Editar la lista de palabras"; Filename: "{app}\palabras.txt"
Name: "{group}\Desinstalar {#Nombre}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#Nombre}"; Filename: "{app}\{#Ejecutable}"; \
    Tasks: escritorio

[Registry]
; El arranque automatico se apunta en la rama del usuario, que no pide
; permisos de administrador. uninsdeletevalue lo borra al desinstalar.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "{#Nombre}"; \
    ValueData: """{app}\{#Ejecutable}"""; \
    Flags: uninsdeletevalue; Tasks: inicio

[Run]
Filename: "{app}\{#Ejecutable}"; \
    Description: "Abrir {#Nombre} y ver la guia de instalacion"; \
    Flags: nowait postinstall skipifsilent

[InstallDelete]
; PyInstaller reparte sus librerias por _internal y de una version a
; otra cambian de nombre. Si no se vacia la carpeta antes de copiar,
; una actualizacion deja mezcladas las de las dos y el programa arranca
; con librerias de una y modulos de otra.
Type: filesandordirs; Name: "{app}\_internal"

[UninstallDelete]
; Lo que el programa crea al usarse y el instalador no puso: si no se
; borra aqui, la carpeta se queda vacia pero presente.
Type: files; Name: "{app}\config.json"
Type: files; Name: "{app}\prueba_original.wav"
Type: files; Name: "{app}\prueba_censurado.wav"
Type: dirifempty; Name: "{app}"
