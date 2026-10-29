#define MyAppName "모모 비서 (친구용)"
#define MyAppVersion "1.3.0"
#define MyAppExeName "MomoFriends.exe"

[Setup]
AppId=MomoFriends
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Momo
DefaultDirName={localappdata}\Programs\MomoFriends
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\friends-installer
OutputBaseFilename=MomoFriendsSetup-{#MyAppVersion}
SetupIconFile=momo.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
CloseApplications=yes

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕화면 바로가기 만들기"; GroupDescription: "추가 바로가기:"; Flags: checkedonce

[Files]
Source: "dist\MomoFriends\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "사용자 가이드.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autoprograms}\모모 사용자 가이드"; Filename: "{app}\사용자 가이드.md"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "모모 실행"; Flags: nowait postinstall skipifsilent
