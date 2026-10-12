#ifndef AppVersion
#define AppVersion "1.0.1"
#endif
[Setup]
AppId={{846D6C5E-EA9A-4317-A83B-CA02F23B5107}
AppName=Flow Studio
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Flow Studio
DefaultGroupName=Flow Studio
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=FlowStudio-{#AppVersion}-Windows-x64-Setup
SetupIconFile=..\assets\flowstudio.ico
UninstallDisplayIcon={app}\assets\flowstudio.ico
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
AppMutex=FlowStudio.Desktop.Running
[Files]
Source: "..\build\FlowStudio-Windows\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.pyc,__pycache__\*"
[Icons]
Name: "{group}\Flow Studio"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\flowstudio.ico"
Name: "{autodesktop}\Flow Studio"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\flowstudio.ico"
[Run]
Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; Description: "Launch Flow Studio"; Flags: nowait postinstall skipifsilent
