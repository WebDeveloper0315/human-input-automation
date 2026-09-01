; Inno Setup script for Human Input Automation.
;
; Deliberately a *per-user* install: it goes into %LOCALAPPDATA%\Programs, needs
; no administrator rights, and cannot write anywhere a normal user should not.
; An automation tool has no reason to ask for elevation, and asking would make
; every future run of the application inherit privileges it does not need.
;
; Build (on Windows, after packaging/build.py has produced dist\HumanInputAutomation):
;   iscc packaging\windows\installer.iss /DAppVersion=0.6.0

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName "Human Input Automation"
#define AppSlug "human-input-automation"
#define AppExeName "HumanInputAutomation.exe"
#define AppPublisher "Human Input Automation contributors"
#define AppUrl "https://github.com/human-input-automation/human-input-automation"

[Setup]
AppId={{8F2A6E5C-58B4-4E4E-9C2B-7E1B0A9D4C31}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
DefaultDirName={localappdata}\Programs\{#AppSlug}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Per-user: no UAC prompt, no administrator rights.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\..\dist
OutputBaseFilename=HumanInputAutomation-{#AppVersion}-windows-x64-setup
SetupIconFile=..\..\src\human_input_automation\resources\icons\app.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\..\dist\HumanInputAutomation\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Start {#AppName}"; Flags: nowait postinstall skipifsilent

; Uninstall removes only what the installer put on disk.
;
; Profiles and logs live in %APPDATA%\human-input-automation and are NOT
; removed: they are the user's work, and silently deleting them because an
; application was uninstalled would be indefensible. The uninstaller says so,
; and docs/RELEASE-CHECKLIST.md documents where to delete them by hand.
[Messages]
ConfirmUninstall=Remove %1?%n%nYour saved profiles and logs in %APPDATA%\human-input-automation will be kept.
