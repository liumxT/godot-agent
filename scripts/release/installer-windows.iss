; Godot AI Agent Platform — Windows 安装器（Inno Setup）
;
; 构建（仓库根目录）：
;   .tools/innosetup/ISCC.exe scripts/release/installer-windows.iss
;
; 产物：release/installers/windows/GodotAIAgent-Setup-1.0.0.exe
;
; 设计约束（E12）：
;   - 安装目录与数据目录分离；数据目录由后端首启创建于 %LOCALAPPDATA%\GodotAIAgent
;   - 默认安装到用户目录，无需管理员权限
;   - 卸载仅移除安装目录，保留用户数据、项目与日志

#define AppName "Godot AI Agent Platform"
#define AppVersion "1.0.0"
#define AppPublisher "Godot AI Agent"
#define BackendExe "godot-ai-backend.exe"

; 相对路径基于本脚本所在目录（scripts/release）
#define RepoRoot "..\.."
#define BackendDist RepoRoot + "\artifacts\dist-e12"
#define PluginSrc RepoRoot + "\apps\godot-plugin\addons\godot_ai_agent"
#define DocsSrc RepoRoot + "\docs"

[Setup]
AppId={{7F3A9C2E-5B1D-4E8A-9C6F-2D8B1A4E7C50}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}.0
DefaultDirName={localappdata}\Programs\GodotAIAgent
DefaultGroupName=Godot AI Agent
DisableProgramGroupPage=yes
OutputDir={#RepoRoot}\release\installers\windows
OutputBaseFilename=GodotAIAgent-Setup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
PrivilegesRequired=lowest
WizardStyle=modern
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\backend\{#BackendExe}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableWelcomePage=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
; 后端可执行文件（含 E12 产品化模块）
Source: "{#BackendDist}\{#BackendExe}"; DestDir: "{app}\backend"; Flags: ignoreversion
; 启动脚本：自动设置数据目录与数据库连接，开箱即用
Source: "packaging\Start-Backend.cmd"; DestDir: "{app}"; Flags: ignoreversion
; Godot 插件（addons/godot_ai_agent）
Source: "{#PluginSrc}\*"; DestDir: "{app}\godot_plugin\addons\godot_ai_agent"; Flags: ignoreversion recursesubdirs createallsubdirs
; 文档
Source: "{#DocsSrc}\05-product\user-guide.md"; DestDir: "{app}\documentation"; Flags: ignoreversion
Source: "{#DocsSrc}\05-product\usage-manual.md"; DestDir: "{app}\documentation"; Flags: ignoreversion
Source: "{#DocsSrc}\05-product\developer-guide.md"; DestDir: "{app}\documentation"; Flags: ignoreversion
Source: "{#DocsSrc}\04-operations\runbooks.md"; DestDir: "{app}\documentation"; Flags: ignoreversion
Source: "{#DocsSrc}\05-product\release-notes\v1.0.0.md"; DestDir: "{app}\documentation"; Flags: ignoreversion

[Icons]
Name: "{group}\Godot AI Agent Backend"; Filename: "{app}\Start-Backend.cmd"; WorkingDir: "{app}"
Name: "{group}\User Guide"; Filename: "{app}\documentation\user-guide.md"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Godot AI Agent Backend"; Filename: "{app}\Start-Backend.cmd"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\Start-Backend.cmd"; Description: "Launch backend now"; Flags: nowait postinstall skipifsilent unchecked

[UninstallDelete]
; 仅清理安装目录内的缓存；用户数据目录（%LOCALAPPDATA%\GodotAIAgent）一律保留
Type: filesandordirs; Name: "{app}\backend\__pycache__"
