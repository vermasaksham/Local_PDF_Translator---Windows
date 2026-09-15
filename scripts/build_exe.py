"""Build the Windows application with PyInstaller.

    python scripts\\build_exe.py

Checks its inputs first, because the failure modes otherwise appear much later
— an app that starts and then says every model is missing, or one that shows
empty boxes instead of Hindi.

The result is dist\\LocalPDFTranslator\\LocalPDFTranslator.exe. To wrap that in
an installer, run scripts\\build_installer.py afterwards.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from local_pdf_translator import __version__
from local_pdf_translator.core.model_catalog import BUNDLED, REQUIRED_FILES

SPEC = REPO_ROOT / "packaging" / "LocalPDFTranslator.spec"
DIST = REPO_ROOT / "dist"
BUILD = REPO_ROOT / "build" / "pyinstaller"


def log(message: str) -> None:
    print(f"==> {message}", flush=True)


def warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def check_models() -> None:
    missing = [
        model.directory_name
        for model in BUNDLED
        if not all(
            (REPO_ROOT / "models" / model.directory_name / name).is_file()
            for name in REQUIRED_FILES
        )
    ]
    if missing:
        die(
            "these models are not converted yet: "
            + ", ".join(missing)
            + "\n       Run: python scripts\\fetch_models.py"
        )
    log(f"All {len(BUNDLED)} models present")


def check_optional_payloads() -> None:
    if (REPO_ROOT / "tesseract" / "tesseract.exe").is_file():
        log("Tesseract will be bundled")
    else:
        warn(
            "no tesseract\\tesseract.exe — scanned PDFs will not be translatable "
            "in this build. Run: python scripts\\bundle_tesseract.py"
        )

    try:
        from local_pdf_translator.pdf.textpainter import shaping_status

        shapes, reason = shaping_status()
        if shapes:
            log(f"Devanagari shaping works — {reason}")
        else:
            warn(f"Hindi output would not be trustworthy: {reason}")
    except Exception as failure:
        warn(f"could not check complex-script shaping: {failure}")


def write_version_info() -> None:
    """Write the VERSIONINFO resource embedded into the .exe.

    Windows shows this on the file's Properties page and SmartScreen mentions
    it, so it is worth filling in properly.
    """
    parts = (__version__.split(".") + ["0", "0", "0"])[:4]
    numbers = ", ".join(part if part.isdigit() else "0" for part in parts)
    target = REPO_ROOT / "packaging" / "version_info.txt"
    target.write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({numbers}),
    prodvers=({numbers}),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('FileDescription', 'Local PDF Translator'),
        StringStruct('FileVersion', '{__version__}'),
        StringStruct('InternalName', 'LocalPDFTranslator'),
        StringStruct('OriginalFilename', 'LocalPDFTranslator.exe'),
        StringStruct('ProductName', 'Local PDF Translator'),
        StringStruct('ProductVersion', '{__version__}'),
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-checks", action="store_true", help="build even if inputs are missing"
    )
    parser.add_argument(
        "--clean", action="store_true", help="delete previous build output first"
    )
    arguments = parser.parse_args()

    if not arguments.skip_checks:
        check_models()
        check_optional_payloads()

    if arguments.clean:
        log("Removing previous build output")
        shutil.rmtree(DIST / "LocalPDFTranslator", ignore_errors=True)
        shutil.rmtree(BUILD, ignore_errors=True)

    write_version_info()

    log(f"Building Local PDF Translator {__version__}")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--distpath",
            str(DIST),
            "--workpath",
            str(BUILD),
            str(SPEC),
        ],
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        die("PyInstaller failed")

    executable = DIST / "LocalPDFTranslator" / "LocalPDFTranslator.exe"
    if not executable.exists() and sys.platform == "win32":
        die("the build finished but produced no executable")

    total = sum(
        item.stat().st_size
        for item in (DIST / "LocalPDFTranslator").rglob("*")
        if item.is_file()
    )
    log(f"Built {DIST / 'LocalPDFTranslator'} ({total / 1_000_000:.0f} MB)")
    print("\nNext: python scripts\\build_installer.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
