"""Download the fallback fonts the build bundles.

The app prefers the fonts already on the machine — Nirmala UI is on every
ordinary Windows 8+ install and is better hinted than anything shipped here.
But it is not on every machine: Windows Server images often lack it, N editions
can, and it can be removed. Without a Devanagari face the app cannot draw Hindi
at all, so one is carried as a fallback.

    python scripts/fetch_fonts.py

Noto Sans Devanagari is licensed under the SIL Open Font License 1.1, which
permits redistribution. Anything added here must be added to
THIRD-PARTY-NOTICES.md as well.
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FONTS_DIR = REPO_ROOT / "fonts"

_BASE = (
    "https://raw.githubusercontent.com/notofonts/notofonts.github.io/main/"
    "fonts/NotoSansDevanagari/hinted/ttf"
)
FONTS = {
    "NotoSansDevanagari-Regular.ttf": f"{_BASE}/NotoSansDevanagari-Regular.ttf",
    "NotoSansDevanagari-Bold.ttf": f"{_BASE}/NotoSansDevanagari-Bold.ttf",
}

#: The licence has to travel with the fonts.
LICENCE = ("OFL.txt", "https://raw.githubusercontent.com/notofonts/devanagari/main/OFL.txt")

#: A TrueType file starts with one of these; used to catch a proxy error page
#: being saved as a font, which otherwise fails much later and confusingly.
_TRUETYPE_MAGIC = (b"\x00\x01\x00\x00", b"true", b"ttcf", b"OTTO")


def log(message: str) -> None:
    print(f"==> {message}", flush=True)


def main() -> int:
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    for name, url in FONTS.items():
        target = FONTS_DIR / name
        if target.is_file() and target.stat().st_size > 1000:
            log(f"{name} is already present")
            continue

        log(f"Downloading {name}")
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                data = response.read()
        except Exception as failure:
            print(f"error: could not download {name}: {failure}", file=sys.stderr)
            return 1

        if not data.startswith(_TRUETYPE_MAGIC):
            print(
                f"error: what came back for {name} is not a TrueType font "
                f"({len(data)} bytes). Check the network path.",
                file=sys.stderr,
            )
            return 1
        target.write_bytes(data)
        log(f"  {len(data) / 1024:.0f} KB")

    name, url = LICENCE
    target = FONTS_DIR / name
    if not target.is_file():
        log(f"Downloading {name}")
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                target.write_bytes(response.read())
        except Exception as failure:
            print(f"error: could not download {name}: {failure}", file=sys.stderr)
            return 1

    log(f"Fonts ready in {FONTS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
