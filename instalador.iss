; Instalador del Traductor de Pantalla (Inno Setup 6). Se compila con: python construir.py

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#ifndef CarpetaApp
  #define CarpetaApp "build\dist\TraductorDePantalla"
#endif
#ifndef IconoApp
  #define IconoApp "recursos\icono.ico"
#endif
#define MyAppName "Traductor de Pantalla"
#define MyAppExeName "TraductorDePantalla.exe"

[Setup]
AppId={{8C4B6F2E-3D7A-4E91-B5C2-6A1F0D9E7B43}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Sin permisos de administrador: se instala para el usuario actual.
; El asistente igual ofrece instalar "para todos los usuarios" (eso sí pide permisos).
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=salida
OutputBaseFilename=TraductorDePantalla-Setup-{#MyAppVersion}
SetupIconFile={#IconoApp}
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; Mismo nombre que NOMBRE_MUTEX en traductor.py: pide cerrar la app antes de actualizar o desinstalar.
AppMutex=TraductorDePantalla_Instancia

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "escritorio"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "iniciowindows"; Description: "Iniciar el traductor automáticamente al encender la PC"; GroupDescription: "Opciones:"; Flags: unchecked

[Files]
Source: "{#CarpetaApp}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: escritorio
Name: "{autostartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: iniciowindows

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Registro de errores que crea la app (ver traductor.py).
Type: filesandordirs; Name: "{localappdata}\TraductorDePantalla"
