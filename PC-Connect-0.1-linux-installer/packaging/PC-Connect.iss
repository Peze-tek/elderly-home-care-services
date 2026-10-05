#define MyAppName "PC Connect"
#define MyAppVersion "3.0.0"
#define MyAppPublisher "PC Connect"
#define MyAppExeName "PC Connect.exe"

[Setup]
AppId={{9C4E8F0D-3F8A-4F4A-A1E0-PCCONNECT300}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\PC Connect
DefaultGroupName=PC Connect
OutputBaseFilename=PC-Connect-Setup
ArchitecturesInstallIn64BitMode=x64
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "..\dist\PC Connect.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\PC Connect"; Filename: "{app}\PC Connect.exe"
Name: "{autodesktop}\PC Connect"; Filename: "{app}\PC Connect.exe"

[Run]
Filename: "{app}\PC Connect.exe"; Description: "Launch PC Connect"; Flags: nowait postinstall skipifsilent
