"""The languages the app offers, and the scripts they are written in."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum


class Script(Enum):
    """A writing system, which determines how the text must be drawn."""

    LATIN = "latin"
    DEVANAGARI = "devanagari"

    @property
    def regular_font_files(self) -> tuple[str, ...]:
        """Windows font file names tried in order; the first present wins.

        File names rather than family names because the PDF renderer needs a
        path to embed, not a GDI family, and because matching by file avoids a
        dependency on the font enumeration APIs.
        """
        if self is Script.DEVANAGARI:
            # Nirmala UI ships with every Windows 8+ install; Mangal is the
            # older fallback and is present on Windows 10 as well.
            return (
                "Nirmala.ttf",
                "mangal.ttf",
                # Carried in the app's own fonts/ directory as a fallback for
                # machines with no Devanagari face installed.
                "NotoSansDevanagari-Regular.ttf",
                # Trailing entries are Linux faces: they never match on
                # Windows, and they let the renderer be exercised on a build
                # machine that has no Microsoft fonts.
                "Lohit-Devanagari.ttf",
                "Samyak-Devanagari.ttf",
            )
        return (
            "segoeui.ttf",
            "calibri.ttf",
            "arial.ttf",
            "tahoma.ttf",
            "NotoSans-Regular.ttf",
            "DejaVuSans.ttf",
        )

    @property
    def bold_font_files(self) -> tuple[str, ...]:
        """Bold companions to `regular_font_files`, same ordering rule."""
        if self is Script.DEVANAGARI:
            return (
                "NirmalaB.ttf",
                "mangalb.ttf",
                "NotoSansDevanagari-Bold.ttf",
                "Lohit-Devanagari-Bold.ttf",
            )
        return (
            "segoeuib.ttf",
            "calibrib.ttf",
            "arialbd.ttf",
            "tahomabd.ttf",
            "NotoSans-Bold.ttf",
            "DejaVuSans-Bold.ttf",
        )

    @property
    def needs_shaping(self) -> bool:
        """Whether correct rendering requires a complex-text shaping engine.

        Devanagari reorders matras and forms conjuncts, so drawing its code
        points in logical order produces text that is wrong rather than merely
        ugly. See `pdf.textpainter` for how that is handled.
        """
        return self is Script.DEVANAGARI


@dataclass(frozen=True)
class Language:
    """A translatable language.

    Deliberately a record in a registry rather than an enum member: adding a
    language should be a data change (one entry here plus models in
    `ModelCatalog`), never a change that forces every branch in the app to be
    revisited.
    """

    # ISO 639-1 code as used by the OPUS-MT model names (en, de, hi).
    code: str
    # Name shown in the UI, in the language itself.
    native_name: str
    # Name shown in the UI, in English.
    english_name: str
    script: Script
    # Tesseract's own three-letter code, used when OCR-ing a scanned document.
    tesseract_code: str

    def __str__(self) -> str:  # pragma: no cover - display only
        return self.english_name


ENGLISH = Language("en", "English", "English", Script.LATIN, "eng")
GERMAN = Language("de", "Deutsch", "German", Script.LATIN, "deu")
HINDI = Language("hi", "हिन्दी", "Hindi", Script.DEVANAGARI, "hin")

#: Every language the app offers, in menu order.
#:
#: To add one: append it here and add the matching models to
#: `ModelCatalog.BUNDLED`. Nothing else needs to change.
ALL: tuple[Language, ...] = (ENGLISH, GERMAN, HINDI)


def named(code: str) -> Language | None:
    """The language with this ISO code, case-insensitively."""
    lowered = code.strip().lower()
    return next((language for language in ALL if language.code == lowered), None)


def first_other_than(language: Language, among: Iterable[Language] = ALL) -> Language | None:
    """The first language in `among` that is not `language`."""
    return next((candidate for candidate in among if candidate != language), None)


@dataclass(frozen=True)
class LanguagePair:
    """A directed language pair. `en->de` and `de->en` are distinct models."""

    source: Language
    target: Language

    @property
    def is_identity(self) -> bool:
        return self.source == self.target

    def __str__(self) -> str:
        return f"{self.source.code}->{self.target.code}"
