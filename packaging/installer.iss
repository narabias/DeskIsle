#ifndef BuildDir
  #define BuildDir "..\dist\DeskIsle"
#endif
#ifndef AppVersion
  #define AppVersion "2.1.0"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

[Setup]
AppId={{798E4D01-E8A9-4B88-9CB2-EFD65A6F122A}
AppName=桌屿 DeskIsle
AppVersion={#AppVersion}
AppPublisher=DeskIsle
AppPublisherURL=https://github.com/narabias/DeskIsle
AppSupportURL=https://github.com/narabias/DeskIsle/issues
AppUpdatesURL=https://github.com/narabias/DeskIsle/releases
VersionInfoVersion={#AppVersion}
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
; The "add deskisle-cli to PATH" task edits the user's PATH.
ChangesEnvironment=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: unchecked
; Offered in the wizard only: silent in-app updates never change PATH.
Name: "addtopath"; Description: "把命令行工具 deskisle-cli 加入 PATH（供 AI 助手和脚本使用）"; Check: not WizardSilent

[InstallDelete]
; 2.0 ships a different Qt runtime (Qt Quick).  Remove the previous version's
; bundle first so no stale 1.x Qt plugin or DLL is ever loaded.  User data lives
; in %LOCALAPPDATA%\DeskIsle and is not affected.
Type: filesandordirs; Name: "{app}\_internal"

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

{ ---- user PATH (task "addtopath") --------------------------------------- }

function SameFolder(A, B: String): Boolean;
begin
  Result := CompareText(RemoveBackslashUnlessRoot(Trim(A)), RemoveBackslashUnlessRoot(Trim(B))) = 0;
end;

{ PATH without Dir (and without empty entries); Found tells whether Dir was in it. }
function PathWithout(Paths, Dir: String; var Found: Boolean): String;
var
  Rest, Entry: String;
  P: Integer;
begin
  Result := '';
  Found := False;
  Rest := Paths;
  while Rest <> '' do
  begin
    P := Pos(';', Rest);
    if P > 0 then
    begin
      Entry := Copy(Rest, 1, P - 1);
      Delete(Rest, 1, P);
    end
    else
    begin
      Entry := Rest;
      Rest := '';
    end;
    if Trim(Entry) <> '' then
    begin
      if SameFolder(Entry, Dir) then
        Found := True
      else if Result = '' then
        Result := Entry
      else
        Result := Result + ';' + Entry;
    end;
  end;
end;

procedure AddToUserPath(Dir: String);
var
  Paths: String;
  Found: Boolean;
begin
  if not RegQueryStringValue(HKCU, 'Environment', 'Path', Paths) then
    Paths := '';
  PathWithout(Paths, Dir, Found);
  if Found then
    Exit;
  if (Paths <> '') and (Paths[Length(Paths)] <> ';') then
    Paths := Paths + ';';
  RegWriteExpandStringValue(HKCU, 'Environment', 'Path', Paths + Dir);
end;

procedure RemoveFromUserPath(Dir: String);
var
  Paths, Cleaned: String;
  Found: Boolean;
begin
  if not RegQueryStringValue(HKCU, 'Environment', 'Path', Paths) then
    Exit;
  Cleaned := PathWithout(Paths, Dir, Found);
  if Found then
    RegWriteExpandStringValue(HKCU, 'Environment', 'Path', Cleaned);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('addtopath') then
    AddToUserPath(ExpandConstant('{app}'));
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  StartupValue: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'DeskIsle', StartupValue) then
      if Pos(Lowercase(ExpandConstant('{app}\DeskIsle.exe')), Lowercase(StartupValue)) > 0 then
        RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'DeskIsle');
    RemoveFromUserPath(ExpandConstant('{app}'));
  end;
end;

