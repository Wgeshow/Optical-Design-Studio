; Build with Inno Setup 7.1 or later. The payload is an already tested
; PyInstaller one-folder application; the installer never downloads packages.
#ifndef PayloadDir
  #define PayloadDir SourcePath + "dist\Optical Design Studio"
#endif
#ifndef OutputDir
  #define OutputDir SourcePath + "release"
#endif
#ifndef Version
  #include "version.iss"
#endif
#define AppName "Optical Design Studio"
#define AppExe "Optical Design Studio.exe"
#define IconFile SourcePath + "assets\S4_Studio.ico"
#define LogoFile SourcePath + "assets\S4_Studio_icon.png"

#if !FileExists(PayloadDir + "\" + AppExe)
  #error The application payload is missing Optical Design Studio.exe.
#endif
#if !FileExists(PayloadDir + "\OpticalDesignBackend.exe")
  #error The application payload is missing OpticalDesignBackend.exe.
#endif
#if !FileExists(IconFile) || !FileExists(LogoFile)
  #error Run prepare_installer_assets.py to copy the existing application icon.
#endif

[Setup]
; Keep this ID stable so upgrades use the existing uninstall record.
AppId={{3103D40B-0D27-4DA2-8C2A-D87331C81AD2}
AppName={#AppName}
AppVersion={#Version}
AppVerName={#AppName} {#Version}
AppPublisher={#AppName}
VersionInfoDescription={#AppName} Installer
VersionInfoProductName={#AppName}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
SetupArchitecture=x64
ArchitecturesAllowed=x64compatible and not arm64
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
DisableWelcomePage=no
DisableDirPage=no
DisableProgramGroupPage=yes
AlwaysShowDirOnReadyPage=yes
UsePreviousAppDir=yes
AllowRootDirectory=no
WizardStyle=modern dynamic
WizardSizePercent=110
SetupIconFile={#IconFile}
WizardSmallImageFile={#LogoFile}
WizardSmallImageFileDynamicDark={#LogoFile}
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
AppReadmeFile={app}\INSTALLATION.md
OutputDir={#OutputDir}
OutputBaseFilename=OpticalDesignStudio-Setup-{#Version}-Windows-x64
Compression=lzma2/normal
SolidCompression=yes
DiskSpanning=no
CloseApplications=yes
CloseApplicationsFilter=*.exe,*.dll,*.pyd
RestartApplications=no
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
WelcomeLabel1=Install Optical Design Studio
WelcomeLabel2=This installs Optical Design Studio, its simulation engine, and machine-learning tools.%n%nNo separate Python or Conda installation or internet connection is required.%n%nYour saved work remains in your Windows user profile. Click Next to choose the installation folder.
SelectDirDesc=Where should Optical Design Studio be installed?
SelectDirLabel3=Choose a folder for the application and all of its runtime files.%n%nSaved work is kept separately in your Windows user profile, including after updates or uninstalling.

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourcePath}INSTALLATION.md"; DestDir: "{app}"; Flags: ignoreversion
; Register the receipt as an installed file so ordinary uninstall removes it.
Source: "{#SourcePath}installation-template.json"; DestDir: "{app}"; DestName: "installation.json"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; IconFilename: "{app}\S4_Studio.ico"; AppUserModelID: "OpticalDesignStudio.Desktop"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; IconFilename: "{app}\S4_Studio.ico"; AppUserModelID: "OpticalDesignStudio.Desktop"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch Optical Design Studio"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

; Deliberately no [InstallDelete] or [UninstallDelete] section: only tracked
; application files are removed. User Data is created by the application in
; LocalAppData, outside the installer-managed payload, and is never deleted.

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ReceiptPath, Receipt: String;
begin
  if CurStep = ssPostInstall then
  begin
    ReceiptPath := ExpandConstant('{app}\installation.json');
    Receipt := '{"version":"{#Version}","updated_at":"' +
      GetDateTimeString('yyyy-mm-dd"T"hh:nn:ss', '-', ':') + '"}' + #13#10;
    if not SaveStringToFile(ReceiptPath, Receipt, False) then
      RaiseException('Unable to record the installed application version.');
  end;
end;
