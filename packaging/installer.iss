; Inno Setup script for Local PDF Translator.
;
; Produces a single all-in-one installer: the app, the translation models and
; Tesseract are all inside it, so the installed program works offline from its
; very first launch and never downloads anything.
;
; Built by scripts\build_installer.py, which passes AppVersion in.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

#define AppName "Local PDF Translator"
#define AppPublisher "Local PDF Translator"
#define AppExeName "LocalPDFTranslator.exe"
#define SourceDir "..\dist\LocalPDFTranslator"

[Setup]
AppId={{8B3C1E64-2A77-4B2E-9E3F-7B1D0C5A9E21}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist\installer
OutputBaseFilename=LocalPDFTranslator-{#AppVersion}-Setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExeName}
WizardStyle=modern

; The payload is mostly already-compressed model weights. LZMA2/max still wins
; a little on the Qt and Python DLLs, and costs only build time.
Compression=lzma2/max
SolidCompression=yes

; Windows 10 (build 10240) and above, 64-bit only — which is what the
; CTranslate2 and PySide6 wheels require in any case.
MinVersion=10.0.10240
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; Per-machine when the user can, per-user when they cannot: this avoids
; demanding administrator rights from someone who does not have them.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"
Name: "associatepdf"; Description: "Add ""Translate with {#AppName}"" to the right-click menu for PDF files"; GroupDescription: "Integration:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Registry]
; A right-click verb rather than a file association: this app translates PDFs,
; it is not a PDF reader, so it has no business taking the default over.
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\TranslateWithLPT"; \
    ValueType: string; ValueName: ""; ValueData: "Translate with {#AppName}"; \
    Flags: uninsdeletekey; Tasks: associatepdf
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\TranslateWithLPT"; \
    ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExeName},0"; \
    Tasks: associatepdf
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\TranslateWithLPT\command"; \
    ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" ""%1"""; \
    Flags: uninsdeletekey; Tasks: associatepdf

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Start {#AppName}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Scratch copies of translated PDFs, written before the user saves them
; anywhere permanent. Their own saved files are never touched.
Type: filesandordirs; Name: "{localappdata}\LocalPDFTranslator\output"
