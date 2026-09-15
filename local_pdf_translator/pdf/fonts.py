"""Finds a font file that can actually draw the target language.

This matters more than it sounds. The original PDF's fonts are almost always
subsetted to just the glyphs the source text happened to use, so they cannot be
reused for the translation, and a Latin font asked to draw Devanagari renders a
row of empty boxes.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..core.languages import Language, Script
from ..core.paths import resource_root


@dataclass(frozen=True)
class FontChoice:
    """A resolved family: the regular file, and a bold one when available."""

    regular: Path
    bold: Path | None

    def file_for(self, bold: bool) -> Path:
        return self.bold if bold and self.bold is not None else self.regular


class FontNotFound(RuntimeError):
    """No font on this machine can draw the requested script."""


def _search_directories() -> list[Path]:
    """Everywhere a font might live, most preferred first."""
    directories: list[Path] = []

    # Fonts shipped with the app win over nothing, but lose to the system's own
    # — the system copies are better hinted and always present on Windows.
    if os.name == "nt":
        windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        directories.append(windir / "Fonts")
        local = os.environ.get("LOCALAPPDATA")
        if local:
            directories.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    else:
        # Only used when developing or running the tests off Windows.
        directories.extend(
            [
                Path("/usr/share/fonts"),
                Path("/usr/local/share/fonts"),
                Path.home() / ".local/share/fonts",
                Path(sys.prefix) / "share/fonts",
            ]
        )

    directories.append(resource_root() / "fonts")
    return [directory for directory in directories if directory.is_dir()]


@lru_cache(maxsize=1)
def _font_index() -> dict[str, Path]:
    """Lower-cased file name -> full path, for every font we can see.

    Built once and cached: walking the Windows font directory takes long
    enough to be worth not repeating per page.
    """
    index: dict[str, Path] = {}
    for directory in _search_directories():
        try:
            # Windows keeps fonts flat; Linux nests them, hence the walk.
            entries = directory.rglob("*") if os.name != "nt" else directory.glob("*")
            for entry in entries:
                if entry.suffix.lower() not in {".ttf", ".otf", ".ttc"}:
                    continue
                index.setdefault(entry.name.lower(), entry)
        except OSError:  # pragma: no cover - unreadable directory
            continue
    return index


def _first_present(names: tuple[str, ...]) -> Path | None:
    index = _font_index()
    for name in names:
        found = index.get(name.lower())
        if found is not None:
            return found
    return None


@lru_cache(maxsize=8)
def font_for_script(script: Script) -> FontChoice:
    """The best available font for a script.

    Raises rather than silently falling back to a Latin face for Devanagari:
    producing a PDF full of empty boxes would be a worse outcome than a clear
    error naming the font to install.
    """
    regular = _first_present(script.regular_font_files)
    if regular is None:
        # Last resort: any font at all is better than failing for Latin, but
        # for a complex script an arbitrary font would render nothing usable.
        if script is Script.LATIN:
            index = _font_index()
            if index:
                regular = next(iter(sorted(index.values())))
        if regular is None:
            raise FontNotFound(
                f"No font for {script.value} text could be found. "
                f"Install one of: {', '.join(script.regular_font_files)}."
            )
    return FontChoice(regular=regular, bold=_first_present(script.bold_font_files))


def font_for(language: Language) -> FontChoice:
    return font_for_script(language.script)


def clear_cache() -> None:
    """Forget the font index. Used by the tests."""
    _font_index.cache_clear()
    font_for_script.cache_clear()
