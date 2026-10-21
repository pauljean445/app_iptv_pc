; Script Inno Setup : cree l'installeur Windows d'IPTV Player (dist\IPTVPlayer-Setup-<version>.exe).
; Ne pas compiler directement : lancer build_installer.bat, qui prepare d'abord dist\IPTVPlayer
; (application compilee + VLC embarque dans le sous-dossier vlc).

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppName "IPTV Player"
#define AppExe "IPTVPlayer.exe"

[Setup]
; AppId identifie l'application pour les mises a jour et la desinstallation : ne jamais le changer.
AppId={{0D036486-ADFC-4D2E-8848-E24E5126B083}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
; Installation pour l'utilisateur courant par defaut (sans droits admin), ou pour tous au choix.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=IPTVPlayer-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; Mise a jour : on retire l'ancienne version pour ne pas garder de fichiers perimes.
; Les reglages et le cache (dans %APPDATA%) ne sont pas touches.
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\vlc"

[Files]
Source: "..\dist\IPTVPlayer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
; Mise a jour lancee depuis l'appli (installeur silencieux avec /relaunch=1) : on relance l'appli a la fin.
Filename: "{app}\{#AppExe}"; Flags: nowait runasoriginaluser; Check: RelaunchAfterUpdate

[Code]
function RelaunchAfterUpdate: Boolean;
begin
  Result := ExpandConstant('{param:relaunch|0}') = '1';
end;
