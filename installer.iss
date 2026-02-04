; ArknightsPassMaker Installer

#define MyAppName "ArknightsPassMaker"
#define MyAppNameCN "明日方舟通行证素材制作器"
#define MyAppVersion "1.5.7"
#define MyAppPublisher "Rafael-ban"
#define MyAppURL "https://github.com/rhodesepass/neo-assetmaker"
#define MyAppExeName "ArknightsPassMaker.exe"
#define MyAppIcon "resources\icons\favicon.ico"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppNameCN}
AppVersion={#MyAppVersion}
AppVerName={#MyAppNameCN} v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\{#MyAppName}
DefaultGroupName={#MyAppNameCN}
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename={#MyAppName}_v{#MyAppVersion}_Setup
SetupIconFile={#MyAppIcon}
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern
WizardImageFile=resources\installer\wizard.bmp
WizardSmallImageFile=resources\installer\wizard_small.bmp
LicenseFile=resources\installer\LICENSE.txt
ShowLanguageDialog=no
Uninstallable=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppNameCN}

[Languages]
Name: "chinese"; MessagesFile: "resources\installer\ChineseSimplified.isl"

[Messages]
WelcomeLabel1=欢迎使用 明日方舟通行证素材制作器
WelcomeLabel2=本程序将安装 [name/ver] 到您的计算机。%n%n点击"下一步"继续安装。
FinishedHeadingLabel=安装完成
FinishedLabel=明日方舟通行证素材制作器 已成功安装到您的计算机。%n%n感谢您的使用！

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "ArknightsPassMaker\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppNameCN}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppNameCN}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppNameCN}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppNameCN, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
