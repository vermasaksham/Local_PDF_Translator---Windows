"""Copy an installed Tesseract into tesseract\\ so the build can ship it.

The app looks for tesseract\\tesseract.exe beside itself before falling back to
whatever is on PATH, so the installed program never depends on the user having
Tesseract of their own.

Install Tesseract first (the UB Mannheim build is the usual one on Windows,
https://github.com/UB-Mannheim/tesseract/wiki), then:

    python scripts\\bundle_tesseract.py

Only the language data the app actually offers is copied; the full tessdata set
is several hundred megabytes and all but three files of it would be dead weight.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from local_pdf_translator.core import languages

TARGET = REPO_ROOT / "tesseract"

DEFAULT_SOURCES = [
    Path(r"C:\Program Files\Tesseract-OCR"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR"),
    Path("/usr/share/tesseract-ocr/5"),  # only useful when testing off Windows
]

#: osd is not a language; it is the orientation and script detection model, and
#: Tesseract wants it for automatic page segmentation.
EXTRA_TRAINEDDATA = ("osd",)


def log(message: str) -> None:
    print(f"==> {message}", flush=True)


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def find_source(explicit: Path | None) -> Path:
    if explicit is not None:
        if not explicit.is_dir():
            die(f"{explicit} is not a directory")
        return explicit
    for candidate in DEFAULT_SOURCES:
        if candidate.is_dir():
            return candidate
    die(
        "Tesseract was not found. Install it, or pass --source with the path to "
        "the Tesseract-OCR folder."
    )


def find_tessdata(source: Path) -> Path:
    for candidate in (source / "tessdata", source.parent / "tessdata", source):
        if candidate.is_dir() and any(candidate.glob("*.traineddata")):
            return candidate
    die(f"no tessdata directory with .traineddata files under {source}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="the Tesseract-OCR install folder")
    arguments = parser.parse_args()

    source = find_source(arguments.source)
    log(f"Copying from {source}")

    if TARGET.exists():
        shutil.rmtree(TARGET)
    (TARGET / "tessdata").mkdir(parents=True)

    # The executable and everything it links against. Copying the whole folder
    # minus tessdata is simpler, and safer, than trying to name each DLL.
    copied = 0
    for item in source.iterdir():
        if item.is_file() and item.suffix.lower() in {".exe", ".dll"}:
            shutil.copy2(item, TARGET / item.name)
            copied += 1
    if not (TARGET / "tesseract.exe").exists() and sys.platform == "win32":
        die(f"no tesseract.exe in {source}")
    log(f"Copied {copied} binaries")

    tessdata = find_tessdata(source)
    wanted = [language.tesseract_code for language in languages.ALL] + list(EXTRA_TRAINEDDATA)
    for code in wanted:
        origin = tessdata / f"{code}.traineddata"
        if not origin.is_file():
            die(
                f"{code}.traineddata is missing from {tessdata}. Re-run the Tesseract "
                "installer and select the additional language data."
            )
        shutil.copy2(origin, TARGET / "tessdata" / origin.name)
    log(f"Copied language data: {', '.join(wanted)}")

    total = sum(item.stat().st_size for item in TARGET.rglob("*") if item.is_file())
    log(f"Bundled Tesseract is {total / 1_000_000:.0f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
