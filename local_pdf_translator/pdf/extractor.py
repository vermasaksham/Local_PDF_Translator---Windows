"""Pulls positioned text out of a PDF page using PyMuPDF's per-character boxes."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pymupdf

from .analyser import blocks_from_lines, lines_from_glyphs
from .layout import Glyph, PageLayout, Rect

#: How far a line's writing direction may deviate from horizontal and still be
#: treated as ordinary text. Rotated captions and vertical spine labels are
#: left alone rather than redrawn horizontally over the top of the original.
_HORIZONTAL_TOLERANCE = 0.05

#: A handful of characters usually means a scanned page that happens to carry a
#: stray label or a watermark, so the "has text" threshold is not zero.
MINIMUM_TEXT_CHARACTERS = 12


def page_rect(page: pymupdf.Page) -> Rect:
    """The page's box, with the origin at zero.

    Callers are expected to have neutralised page rotation first (see
    `unrotated`), so this is the space both extraction and drawing use.
    """
    rect = page.rect
    return Rect(0.0, 0.0, float(rect.width), float(rect.height))


class unrotated:  # noqa: N801 - reads as a phrase: `with unrotated(page):`
    """Context manager that temporarily removes a page's /Rotate.

    PyMuPDF reports extracted text in the *rotated* (as-displayed) coordinate
    space, but content-insertion methods interpret their coordinates in the
    *unrotated* space. Rather than juggle two spaces and a derotation matrix
    through the whole pipeline, rotation is switched off for the duration and
    restored afterwards, so extraction and drawing always agree.
    """

    def __init__(self, page: pymupdf.Page) -> None:
        self._page = page
        self._rotation = 0

    def __enter__(self) -> pymupdf.Page:
        self._rotation = self._page.rotation
        if self._rotation:
            self._page.set_rotation(0)
        return self._page

    def __exit__(self, *_: object) -> None:
        if self._rotation:
            self._page.set_rotation(self._rotation)


def glyphs_on(page: pymupdf.Page) -> list[Glyph]:
    """Every character on the page with its box, in document order.

    Returns an empty list for image-only pages, which is the signal the
    pipeline uses to fall back to OCR.
    """
    try:
        raw: dict[str, Any] = page.get_text("rawdict")
    except Exception:  # pragma: no cover - damaged file guard
        return []

    glyphs: list[Glyph] = []
    for block in raw.get("blocks", ()):
        # type 1 is an image block; it has no characters.
        if block.get("type") != 0:
            continue
        for line in block.get("lines", ()):
            if not _is_horizontal(line.get("dir")):
                continue
            for span in line.get("spans", ()):
                size = float(span.get("size", 0.0) or 0.0)
                font = str(span.get("font", ""))
                colour = int(span.get("color", 0) or 0)
                flags = int(span.get("flags", 0) or 0)
                for char in span.get("chars", ()):
                    rect = _rect_from(char.get("bbox"))
                    if rect is None:
                        continue
                    text = char.get("c", "")
                    if not text:
                        continue
                    glyphs.append(
                        Glyph(
                            text=text,
                            rect=rect,
                            size=size,
                            font=font,
                            color=colour,
                            flags=flags,
                        )
                    )
    return glyphs


def layout_of(page: pymupdf.Page, page_index: int) -> PageLayout:
    """Extract the page's paragraph structure from its embedded text layer."""
    lines = lines_from_glyphs(glyphs_on(page))
    return PageLayout(
        page_index=page_index,
        rect=page_rect(page),
        blocks=blocks_from_lines(lines),
        was_recognised=False,
    )


def has_usable_text_layer(
    page: pymupdf.Page, minimum_characters: int = MINIMUM_TEXT_CHARACTERS
) -> bool:
    """Whether the page carries enough embedded text to be worth translating
    without OCR."""
    try:
        text = page.get_text("text")
    except Exception:  # pragma: no cover - damaged file guard
        return False
    return sum(1 for character in text if not character.isspace()) >= minimum_characters


# --------------------------------------------------------------------------
# Helpers


def _is_horizontal(direction: Sequence[float] | None) -> bool:
    if not direction or len(direction) < 2:
        return True
    return (
        abs(float(direction[0]) - 1.0) < _HORIZONTAL_TOLERANCE
        and abs(float(direction[1])) < _HORIZONTAL_TOLERANCE
    )


def _rect_from(bbox: Sequence[float] | None) -> Rect | None:
    if not bbox or len(bbox) < 4:
        return None
    x0, y0, x1, y1 = (float(value) for value in bbox[:4])
    # Some producers emit boxes with the corners the wrong way round.
    rect = Rect(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
    return rect if rect.is_finite else None
