"""Wrap the built application in a Windows installer using Inno Setup.

    python scripts\\build_installer.py

Requires Inno Setup 6 (https://jrsoftware.org/isdl.php). Run
scripts\\build_exe.py first.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from local_pdf_translator import __version__

SCRIPT = REPO_ROOT / "packaging" / "installer.iss"
BUILT_APP = REPO_ROOT / "dist" / "LocalPDFTranslator"
OUTPUT_DIR = REPO_ROOT / "dist" / "installer"

CANDIDATES = [
    Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
    Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
]


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def find_compiler() -> str:
    override = os.environ.get("ISCC")
    if override:
        return override
    found = shutil.which("iscc") or shutil.which("ISCC")
    if found:
        return found
    for candidate in CANDIDATES:
        if candidate.is_file():
            return str(candidate)
    die(
        "Inno Setup's compiler (ISCC.exe) was not found. Install Inno Setup 6 from "
        "https://jrsoftware.org/isdl.php, or set the ISCC environment variable."
    )


def main() -> int:
    if not (BUILT_APP / "LocalPDFTranslator.exe").is_file():
        die(f"no built application at {BUILT_APP}. Run: python scripts\\build_exe.py")

    compiler = find_compiler()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"==> Building the installer for version {__version__}", flush=True)
    result = subprocess.run(
        [compiler, f"/DAppVersion={__version__}", str(SCRIPT)],
        cwd=REPO_ROOT / "packaging",
    )
    if result.returncode != 0:
        die("Inno Setup failed")

    installers = sorted(OUTPUT_DIR.glob("*Setup.exe"))
    if not installers:
        die("Inno Setup reported success but produced no installer")

    installer = installers[-1]
    print(f"\n==> {installer} ({installer.stat().st_size / 1_000_000:.0f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
