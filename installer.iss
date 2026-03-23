; ArknightsPassMaker Installer

#define MyAppName "ArknightsPassMaker"
#define MyAppNameCN "明日方舟通行证素材工具箱"
#ifndef MyAppVersion
  #define MyAppVersion "2.1.0"
#endif
#define MyAppPublisher "Rafael-ban"
#define MyAppURL "https://github.com/rhodesepass/neo-assetmaker"
#define MyAppExeName "ArknightsPassMaker.exe"
#define MyAppIcon "resources\icons\favicon.ico"

[Setup]
AppId={A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
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
AppMutex=ArknightsPassMakerMutex
MinVersion=10.0
CloseApplications=yes
CloseApplicationsFilter=*.exe
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
WelcomeLabel1=欢迎使用 明日方舟通行证素材工具箱
WelcomeLabel2=本程序将安装 [name/ver] 到您的计算机。%n%n点击"下一步"继续安装。
FinishedHeadingLabel=安装完成
FinishedLabel=明日方舟通行证素材工具箱 已成功安装到您的计算机。%n%n感谢您的使用！

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; === 兜底清理（主要清理由 [Code] 段的白名单反向清理完成）===
; 执行顺序（见 issrc Setup.MainForm.pas:220-225, Setup.Install.pas:2812-2813）：
;   1. CurStepChanged(ssInstall) — [Code] 段 Pascal 脚本先执行
;   2. ProcessInstallDeleteEntries — 本段条目后执行
;   3. CopyFiles — [Files] 最后安装
; 用户数据目录 (config/, logs/, .recovery/) 由 [Code] 段白名单保护
Type: filesandordirs; Name: "{app}\lib"
Type: filesandordirs; Name: "{app}\resources"
Type: filesandordirs; Name: "{app}\simulator"
Type: filesandordirs; Name: "{app}\epass_flasher"
Type: filesandordirs; Name: "{app}\class_icons"

[UninstallDelete]
; === 卸载时清理运行时生成的文件 ===
; 保留 config/ 目录（方便重装后恢复设置），仅清理日志和恢复数据
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\.recovery"
Type: files; Name: "{app}\stdout.log"
Type: files; Name: "{app}\stderr.log"
Type: files; Name: "{app}\crash.log"
Type: dirifempty; Name: "{app}"

[Files]
Source: "ArknightsPassMaker\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppNameCN}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppNameCN}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppNameCN}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppNameCN, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
// ===================================================================
// 升级时动态清理旧版本文件（白名单反向清理）
// 策略：遍历安装目录，仅保留白名单中的用户数据目录，其余全部删除
// 在 CurStepChanged(ssInstall) 中执行，先于 [InstallDelete] 和 [Files]
// ===================================================================

function IsProtectedItem(const RelativePath: string): Boolean;
var
  LowerPath: string;
begin
  LowerPath := Lowercase(RelativePath);
  Result :=
    // 用户配置目录
    (LowerPath = 'config') or (Pos('config\', LowerPath) = 1) or
    // 日志目录
    (LowerPath = 'logs') or (Pos('logs\', LowerPath) = 1) or
    // 崩溃恢复目录
    (LowerPath = '.recovery') or (Pos('.recovery\', LowerPath) = 1) or
    // Inno Setup 卸载文件
    (LowerPath = 'unins000.exe') or (LowerPath = 'unins000.dat');
end;

procedure CleanAppDirectory(const Dir, BaseDir: string);
var
  FindRec: TFindRec;
  FullPath, RelPath: string;
begin
  if not DirExists(Dir) then
    Exit;
  if FindFirst(Dir + '\*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Name = '.') or (FindRec.Name = '..') then
          Continue;
        FullPath := Dir + '\' + FindRec.Name;
        RelPath := Copy(FullPath, Length(BaseDir) + 2, MaxInt);
        if IsProtectedItem(RelPath) then
        begin
          Log('Protected (skipped): ' + RelPath);
          Continue;
        end;
        if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
        begin
          if DelTree(FullPath, True, True, True) then
            Log('Deleted dir: ' + RelPath)
          else
            Log('Failed to delete dir: ' + RelPath);
        end
        else
        begin
          if DeleteFile(FullPath) then
            Log('Deleted file: ' + RelPath)
          else
            Log('Failed to delete file: ' + RelPath);
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  AppDir: string;
begin
  if CurStep = ssInstall then
  begin
    AppDir := ExpandConstant('{app}');
    if DirExists(AppDir) then
    begin
      Log('=== Upgrade cleanup: scanning ' + AppDir + ' ===');
      CleanAppDirectory(AppDir, AppDir);
      Log('=== Upgrade cleanup completed ===');
    end
    else
      Log('App directory does not exist, skipping cleanup (fresh install)');
  end;
end;
