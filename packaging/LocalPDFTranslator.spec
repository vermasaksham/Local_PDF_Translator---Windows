# PyInstaller build definition.
#
# A one-*folder* build, deliberately. One-file would have to unpack ~300 MB of
# model weights into a temporary directory on every launch, which turns a
# two-second start into a thirty-second one.
#
# Invoked by scripts/build_exe.py, which checks the inputs are present first.

import sys
from pathlib import Path

REPO_ROOT = Path(SPECPATH).parent

datas = [
    (str(REPO_ROOT / "models"), "models"),
    (str(REPO_ROOT / "assets"), "assets"),
]

# Optional payloads: present when the matching bundling script has been run.
for optional in ("tesseract", "fonts"):
    directory = REPO_ROOT / optional
    if directory.is_dir():
        datas.append((str(directory), optional))

hidden_imports = [
    # Both are loaded through a lazy import inside the engine, so PyInstaller's
    # static analysis never sees them.
    "ctranslate2",
    "sentencepiece",
]

# Qt ships a great deal this app never touches. Dropping it saves roughly
# 120 MB in the finished installer.
excludes = [
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.QtBluetooth",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtHelp",
    "PySide6.QtLocation",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtNetworkAuth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtTextToSpeech",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets",
    # Pulled in transitively by some wheels but never used here.
    "tkinter",
    "matplotlib",
    "numpy.f2py",
    "pytest",
]

analysis = Analysis(
    [str(REPO_ROOT / "local_pdf_translator" / "__main__.py")],
    pathex=[str(REPO_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(analysis.pure, analysis.zipped_data)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="LocalPDFTranslator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # A GUI app: no console window behind the main window.
    console=False,
    disable_windowed_traceback=False,
    icon=str(REPO_ROOT / "assets" / "icon.ico"),
    version=str(REPO_ROOT / "packaging" / "version_info.txt"),
)

collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="LocalPDFTranslator",
)
