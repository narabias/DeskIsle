#ifndef BuildDir
  #define BuildDir "..\dist\DeskIsle"
#endif
#ifndef AppVersion
  #define AppVersion "1.2.1"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

[Setup]
AppId={{798E4D01-E8A9-4B88-9CB2-EFD65A6F122A}
AppName=桌屿 DeskIsle
AppVersion={#AppVersion}
AppPublisher=DeskIsle
DefaultDirName={localappdata}\Programs\DeskIsle
DefaultGroupName=桌屿 DeskIsle
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=DeskIsle-Setup-{#AppVersion}-x64
SetupIconFile=DeskIsle.ico
UninstallDisplayIcon={app}\DeskIsle.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
CloseApplications=yes
RestartApplications=no
; Updates reuse the previous install folder and choices; user data lives in
; %LOCALAPPDATA%\DeskIsle and is never touched by the installer.
UsePreviousAppDir=yes
UsePreviousTasks=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: unchecked

[Files]
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\桌屿 DeskIsle"; Filename: "{app}\DeskIsle.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\桌屿 DeskIsle"; Filename: "{app}\DeskIsle.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "DeskIsle"; ValueData: """{app}\DeskIsle.exe"""; Check: ExistingStartup

[Run]
Filename: "{app}\DeskIsle.exe"; Description: "启动桌屿 DeskIsle"; Flags: nowait postinstall skipifsilent
; In-app update (silent install started by DeskIsle): reopen the app afterwards.
Filename: "{app}\DeskIsle.exe"; WorkingDir: "{app}"; Flags: nowait; Check: ShouldRelaunchAfterUpdate

[Code]
function ShouldRelaunchAfterUpdate: Boolean;
begin
  Result := WizardSilent and (ExpandConstant('{param:DESKISLERELAUNCH|0}') = '1');
end;

function ExistingStartup: Boolean;
begin
  Result := (ExpandConstant('{param:SKIPSTARTUPMIGRATION|0}') <> '1') and
    RegValueExists(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'DeskIsle');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  StartupValue: String;
begin
  if CurUninstallStep = usUninstall then
    if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'DeskIsle', StartupValue) then
      if Pos(Lowercase(ExpandConstant('{app}\DeskIsle.exe')), Lowercase(StartupValue)) > 0 then
        RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'DeskIsle');
end;
