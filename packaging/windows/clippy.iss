; Clippy installer (Inno Setup 6). Built by packaging/windows/build.ps1 from dist\Clippy.
; Installs per user (no admin rights) into a folder Clippy can write to, because everything it downloads
; (AI engine, AI and speech models, ffmpeg) goes into its own folder. Uninstalling removes that whole folder.

#define AppVersion GetEnv("CLIPPY_VERSION")
#if AppVersion == ""
  #define AppVersion "0.3.1"
#endif

[Setup]
AppId={{B8C7E8A2-6C0E-4D7B-9E39-3F5C2E9A1C11}
AppName=Clippy
AppVersion={#AppVersion}
AppVerName=Clippy {#AppVersion}
AppPublisher=Storm Amdam
AppPublisherURL=https://github.com/StormAmdam/clippy
AppSupportURL=https://github.com/StormAmdam/clippy/issues
DefaultDirName={localappdata}\Programs\Clippy
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
DisableDirPage=auto
OutputDir=..\..\dist
OutputBaseFilename=Clippy-Setup-{#AppVersion}-win64
SetupIconFile=clippy.ico
UninstallDisplayIcon={app}\Clippy.exe
UninstallDisplayName=Clippy
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
LicenseFile=..\..\LICENSE
CloseApplications=force
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Put a Clippy shortcut on the desktop"

[Files]
Source: "..\..\dist\Clippy\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
; the app id lets Clippy's notifications show as "Clippy" (clippy/notify.py)
Name: "{autoprograms}\Clippy"; Filename: "{app}\Clippy.exe"; AppUserModelID: "StormAmdam.Clippy"
Name: "{autodesktop}\Clippy"; Filename: "{app}\Clippy.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Clippy.exe"; Description: "Start Clippy"; Flags: nowait postinstall skipifsilent
; an update started from inside Clippy (clippy/updates.py) runs silently: open Clippy again afterwards
Filename: "{app}\Clippy.exe"; Flags: nowait; Check: RestartClippy

[UninstallDelete]
; everything Clippy downloaded or made lives in its folder: remove all of it
Type: filesandordirs; Name: "{app}"

[Code]
const
  RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';
  ApprovedKey = 'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run';

{ "Start at login" (clippy/autostart.py) adds a Run entry for this folder's Clippy.exe: take it away again }
procedure RemoveStartAtLogin();
var
  Cmd: String;
begin
  if RegQueryStringValue(HKEY_CURRENT_USER, RunKey, 'Clippy', Cmd) and
     (Pos(Lowercase(ExpandConstant('{app}\Clippy.exe')), Lowercase(Cmd)) > 0) then
  begin
    RegDeleteValue(HKEY_CURRENT_USER, RunKey, 'Clippy');
    RegDeleteValue(HKEY_CURRENT_USER, ApprovedKey, 'Clippy');
  end;
end;

{ End a running Clippy from this folder (also one running in the background for "Start at login") and its app
  window, which keeps files open in data\window. The AI engine, ffmpeg and the rest end with Clippy (clippy/quiet.py). }
procedure StopClippy();
var
  App, Script: String;
  ResultCode: Integer;
begin
  App := ExpandConstant('{app}');
  StringChangeEx(App, '''', '''''', True);       { a ' in the path, doubled for PowerShell }
  Script := '$d = (''' + App + ''').ToLower(); $w = ''--user-data-dir='' + $d + ''\data\window''; ' +
    'Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.Name -notlike ''unins*'' -and $_.Name -notlike ''Clippy-Setup*'' -and ' +
    '(($_.ExecutablePath -and $_.ExecutablePath.ToLower().StartsWith($d + ''\'')) -or ' +
    '($_.CommandLine -and $_.CommandLine.ToLower().Contains($w))) } | ' +
    'ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }';
  Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
       '-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "' + Script + '"',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

{ /CLIPPYRESTART=1: Clippy started this update itself, so open it again when done }
function RestartClippy: Boolean;
begin
  Result := ExpandConstant('{param:CLIPPYRESTART|0}') = '1';
end;

{ updating: close the running Clippy first, so every file can be replaced }
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  if FileExists(ExpandConstant('{app}\Clippy.exe')) then
    StopClippy();
  Result := '';
end;

{ Windows' own Videos folder: it may have been moved into OneDrive or onto another drive }
function VideosFolder(): String;
begin
  Result := GetShellFolderByCSIDL($000E, True);    { CSIDL_MYVIDEO }
  if Result = '' then
    Result := GetEnv('USERPROFILE') + '\Videos';
end;

{ move a folder, also onto another drive (where RenameFile can't): copy it, the uninstaller deletes the original }
function MoveFolder(Src, Dst: String): Boolean;
var
  S, D: String;
  ResultCode: Integer;
begin
  Result := RenameFile(Src, Dst);
  if Result then
    exit;
  S := Src;
  D := Dst;
  StringChangeEx(S, '''', '''''', True);
  StringChangeEx(D, '''', '''''', True);
  Result := Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
                 '-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$ErrorActionPreference = ''Stop''; ' +
                 'Copy-Item -LiteralPath ''' + S + ''' -Destination ''' + D + ''' -Recurse"',
                 '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0) and DirExists(Dst);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Clips, Keep: String;
  KeepThem: Boolean;
begin
  if CurUninstallStep = usUninstall then
  begin
    StopClippy();
    RemoveStartAtLogin();
    Clips := ExpandConstant('{app}\output');
    if DirExists(Clips) then
    begin
      { silent uninstalls delete them unless /KEEPSHORTS=1 }
      if UninstallSilent() then
        KeepThem := ExpandConstant('{param:KEEPSHORTS|0}') = '1'
      else
        KeepThem := MsgBox('Keep your videos and finished shorts?' + #13#10 + #13#10 +
                           'Yes: they move to your Videos folder (Videos\Clippy).' + #13#10 +
                           'No: they are deleted along with the AI models, tools and settings.',
                           mbConfirmation, MB_YESNO) = IDYES;
      if KeepThem then
      begin
        Keep := VideosFolder() + '\Clippy';
        ForceDirectories(Keep);
        if not MoveFolder(Clips, Keep + '\shorts-' + GetDateTimeString('yyyymmdd-hhnnss', '-', '-')) and
           not UninstallSilent() then
          MsgBox('Clippy couldn''t move your shorts. Copy them out of ' + Clips + ' now: they are deleted when you press OK.', mbError, MB_OK);
      end;
    end;
  end;
end;
