; Clippy installer (Inno Setup 6). Built by packaging/windows/build.ps1 from dist\Clippy.
; Installs per user (no admin rights) into a folder Clippy can write to, because everything it downloads
; (AI engine, AI and speech models, ffmpeg) goes into its own folder. Uninstalling removes that whole folder.

#define AppVersion GetEnv("CLIPPY_VERSION")
#if AppVersion == ""
  #define AppVersion "0.1.0"
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
Name: "{autoprograms}\Clippy"; Filename: "{app}\Clippy.exe"
Name: "{autodesktop}\Clippy"; Filename: "{app}\Clippy.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Clippy.exe"; Description: "Start Clippy"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; everything Clippy downloaded or made lives in its folder: remove all of it
Type: filesandordirs; Name: "{app}"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Clips, Keep: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    Clips := ExpandConstant('{app}\output');
    if DirExists(Clips) and not UninstallSilent() then
      if MsgBox('Keep your videos and finished shorts?' + #13#10 + #13#10 +
                'Yes: they move to your Videos folder (Videos\Clippy).' + #13#10 +
                'No: they are deleted along with the AI models, tools and settings.',
                mbConfirmation, MB_YESNO) = IDYES then
      begin
        Keep := GetEnv('USERPROFILE') + '\Videos\Clippy';
        ForceDirectories(Keep);
        if not RenameFile(Clips, Keep + '\shorts-' + GetDateTimeString('yyyymmdd-hhnnss', '-', '-')) then
          MsgBox('Clippy couldn''t move your shorts. Copy them out of ' + Clips + ' now: they are deleted when you press OK.', mbError, MB_OK);
      end;
  end;
end;
