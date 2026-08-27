#define MyAppName "VK Outreach Manager"
#define MyAppVersion "0.4.4"
#define MyAppPublisher "VK Outreach Manager"
#define MyAppExeName "VK Outreach Manager.exe"

[Setup]
AppId={{E6D89DBB-E65D-4A70-99B9-E370205B93E7}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\VK Outreach Manager
DefaultGroupName={#MyAppName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=release
OutputBaseFilename=VK_Outreach_Manager_Setup_0.4.4
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupIconFile=app-icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
PrivilegesRequired=lowest
CloseApplications=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Ярлыки:"; Flags: checkedonce
Name: "startup"; Description: "Запускать вместе с Windows"; GroupDescription: "Дополнительно:"; Flags: unchecked

[Files]
Source: "dist\VK Outreach Manager\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startup

[Run]
Filename: "{app}\MicrosoftEdgeWebView2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "Проверяю Microsoft Edge WebView2 Runtime..."; Flags: runhidden waituntilterminated
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить {#MyAppName}"; Flags: nowait postinstall skipifsilent
