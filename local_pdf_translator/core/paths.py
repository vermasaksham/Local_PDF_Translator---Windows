"""Where the app's bundled resources live.

The same code has to work in three situations: run from a source checkout, run
from a PyInstaller one-folder build, and run from the installed program in
C:\\Program Files. Resolving that in one place keeps every other module free of
`sys.frozen` checks.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

#: Environment variables that override the bundled locations, so a developer
#: can point a source checkout at an already-installed set of models.
MODELS_DIR_ENV = "LPT_MODELS_DIR"
TESSERACT_EXE_ENV = "LPT_TESSERACT_EXE"


def is_frozen() -> bool:
    """True when running from a PyInstaller build rather than source."""
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """The directory that bundled resources sit beside."""
    if is_frozen():
        # One-folder builds unpack next to the executable; one-file builds
        # extract to _MEIPASS. Support both so either PyInstaller mode works.
        bundled = getattr(sys, "_MEIPASS", None)
        return Path(bundled) if bundled else Path(sys.executable).parent
    return Path(__file__).resolve().parents[2]


def models_directory() -> Path:
    """The directory holding one subdirectory per CTranslate2 model."""
    override = os.environ.get(MODELS_DIR_ENV)
    if override:
        return Path(override).expanduser()
    return resource_root() / "models"


def tesseract_executable() -> Path | None:
    """The Tesseract binary to use, or None when none can be found.

    Prefers the copy shipped inside the app so the installed program never
    depends on what the user happens to have on PATH.
    """
    override = os.environ.get(TESSERACT_EXE_ENV)
    if override:
        candidate = Path(override).expanduser()
        return candidate if candidate.exists() else None

    executable = "tesseract.exe" if os.name == "nt" else "tesseract"
    bundled = resource_root() / "tesseract" / executable
    if bundled.exists():
        return bundled

    from shutil import which

    found = which(executable)
    return Path(found) if found else None


def tessdata_directory() -> Path | None:
    """The bundled language-data directory, when there is one."""
    bundled = resource_root() / "tesseract" / "tessdata"
    return bundled if bundled.is_dir() else None


def user_data_directory() -> Path:
    """Per-user writable storage for settings and scratch output."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    directory = base / "LocalPDFTranslator"
    directory.mkdir(parents=True, exist_ok=True)
    return directory
